# training/ モジュラモノリス移行 Seam5: trainの共通化(低レベル関数のみ) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `training/train_func_color.py`と`training/train_func_monochro.py`の間で完全に(機能的に)重複している8つの低レベル関数を`training/train/common.py`という共有モジュールへ抽出し、両ファイルを新設パッケージ`training/train/`(`training/train/color.py`・`training/train/monochro.py`)へ移動する。学習ループ本体(`train_color`/`train_monochro`)とmonochro固有ロジックは一切変更しない。

**Architecture:** strangler-fig方式。Seam1/2/4と同じ「挙動保存の抽出」。ただし対象が学習ループ内の低レベル関数であるため、Seam3 Task1で確立した「抽出前の関数本体を字句通り複製した参照実装との数値一致」パターンで検証する。先行実装 `D:\0032011\GitLab\shisui\EfficientAD` の同名Seam（`docs/superpowers/plans/2026-07-15-modular-monolith-seam5-training-common.md`）を参照。

**Tech Stack:** Python, PyTorch, pytest。

## Global Constraints

- **今回共通化する関数は以下8つのみ**(調査により機能的に100%同一であることを確認済み)。他の関数(`evaluate_validation_loss`・`get_pre_transform`・`_resolve_teacher_weights_path`)や`train_color`/`train_monochro`本体は**1文字も変更しない**:
  - `numpy_encoder(obj)`
  - `focal_feature_loss(distance, gamma=2.0)`
  - `class GaussianNoise`
  - `get_st_transform(cfg)`
  - `class TrainTransform`
  - `predict(image, teacher, student, autoencoder, teacher_mean, teacher_std, st_para, ae_para, q_st_start=None, q_st_end=None, q_ae_start=None, q_ae_end=None, channel_weights=None)`(`@torch.no_grad()`付き)
  - `map_normalization(validation_loader, teacher, student, autoencoder, teacher_mean, teacher_std, st_para, ae_para, desc='Map normalization', channel_weights=None, edge_mask_w=0)`(`@torch.no_grad()`付き)
  - `teacher_normalization(teacher, train_loader)`(`@torch.no_grad()`付き)
- **既知の既存不整合(このSeamでは修正しない)**: `evaluate_validation_loss`はcolor版(`training/train_func_color.py:563-588`)がedge_mask未適用、monochro版(`training/train_func_monochro.py:672-708`)が適用済み。monochro側の関数docstring・コメントには「color側も対称適用済」という誤った記述があるが、この関数は共通化の対象外(完全重複ではない)のため、コード・コメントとも一切変更しない
- **module-level定数は移動しない**: `seed=42`、`random.seed(0)`(副作用あり)、`on_gpu = torch.cuda.is_available()`、`out_channels = 384`は各ファイルにそのまま残す。`training/train/common.py`側には抽出した3関数(`predict`/`map_normalization`/`teacher_normalization`)が必要とする`out_channels`/`on_gpu`を**独立して**定義する(副作用のない冪等な再計算のため、値は常に一致し安全)。`random.seed(0)`のような副作用のある呼び出しタイミングには触れない
- テスト方針: 抽出前の各関数本体を字句通り複製した「参照実装」との数値一致を検証する(Seam3 Task1のパターンを踏襲)。緩い許容誤差は使わない(`torch.allclose`の既定値、または完全一致)。学習ループ全体のエンドツーエンド再現性テストは、学習ループ本体を共通化する将来のSeamのスコープであり、本計画では行わない
- **命名**: 学習ステージのパッケージ名は`train`とする(`training`ではない。設計書ADR-app1: 対象範囲自体が`training/`ディレクトリのため、EfficientADの`training/`パッケージ名をそのまま使うと`training/training/color.py`のような入れ子になるため回避)
- Seam1/2/4と同じ「stage-primaryパッケージング + 公開APIは関数、内部モジュールはCI gateで直接import禁止」規約に従う
- CI gateの走査対象は`training/`配下に限定する(設計書ADR-app4)
- `training/tests/`配下は基本的に`__init__.py`を作らない(既存方針、conftest.py方式。Seam3の`tests/model/`と同様、本Seamの`tests/train/`にも`__init__.py`は作らない)
- `training/pipline.py`には本Seamと無関係な既存WIP(`_spawn_with_gpu_env`のspawn-context修正)が作業ツリーに残っている。Task2のコミット前に混入がないことを確認する
- 日本語コミットメッセージ、Conventional Commits形式(`<type>(<scope>): <subject>`)
- 自分の変更で未使用になったimportは削除するが、元から未使用だったimport(`train_func_color.py`の`pandas`/`seaborn`/`tifffile`/`argparse`/`shutil`/`glob`/`sklearn.metrics`の一部等、既知のdead code)はこのSeamでは一切触らない
- 呼び出し元は`training/pipline.py`のみ(grep確認済み): **25-26行目**`from train_func_monochro import train_monochro` / `from train_func_color import train_color`、**416行目**`train_monochro(sub_cfg, mgr=mgr)`、**419行目**`train_color(sub_cfg, mgr=mgr)`
- ベースラインテスト: `cd training && python -m pytest tests/ -v` で **32 passed**(2026-07-21時点、Seam1〜4完了後。実測済み)

---

## Task 1: `training/train/common.py`への8関数抽出 + 参照実装との数値一致テスト

**Files:**
- Create: `training/train/__init__.py`(この時点では公開APIはまだ確定しない、Task2で`train_color`/`train_monochro`を追加する)
- Create: `training/train/common.py`
- Create: `training/tests/train/test_common.py`

**Interfaces:**
- Produces: `train.common.numpy_encoder(obj)`, `train.common.focal_feature_loss(distance, gamma=2.0)`, `train.common.GaussianNoise`, `train.common.get_st_transform(cfg)`, `train.common.TrainTransform`, `train.common.predict(...)`, `train.common.map_normalization(...)`, `train.common.teacher_normalization(...)` — いずれも元の`training/train_func_color.py`のシグネチャと完全一致
- Consumes: `torch`, `numpy`, `tqdm`, `torchvision.transforms`, `utils.edge_mask.slice_edge_excluded`(いずれも既存)

- [ ] **Step 1: `training/train/`パッケージの器を作る**

`training/train/__init__.py`を新規作成する(この時点では公開APIはまだ確定しない、Task2で`train_color`/`train_monochro`を追加する):

```python
"""trainステージの公開API。

trainパッケージ外からは `train.train_color` / `train.train_monochro`
のみを使用すること。`train.common` / `train.color` / `train.monochro`
内の関数を外部から直接importしてはならない
（境界はtests/ci_gates/test_training_boundary.pyで検証）。
"""
```

- [ ] **Step 2: 失敗するテストを書く(共有モジュールがまだ存在しない)**

`training/tests/train/test_common.py`を新規作成する:

```python
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
```

- [ ] **Step 3: テストを実行して失敗を確認する**

Run: `cd training && python -m pytest tests/train/test_common.py -v`
Expected: 全件`ModuleNotFoundError: No module named 'train.common'`でFAIL

- [ ] **Step 4: `training/train/common.py`を実装する**

`training/train/common.py`を新規作成する。以下は`training/train_func_color.py`の該当関数の内容をそのまま(docstring・コメントは元のcolor版のものを採用、monochro版とロジックは機能的に同一であることは事前調査で確認済み)移した内容:

```python
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


def get_st_transform(cfg):
    """ST入力用の軽微なAugmentationを構築する（configで無効化可能）"""
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
```

- [ ] **Step 5: テストを実行して成功を確認する**

Run: `cd training && python -m pytest tests/train/test_common.py -v`
Expected: 全件PASS(9件)

- [ ] **Step 6: コミット**

```bash
git add training/train/__init__.py training/train/common.py training/tests/train/test_common.py
git commit -m "$(cat <<'EOF'
feat(training-train): train_func_color/monochroで完全重複していた8関数をtrain/common.pyへ抽出

training/train_func_color.py・training/train_func_monochro.pyの間で
機能的に100%同一だった8関数(numpy_encoder/focal_feature_loss/
GaussianNoise/get_st_transform/TrainTransform/predict/map_normalization/
teacher_normalization)をtraining/train/common.pyへ抽出。抽出前の関数本体を
字句通り複製した参照実装との数値一致をtests/train/test_common.pyで検証。
学習ループ本体(train_color/train_monochro)・monochro固有ロジックは
1文字も変更なし。
EOF
)"
```

---

## Task 2: `training/train/color.py`・`training/train/monochro.py`への移動、`pipline.py`リダイレクト、CI gate追加

**Files:**
- Create: `training/train/color.py`(`training/train_func_color.py`を移動、8関数を除去)
- Create: `training/train/monochro.py`(`training/train_func_monochro.py`を移動、8関数を除去)
- Modify: `training/train/__init__.py`(公開API追加)
- Modify: `training/pipline.py:25-26`
- Create: `training/tests/ci_gates/test_training_boundary.py`
- Delete: `training/train_func_color.py`, `training/train_func_monochro.py`(`git mv`により実質的に削除)

**Interfaces:**
- Consumes: Task1で作成した`train.common`の8関数(既存のimport文をそのまま使う)
- Produces: `train.train_color(cfg, mgr=None) -> None`, `train.train_monochro(cfg, mgr=None) -> None`(既存のシグネチャと完全一致)

- [ ] **Step 1: `training/train_func_color.py`を`training/train/color.py`へ移動する**

```bash
git mv training/train_func_color.py training/train/color.py
```

- [ ] **Step 2: `training/train/color.py`から8関数を削除し、importに置き換える**

`training/train/color.py`の先頭import部分、以下の行(21行目):

```python
from utils.common import get_autoencoder_256_512, get_autoencoder, get_pdn_small, get_pdn_medium, \
    ImageFolderWithoutTarget, ImageFolderWithPath, InfiniteDataloader, OpenCVResize
```

の直後に、以下の1行を追加する:

```python
from train.common import (numpy_encoder, focal_feature_loss, GaussianNoise,
                          get_st_transform, TrainTransform, predict,
                          map_normalization, teacher_normalization)
```

次に、以下の関数/クラス定義ブロックをそれぞれ削除する(各ブロックの直前・直後の空行は1つだけ残すよう調整すること):

削除対象1(`numpy_encoder`、27-31行目、コメント「# numpyをjson形式に対応させるための関数」含む):
```python
# numpyをjson形式に対応させるための関数
def numpy_encoder(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return json.JSONEncoder().default(obj)
```

削除対象2(`focal_feature_loss`、39-51行目):
```python
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
```

削除対象3(`GaussianNoise`、69-79行目):
```python
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
```

削除対象4(`get_st_transform`、105-121行目):
```python
def get_st_transform(cfg):
    """ST入力用の軽微なAugmentationを構築する（configで無効化可能）"""
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
    if not tf_list:
        return None
    return transforms.Compose(tf_list)
```

削除対象5(`TrainTransform`、123-138行目):
```python
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
```

削除対象6(`predict`・`map_normalization`・`teacher_normalization`、591-674行目、3関数連続しているブロック):
```python
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
```

削除後、`evaluate_validation_loss`の`return total_loss / count`の直後は空行を挟んで`if __name__ == '__main__':`ブロックに直接つながる状態になる。

- [ ] **Step 3: `training/train_func_monochro.py`を`training/train/monochro.py`へ移動する**

```bash
git mv training/train_func_monochro.py training/train/monochro.py
```

- [ ] **Step 4: `training/train/monochro.py`から8関数を削除し、importに置き換える**

`training/train/monochro.py`の先頭import部分、以下の行(22-23行目):

```python
from utils.common import (get_autoencoder, get_pdn_small, get_pdn_medium,
                          ImageFolderWithoutTarget, InfiniteDataloader)
```

の直後に、以下の1行を追加する:

```python
from train.common import (numpy_encoder, focal_feature_loss, GaussianNoise,
                          get_st_transform, TrainTransform, predict,
                          map_normalization, teacher_normalization)
```

次に、以下の関数/クラス定義ブロックをそれぞれ削除する:

削除対象1(`numpy_encoder`、31-34行目):
```python
def numpy_encoder(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return json.JSONEncoder().default(obj)
```

削除対象2(`focal_feature_loss`、43-46行目):
```python
def focal_feature_loss(distance, gamma=2.0):
    d_norm = distance / (distance.max().detach() + 1e-8)
    weights = d_norm ** gamma
    return torch.mean(weights * distance)
```

削除対象3(`GaussianNoise`、57-67行目):
```python
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
```

削除対象4(`get_st_transform`、98-113行目):
```python
def get_st_transform(cfg):
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
    if not tf_list:
        return None
    return transforms.Compose(tf_list)
```

削除対象5(`TrainTransform`、116-128行目):
```python
class TrainTransform:
    def __init__(self, pre_tf, default_tf, st_tf=None):
        self.pre_tf = pre_tf
        self.default_tf = default_tf
        self.st_tf = st_tf

    def __call__(self, image):
        if self.st_tf is not None:
            st_image = self.default_tf(self.st_tf(image))
        else:
            st_image = self.default_tf(image)
        ae_image = self.default_tf(self.pre_tf(image))
        return st_image, ae_image
```

削除対象6(`predict`・`map_normalization`・`teacher_normalization`、711-795行目):
```python
@torch.no_grad()
def predict(image, teacher, student, autoencoder, teacher_mean, teacher_std, st_para, ae_para,
            q_st_start=None, q_st_end=None, q_ae_start=None, q_ae_end=None,
            channel_weights=None):
    teacher_output = teacher(image)
    teacher_output = (teacher_output - teacher_mean) / teacher_std
    student_output = student(image)
    autoencoder_output = autoencoder(image)

    diff_st = (teacher_output - student_output[:, :out_channels]) ** 2
    if channel_weights is not None:
        map_st = torch.sum(diff_st * channel_weights, dim=1, keepdim=True)
    else:
        map_st = torch.mean(diff_st, dim=1, keepdim=True)

    map_ae = torch.mean((autoencoder_output - student_output[:, out_channels:]) ** 2,
                        dim=1, keepdim=True)
    if q_st_start is not None:
        map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
    if q_ae_start is not None:
        map_ae = 0.1 * (map_ae - q_ae_start) / (q_ae_end - q_ae_start)
    map_combined = st_para * map_st + ae_para * map_ae
    return map_combined, map_st, map_ae


@torch.no_grad()
def map_normalization(validation_loader, teacher, student, autoencoder,
                      teacher_mean, teacher_std, st_para, ae_para,
                      desc='Map normalization', channel_weights=None,
                      edge_mask_w=0):
    """validation set から anomaly map の quantile を集計する (monochro 専用)。

    edge_mask_w>0 のとき両端を除外して quantile を計算する (color 版も Phase H
    完成で対称適用済、cfg.color.edge_mask_w で制御)。
    """
    maps_st = []
    maps_ae = []
    # teacher が乗っている device を採用 (cuda:0 ハードコードを廃止)
    device = next(teacher.parameters()).device
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
```

- [ ] **Step 5: `training/train/__init__.py`を更新する**

`training/train/__init__.py`を以下に全文置換する:

```python
"""trainステージの公開API。

trainパッケージ外からは `train.train_color` / `train.train_monochro`
のみを使用すること。`train.common` / `train.color` / `train.monochro`
内の関数を外部から直接importしてはならない
（境界はtests/ci_gates/test_training_boundary.pyで検証）。
"""
from train.color import train_color
from train.monochro import train_monochro

__all__ = ["train_color", "train_monochro"]
```

- [ ] **Step 6: importとシンタックスが正しいことを確認する**

Run: `cd training && python -c "import train; print(train.train_color, train.train_monochro)"`
Expected: エラーなく2つの関数オブジェクトが表示される(ImportError/SyntaxErrorが出ないこと)

Run: `cd training && python -m py_compile train/color.py train/monochro.py train/common.py train/__init__.py`
Expected: エラーなく終了

- [ ] **Step 7: `training/pipline.py`を更新する**

`training/pipline.py:25-26`の以下の行:

```python
from train_func_monochro import train_monochro
from train_func_color import train_color
```

を以下に置換する:

```python
from train import train_color, train_monochro
```

呼び出し箇所(416行目`train_monochro(sub_cfg, mgr=mgr)`、419行目`train_color(sub_cfg, mgr=mgr)`)は変更不要(シグネチャ・呼び出し方は完全に同一のため)。

**重要（無関係WIPの分離）**: `git add`前に`git diff training/pipline.py`で、本Step7の変更（import 2行→1行の置換）のみが含まれ、本Seamと無関係な既存WIP（`_spawn_with_gpu_env`のspawn-context修正）が混入していないことを確認すること。Seam1〜4のTask3/Task2で行った「一時的にWIPを元に戻す→コミット→復元する」手順を同様に踏むこと。

- [ ] **Step 8: CI gateを新規作成する**

`training/tests/ci_gates/test_training_boundary.py`を新規作成する:

```python
"""trainステージの境界を守るCI gate。

train.common / train.color / train.monochro（学習ロジックの
低レベルモジュール）を直接importできるのはtrainパッケージ内のみで
あることを保証する。他のモジュールは train.train_color /
train.train_monochro の公開APIのみを使用すること。

走査対象は training/ 配下のみに限定する（app_ver2はEfficientADと異なり、
同一リポジトリに backend/ 等の無関係なPythonコードを含むため。設計書ADR-app4）。
"""
import ast
from pathlib import Path

TRAINING_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIR_NAMES = {"tests", "train", "__pycache__"}
INTERNAL_MODULES = {"train.common", "train.color", "train.monochro"}


def _imported_module_names(file_path):
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


def test_pipline_does_not_import_training_internals_directly():
    """pipline.py は train.common / train.color / train.monochro を
    直接importしてはいけない。学習処理は train の公開APIを経由すること。"""
    pipline_path = TRAINING_ROOT / "pipline.py"
    assert _imported_module_names(pipline_path).isdisjoint(INTERNAL_MODULES)


def test_only_training_module_imports_training_internals():
    """train.common / train.color / train.monochro を直接importして
    いるのは train パッケージ内のみであること（境界の逆行を防ぐラチェット）。"""
    offenders = []
    for py_file in TRAINING_ROOT.rglob("*.py"):
        rel_parts = py_file.relative_to(TRAINING_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if _imported_module_names(py_file) & INTERNAL_MODULES:
            offenders.append(str(py_file.relative_to(TRAINING_ROOT)))
    assert offenders == [], f"train外からのtrain内部モジュール直接importを検出: {offenders}"
```

- [ ] **Step 9: CI gateテストを実行する**

Run: `cd training && python -m pytest tests/ci_gates/test_training_boundary.py -v`
Expected: 2件ともPASS

- [ ] **Step 10: プロジェクト全体のテストを実行する**

Run: `cd training && python -m pytest tests/ -v`
Expected: 全件PASS(43件: Seam4完了時点で32件 + Task1で追加した9件(`tests/train/test_common.py`) = 41件 + Task2 Step9で追加した2件(CI gate) = 43件)

- [ ] **Step 11: コミット**

```bash
git add training/train/ training/pipline.py training/tests/ci_gates/test_training_boundary.py
git commit -m "$(cat <<'EOF'
refactor(training-train): train_func_color/monochroをtrain/color.py・train/monochro.pyへ移動し公開APIを整備

training/train_func_color.py・training/train_func_monochro.pyを
training/train/color.py・training/train/monochro.pyへgit mvし、
Task1で抽出した8関数はtrain.common経由のimportに置き換えた。
学習ループ本体(train_color/train_monochro)・monochro固有ロジックは
1文字も変更していない。training/pipline.pyのimportをtrain.train_color/
train_monochro経由にリダイレクト。CI gate(test_training_boundary.py)で
train内部モジュールへの境界逆行を防止する。
EOF
)"
```

`training/train_func_color.py`・`training/train_func_monochro.py`の削除は`git mv`(Step1・Step3)で既にステージ済みのため、上記コミットに含まれる。

---

## 完了条件（このSeamのDone）

- `train.train_color(cfg, mgr=None)`・`train.train_monochro(cfg, mgr=None)`が公開APIとして存在し、`training/pipline.py`はこれ経由でのみ学習を実行する
- 8つの低レベル関数が`train.common`に一本化され、`training/train_func_color.py`・`training/train_func_monochro.py`（削除済み・移動済み）にあった重複が解消されている
- 抽出前の関数本体を字句通り複製した参照実装との数値一致テストが全てPASSしている（挙動保存の証拠）
- 学習ループ本体(`train_color`/`train_monochro`)・monochro固有ロジック（raw_shift・normalize_mode・cand1較正等）・`evaluate_validation_loss`は1文字も変更されていない
- CI gate（`training/tests/ci_gates/test_training_boundary.py`）が導入され、`train`内部モジュールの境界逆行を検出できる
- `cd training && python -m pytest tests/ -v` が全件PASS（43件）
- `training/pipline.py`の無関係な既存WIP（spawn-context修正）が本Seamのコミットに混入していない
- 設計書（`docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md`）§8のSeam5が完了としてマークできる状態になっている
