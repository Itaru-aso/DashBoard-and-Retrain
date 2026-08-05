"""train(color/monochro)の学習ループ間で完全に重複していた低レベル関数。

以下は train_func_color.py / train_func_monochro.py の両方で機能的に
100%同一だった関数のみを集約している。学習ループ本体(train_color/
train_monochro)やmonochro固有ロジック(raw_shift・normalize_mode・
cand1較正等)はここには含まれない。
"""
import json

import numpy as np
import torch
from torchvision import transforms
from tqdm import tqdm

from utils.edge_mask import slice_edge_excluded

# train.color / train.monochro それぞれのモジュールにも同名の定数が
# 独立して存在する(意図的な重複、副作用のない冪等な再計算のため安全)。
out_channels = 384
on_gpu = torch.cuda.is_available()


def numpy_encoder(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return json.JSONEncoder().default(obj)


def focal_feature_loss(distance, gamma=2.0):
    """Focal Feature Loss: 困難な特徴ほど重みが大きくなる連続的な損失関数。

    Hard Feature Lossがquantile閾値で離散的に上位0.1%だけ選択するのに対し、
    全特徴に連続的な重み付けを行うことで学習を安定させる。

    Args:
        distance: Teacher-Student間の二乗距離テンソル
        gamma: 集中度パラメータ (大きいほど困難な特徴に集中)
    """
    d_norm = distance / (distance.max().detach() + 1e-8)
    weights = d_norm ** gamma
    return torch.mean(weights * distance)


class GaussianNoise:
    """ガウシアンノイズを付加する変換（pickle可能）"""
    def __init__(self, std=0.02):
        self.std = std

    def __call__(self, image):
        import torchvision.transforms.functional as TF
        tensor = TF.to_tensor(image)
        noise = torch.randn_like(tensor) * self.std
        tensor = torch.clamp(tensor + noise, 0.0, 1.0)
        return TF.to_pil_image(tensor)


class RandomSharpness:
    """factor を [factor_min, factor_max] の一様乱数で引く鮮明化変換（pickle可能）。

    torchvision 標準の RandomAdjustSharpness は factor 固定のため、
    連続範囲で良品多様体を広げる目的に合わない。撮像環境ドリフト
    （照明交換・台数展開でのシャープネス差）への頑強性獲得用
    (@.kiro/specs/retraining/st-augmentation-sharpness-robustness.md)。
    """
    def __init__(self, factor_min=1.0, factor_max=2.0, p=0.5):
        self.factor_min = factor_min
        self.factor_max = factor_max
        self.p = p

    def __call__(self, image):
        import torchvision.transforms.functional as TF
        if torch.rand(1).item() >= self.p:
            return image
        factor = self.factor_min + (self.factor_max - self.factor_min) * torch.rand(1).item()
        return TF.adjust_sharpness(image, factor)


def get_st_transform(cfg):
    """ST入力用の軽微なAugmentationを構築する（configで無効化可能）。

    sharpen/blur は撮像環境ドリフト頑強性用（既定無効・monochro のみ config で有効化。
    パラメータ較正の実測根拠は ADR 参照）。
    """
    st_cfg = cfg.get('st_augmentation', None)
    if st_cfg is None or not st_cfg.get('enabled', False):
        return None
    tf_list = []
    if st_cfg.get('horizontal_flip', False):
        tf_list.append(transforms.RandomHorizontalFlip())
    brightness = st_cfg.get('color_jitter_brightness', 0)
    contrast = st_cfg.get('color_jitter_contrast', 0)
    saturation = st_cfg.get('color_jitter_saturation', 0)
    if brightness > 0 or contrast > 0 or saturation > 0:
        tf_list.append(transforms.ColorJitter(
            brightness=brightness, contrast=contrast, saturation=saturation))
    sharpen_p = st_cfg.get('sharpen_p', 0)
    if sharpen_p > 0:
        tf_list.append(RandomSharpness(
            factor_min=st_cfg.get('sharpen_factor_min', 1.0),
            factor_max=st_cfg.get('sharpen_factor_max', 2.0),
            p=sharpen_p))
    blur_p = st_cfg.get('gaussian_blur_p', 0)
    if blur_p > 0:
        sigma_max = st_cfg.get('gaussian_blur_sigma_max', 0.6)
        tf_list.append(transforms.RandomApply(
            [transforms.GaussianBlur(kernel_size=5, sigma=(0.1, sigma_max))], p=blur_p))
    if not tf_list:
        return None
    return transforms.Compose(tf_list)


class TrainTransform:
    """pickle可能なtrain transform（Windows multiprocessing対応）"""
    def __init__(self, pre_tf, default_tf, st_tf=None):
        self.pre_tf = pre_tf
        self.default_tf = default_tf
        self.st_tf = st_tf

    def __call__(self, image):
        # ST入力: 軽微なaugmentation（configで制御、Noneなら原論文準拠）
        if self.st_tf is not None:
            st_image = self.default_tf(self.st_tf(image))
        else:
            st_image = self.default_tf(image)
        # AE入力: augmentationあり
        ae_image = self.default_tf(self.pre_tf(image))
        return st_image, ae_image


@torch.no_grad()
def predict(image, teacher, student, autoencoder, teacher_mean, teacher_std, st_para, ae_para,
            q_st_start=None, q_st_end=None, q_ae_start=None, q_ae_end=None,
            channel_weights=None):
    teacher_output = teacher(image)
    teacher_output = (teacher_output - teacher_mean) / teacher_std
    student_output = student(image)
    autoencoder_output = autoencoder(image)

    diff_st = (teacher_output - student_output[:, :out_channels])**2
    if channel_weights is not None:
        map_st = torch.sum(diff_st * channel_weights, dim=1, keepdim=True)
    else:
        map_st = torch.mean(diff_st, dim=1, keepdim=True)

    map_ae = torch.mean((autoencoder_output -
                        student_output[:, out_channels:])**2,
                        dim=1, keepdim=True)
    if q_st_start is not None:
        map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
    if q_ae_start is not None:
        map_ae = 0.1 * (map_ae - q_ae_start) / (q_ae_end - q_ae_start)
    map_combined = st_para * map_st + ae_para * map_ae

    return map_combined, map_st, map_ae


@torch.no_grad()
def map_normalization(validation_loader, teacher, student, autoencoder,
                    teacher_mean, teacher_std, st_para, ae_para, desc='Map normalization',
                    channel_weights=None, edge_mask_w=0):
    maps_st = []
    maps_ae = []
    # teacher が乗っている device を採用 (cuda:0 ハードコードを廃止)
    device = next(teacher.parameters()).device
    # ignore augmented ae image
    for image, _ in tqdm(validation_loader, desc=desc):
        if on_gpu:
            image = image.to(device)
        map_combined, map_st, map_ae = predict(
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
def teacher_normalization(teacher, train_loader):

    mean_outputs = []

    # teacher が乗っている device を採用 (cuda:0 ハードコードを廃止)
    device = next(teacher.parameters()).device

    for train_image, _ in tqdm(train_loader, desc='Computing mean of features'):
        if on_gpu:
            train_image = train_image.to(device)
        teacher_output = teacher(train_image)
        mean_output = torch.mean(teacher_output, dim=[0, 2, 3])
        mean_outputs.append(mean_output)
    channel_mean = torch.mean(torch.stack(mean_outputs), dim=0)
    channel_mean = channel_mean[None, :, None, None]

    mean_distances = []
    for train_image, _ in tqdm(train_loader, desc='Computing std of features'):
        if on_gpu:
            train_image = train_image.to(device)
        teacher_output = teacher(train_image)
        distance = (teacher_output - channel_mean) ** 2
        mean_distance = torch.mean(distance, dim=[0, 2, 3])
        mean_distances.append(mean_distance)
    channel_var = torch.mean(torch.stack(mean_distances), dim=0)
    channel_var = channel_var[None, :, None, None]
    channel_std = torch.sqrt(channel_var)

    return channel_mean, channel_std
