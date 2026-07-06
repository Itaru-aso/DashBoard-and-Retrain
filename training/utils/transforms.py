"""共通画像 transform (前処理) ユーティリティ

PerImageMinMax: 画像ごとに [0, 1] にスケーリング (min-max 正規化)。
PerImageMeanStd: 画像ごとに z-score 標準化 → 目標 mean/std に再スケール。
build_default_transform: normalize_mode で 3 通り (none / min_max / mean_std) 切り替え。

撮像時の照明変動に対するロバスト性を狙う。learning と inference で同じモードを使うこと。
"""
import torch
from torch import Tensor


# ImageNet 事前学習で使われた標準統計 (PyTorch / torchvision 慣例)
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class PerImageMinMax:
    """画像ごとに [0, 1] にスケーリングする変換 (pickle 可能)。

    入力:
        Tensor [C, H, W]: 単一画像 (ToTensor 直後の形、0〜1 範囲)
    出力:
        Tensor [C, H, W]: 全 element の min/max で線形スケーリング後の値

    全 element 共通の min/max を使うため、チャネル間の相対的な明暗差は保持される。
    """

    def __call__(self, tensor: Tensor) -> Tensor:
        if not torch.is_tensor(tensor):
            raise TypeError(f'PerImageMinMax expects Tensor, got {type(tensor)}')
        mn = tensor.amin()
        mx = tensor.amax()
        denom = (mx - mn).clamp(min=1e-9)
        return (tensor - mn) / denom

    def __repr__(self) -> str:
        return self.__class__.__name__ + '()'


class PerImageMeanStd:
    """画像ごとに z-score 標準化し、目標 mean/std に再スケールする変換。

    式: (x - x.mean()) / x.std() * target_std + target_mean

    入力:
        Tensor [C, H, W] (ToTensor 直後の 0〜1 範囲)
    出力:
        Tensor [C, H, W] (画像ごとに mean=target_mean, std=target_std に揃う)

    Args:
        target_mean: スカラー (全チャネル共通) or list [C] (チャネル別)。
            デフォルト ImageNet mean。
        target_std: 同様。デフォルト ImageNet std。

    用途:
        ToTensor → PerImageMeanStd → (ImageNet Normalize は不要、目標で直接揃える)
        撮像時の照明変動 / コントラスト差を画像ごとに吸収。
    """

    def __init__(self, target_mean=None, target_std=None):
        target_mean = IMAGENET_MEAN if target_mean is None else target_mean
        target_std = IMAGENET_STD if target_std is None else target_std
        # スカラー or リスト
        if isinstance(target_mean, (int, float)):
            self._tm = torch.tensor(float(target_mean))
            self._mode_per_channel = False
        else:
            self._tm = torch.tensor(list(target_mean), dtype=torch.float32).view(-1, 1, 1)
            self._mode_per_channel = True
        if isinstance(target_std, (int, float)):
            self._ts = torch.tensor(float(target_std))
            assert not self._mode_per_channel  # 整合性
        else:
            self._ts = torch.tensor(list(target_std), dtype=torch.float32).view(-1, 1, 1)
            assert self._mode_per_channel

    def __call__(self, tensor: Tensor) -> Tensor:
        if not torch.is_tensor(tensor):
            raise TypeError(f'PerImageMeanStd expects Tensor, got {type(tensor)}')
        # 全 element の mean / std (チャネル間相対関係を保つ)
        mean = tensor.mean()
        std = tensor.std().clamp(min=1e-9)
        normalized = (tensor - mean) / std
        tm = self._tm.to(device=tensor.device, dtype=tensor.dtype)
        ts = self._ts.to(device=tensor.device, dtype=tensor.dtype)
        return normalized * ts + tm

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(target_mean={self._tm.tolist()}, target_std={self._ts.tolist()})'


def build_default_transform(normalize_mode: str = 'none',
                             target_mean=None, target_std=None):
    """normalize_mode に応じた標準 transform を返す。

    Args:
        normalize_mode:
            'none'    → ToTensor → ImageNet Normalize (既存挙動)
            'min_max' → ToTensor → PerImageMinMax → ImageNet Normalize
            'mean_std'→ ToTensor → PerImageMeanStd(target_mean, target_std)
                        (ImageNet Normalize は適用しない、目標統計で直接揃える)
        target_mean / target_std: mean_std モードでの目標統計。
            None なら ImageNet 統計を使用。

    Returns:
        torchvision.transforms.Compose
    """
    from torchvision import transforms
    tf_list = [transforms.ToTensor()]
    if normalize_mode == 'none':
        tf_list.append(transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD))
    elif normalize_mode == 'min_max':
        tf_list.append(PerImageMinMax())
        tf_list.append(transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD))
    elif normalize_mode == 'mean_std':
        tf_list.append(PerImageMeanStd(target_mean=target_mean, target_std=target_std))
    else:
        raise ValueError(
            f"unknown normalize_mode={normalize_mode!r} "
            "(expected 'none' | 'min_max' | 'mean_std')")
    return transforms.Compose(tf_list)


def resolve_normalize_mode(para: dict) -> str:
    """para.json (または equivalent dict) から normalize_mode を解決する。

    優先順位:
        1. ``para['normalize_mode']`` (新形式)
        2. ``para['per_image_minmax']`` が True なら 'min_max'、False/欠損なら 'none' (旧形式互換)
    """
    if 'normalize_mode' in para and para['normalize_mode']:
        return str(para['normalize_mode'])
    if para.get('per_image_minmax', False):
        return 'min_max'
    return 'none'
