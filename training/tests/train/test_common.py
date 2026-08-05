"""train.common の8関数が、抽出前のtrain_func_color.py/train_func_monochro.py
の該当関数と数値的に一致することを保証するテスト。

_reference_* 関数は抽出前の training/train_func_color.py の関数本体を
字句通り複製した参照実装(train_func_monochro.py側も機能的に同一である
ことは事前調査で確認済み)。

実行: cd training && python -m pytest tests/train/test_common.py -v
"""
import json

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

OUT_CHANNELS = 384


def _reference_numpy_encoder(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return json.JSONEncoder().default(obj)


def _reference_focal_feature_loss(distance, gamma=2.0):
    d_norm = distance / (distance.max().detach() + 1e-8)
    weights = d_norm ** gamma
    return torch.mean(weights * distance)


@torch.no_grad()
def _reference_predict(image, teacher, student, autoencoder, teacher_mean, teacher_std,
                       st_para, ae_para, q_st_start=None, q_st_end=None,
                       q_ae_start=None, q_ae_end=None, channel_weights=None):
    teacher_output = teacher(image)
    teacher_output = (teacher_output - teacher_mean) / teacher_std
    student_output = student(image)
    autoencoder_output = autoencoder(image)

    diff_st = (teacher_output - student_output[:, :OUT_CHANNELS]) ** 2
    if channel_weights is not None:
        map_st = torch.sum(diff_st * channel_weights, dim=1, keepdim=True)
    else:
        map_st = torch.mean(diff_st, dim=1, keepdim=True)

    map_ae = torch.mean((autoencoder_output - student_output[:, OUT_CHANNELS:]) ** 2,
                        dim=1, keepdim=True)
    if q_st_start is not None:
        map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
    if q_ae_start is not None:
        map_ae = 0.1 * (map_ae - q_ae_start) / (q_ae_end - q_ae_start)
    map_combined = st_para * map_st + ae_para * map_ae
    return map_combined, map_st, map_ae


@torch.no_grad()
def _reference_map_normalization(validation_loader, teacher, student, autoencoder,
                                 teacher_mean, teacher_std, st_para, ae_para,
                                 desc='Map normalization', channel_weights=None,
                                 edge_mask_w=0):
    from utils.edge_mask import slice_edge_excluded

    maps_st = []
    maps_ae = []
    device = next(teacher.parameters()).device
    for image, _ in validation_loader:
        image = image.to(device)
        map_combined, map_st, map_ae = _reference_predict(
            image=image, teacher=teacher, student=student,
            autoencoder=autoencoder, teacher_mean=teacher_mean,
            teacher_std=teacher_std, st_para=st_para, ae_para=ae_para,
            channel_weights=channel_weights)
        maps_st.append(slice_edge_excluded(map_st, edge_mask_w))
        maps_ae.append(slice_edge_excluded(map_ae, edge_mask_w))
    maps_st = torch.cat(maps_st).cpu().numpy().flatten()
    maps_ae = torch.cat(maps_ae).cpu().numpy().flatten()
    q_st_start = torch.tensor(np.quantile(maps_st, 0.9))
    q_st_end = torch.tensor(np.quantile(maps_st, 0.995))
    q_ae_start = torch.tensor(np.quantile(maps_ae, 0.9))
    q_ae_end = torch.tensor(np.quantile(maps_ae, 0.995))
    return q_st_start, q_st_end, q_ae_start, q_ae_end


@torch.no_grad()
def _reference_teacher_normalization(teacher, train_loader):
    mean_outputs = []
    device = next(teacher.parameters()).device
    for train_image, _ in train_loader:
        train_image = train_image.to(device)
        teacher_output = teacher(train_image)
        mean_output = torch.mean(teacher_output, dim=[0, 2, 3])
        mean_outputs.append(mean_output)
    channel_mean = torch.mean(torch.stack(mean_outputs), dim=0)
    channel_mean = channel_mean[None, :, None, None]

    mean_distances = []
    for train_image, _ in train_loader:
        train_image = train_image.to(device)
        teacher_output = teacher(train_image)
        distance = (teacher_output - channel_mean) ** 2
        mean_distance = torch.mean(distance, dim=[0, 2, 3])
        mean_distances.append(mean_distance)
    channel_var = torch.mean(torch.stack(mean_distances), dim=0)
    channel_var = channel_var[None, :, None, None]
    channel_std = torch.sqrt(channel_var)
    return channel_mean, channel_std


class _TinyImageDataset(Dataset):
    """(image_tensor, label) を返す最小限の合成データセット。"""
    def __init__(self, num_samples, channels, height, width, seed):
        torch.manual_seed(seed)
        self.images = [torch.rand(channels, height, width) for _ in range(num_samples)]

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        return self.images[idx], 0


def test_numpy_encoder_matches_reference():
    from train.common import numpy_encoder

    arr = np.array([1.0, 2.0, 3.0])
    assert numpy_encoder(arr) == _reference_numpy_encoder(arr)

    try:
        numpy_encoder(object())
        assert False, "TypeError が発生するはず"
    except TypeError:
        pass


def test_focal_feature_loss_matches_reference():
    from train.common import focal_feature_loss

    torch.manual_seed(0)
    distance = torch.rand(4, 8, 8)
    actual = focal_feature_loss(distance, gamma=2.0)
    expected = _reference_focal_feature_loss(distance, gamma=2.0)
    assert torch.allclose(actual, expected)


def test_gaussian_noise_produces_valid_image():
    from PIL import Image

    from train.common import GaussianNoise

    torch.manual_seed(0)
    img = Image.new("RGB", (16, 16), color=(128, 128, 128))
    noisy = GaussianNoise(std=0.05)(img)
    assert isinstance(noisy, Image.Image)
    assert noisy.size == (16, 16)


def test_get_st_transform_disabled_returns_none():
    from omegaconf import OmegaConf

    from train.common import get_st_transform

    cfg = OmegaConf.create({"st_augmentation": {"enabled": False}})
    assert get_st_transform(cfg) is None


def test_get_st_transform_enabled_returns_compose():
    from omegaconf import OmegaConf

    from train.common import get_st_transform

    cfg = OmegaConf.create({
        "st_augmentation": {
            "enabled": True,
            "horizontal_flip": True,
            "color_jitter_brightness": 0.1,
            "color_jitter_contrast": 0.1,
            "color_jitter_saturation": 0.0,
        }
    })
    result = get_st_transform(cfg)
    assert isinstance(result, transforms.Compose)


def _flatten_transforms(compose):
    """Compose 内の transform を再帰的に平坦化してクラス名リストを返す。"""
    names = []
    for t in compose.transforms:
        names.append(type(t).__name__)
        inner = getattr(t, "transforms", None)
        if inner is not None:
            for it in inner:
                names.append(type(it).__name__)
    return names


def test_get_st_transform_new_keys_absent_keeps_legacy_transforms_only():
    """新キー未設定（既定）では blur/sharpen が変換列に含まれない（後方互換）。"""
    from omegaconf import OmegaConf

    from train.common import get_st_transform

    cfg = OmegaConf.create({
        "st_augmentation": {
            "enabled": True,
            "horizontal_flip": True,
            "color_jitter_brightness": 0.1,
            "color_jitter_contrast": 0.1,
            "color_jitter_saturation": 0.0,
        }
    })
    names = _flatten_transforms(get_st_transform(cfg))
    assert "RandomSharpness" not in names
    assert "GaussianBlur" not in names


def test_get_st_transform_sharpen_enabled_adds_random_sharpness():
    """sharpen_p>0 で RandomSharpness が変換列に追加される。"""
    from omegaconf import OmegaConf

    from train.common import get_st_transform

    cfg = OmegaConf.create({
        "st_augmentation": {
            "enabled": True,
            "sharpen_p": 0.3,
            "sharpen_factor_min": 1.0,
            "sharpen_factor_max": 2.0,
        }
    })
    names = _flatten_transforms(get_st_transform(cfg))
    assert "RandomSharpness" in names


def test_get_st_transform_blur_enabled_adds_gaussian_blur():
    """gaussian_blur_p>0 で RandomApply(GaussianBlur) が変換列に追加される。"""
    from omegaconf import OmegaConf

    from train.common import get_st_transform

    cfg = OmegaConf.create({
        "st_augmentation": {
            "enabled": True,
            "gaussian_blur_p": 0.3,
            "gaussian_blur_sigma_max": 0.6,
        }
    })
    names = _flatten_transforms(get_st_transform(cfg))
    assert "RandomApply" in names
    assert "GaussianBlur" in names


def test_random_sharpness_deterministic_apply_increases_sharpness():
    """RandomSharpness を p=1.0・factor固定で適用するとシャープネスが実際に上がる。"""
    import cv2
    from PIL import Image

    from train.common import RandomSharpness

    rng = np.random.RandomState(0)
    arr = rng.randint(60, 200, size=(64, 128, 3), dtype=np.uint8)
    img = Image.fromarray(arr)

    def lap_var(pil):
        gray = np.array(pil.convert("L"), dtype=np.float64)
        return cv2.Laplacian(gray, cv2.CV_64F).var()

    tf = RandomSharpness(factor_min=2.0, factor_max=2.0, p=1.0)
    out = tf(img)
    assert isinstance(out, Image.Image)
    assert out.size == img.size
    assert lap_var(out) > lap_var(img) * 1.2


def test_random_sharpness_p_zero_is_identity():
    """p=0 では画像が変換されない。"""
    from PIL import Image

    from train.common import RandomSharpness

    rng = np.random.RandomState(1)
    arr = rng.randint(0, 255, size=(32, 32, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    out = RandomSharpness(factor_min=1.0, factor_max=3.0, p=0.0)(img)
    assert np.array_equal(np.array(out), np.array(img))


def test_st_transform_with_new_augs_is_picklable():
    """Windows multiprocessing 対応: 新変換を含む st_tf が pickle 可能であること。"""
    import pickle

    from omegaconf import OmegaConf

    from train.common import get_st_transform

    cfg = OmegaConf.create({
        "st_augmentation": {
            "enabled": True,
            "horizontal_flip": True,
            "color_jitter_brightness": 0.1,
            "sharpen_p": 0.3,
            "sharpen_factor_max": 2.0,
            "gaussian_blur_p": 0.3,
            "gaussian_blur_sigma_max": 0.6,
        }
    })
    tf = get_st_transform(cfg)
    restored = pickle.loads(pickle.dumps(tf))
    assert isinstance(restored, transforms.Compose)


def test_train_transform_applies_both_paths():
    from PIL import Image

    from train.common import TrainTransform

    img = Image.new("RGB", (16, 16), color=(128, 128, 128))
    default_tf = transforms.ToTensor()
    pre_tf = transforms.Compose([])  # no-op

    tt = TrainTransform(pre_tf, default_tf, st_tf=None)
    st_image, ae_image = tt(img)
    assert st_image.shape == (3, 16, 16)
    assert ae_image.shape == (3, 16, 16)


def test_predict_matches_reference():
    from utils.common import get_autoencoder, get_pdn_small

    from train.common import predict

    torch.manual_seed(0)
    teacher = get_pdn_small(OUT_CHANNELS)
    student = get_pdn_small(2 * OUT_CHANNELS)
    autoencoder = get_autoencoder(OUT_CHANNELS, image_size_height=256, image_size_width=512)
    teacher.eval()
    student.eval()
    autoencoder.eval()

    image = torch.rand(1, 3, 256, 512)
    teacher_mean = torch.zeros(1, OUT_CHANNELS, 1, 1)
    teacher_std = torch.ones(1, OUT_CHANNELS, 1, 1)

    with torch.no_grad():
        actual = predict(image, teacher, student, autoencoder, teacher_mean, teacher_std,
                          st_para=1.0, ae_para=0.5)
        expected = _reference_predict(image, teacher, student, autoencoder,
                                      teacher_mean, teacher_std, st_para=1.0, ae_para=0.5)

    for a, e in zip(actual, expected):
        assert torch.allclose(a, e)


def test_map_normalization_matches_reference():
    from utils.common import get_autoencoder, get_pdn_small

    from train.common import map_normalization

    torch.manual_seed(0)
    teacher = get_pdn_small(OUT_CHANNELS)
    student = get_pdn_small(2 * OUT_CHANNELS)
    autoencoder = get_autoencoder(OUT_CHANNELS, image_size_height=256, image_size_width=512)
    teacher.eval()
    student.eval()
    autoencoder.eval()

    dataset = _TinyImageDataset(num_samples=3, channels=3, height=256, width=512, seed=1)
    loader = DataLoader(dataset, batch_size=1)

    teacher_mean = torch.zeros(1, OUT_CHANNELS, 1, 1)
    teacher_std = torch.ones(1, OUT_CHANNELS, 1, 1)

    actual = map_normalization(loader, teacher, student, autoencoder,
                               teacher_mean, teacher_std, st_para=1.0, ae_para=0.5)
    expected = _reference_map_normalization(loader, teacher, student, autoencoder,
                                            teacher_mean, teacher_std, st_para=1.0, ae_para=0.5)

    for a, e in zip(actual, expected):
        assert torch.allclose(a, e)


def test_teacher_normalization_matches_reference():
    from utils.common import get_pdn_small

    from train.common import teacher_normalization

    torch.manual_seed(0)
    teacher = get_pdn_small(OUT_CHANNELS)
    teacher.eval()

    dataset = _TinyImageDataset(num_samples=3, channels=3, height=256, width=512, seed=2)
    loader = DataLoader(dataset, batch_size=1)

    actual_mean, actual_std = teacher_normalization(teacher, loader)
    expected_mean, expected_std = _reference_teacher_normalization(teacher, loader)

    assert torch.allclose(actual_mean, expected_mean)
    assert torch.allclose(actual_std, expected_std)
