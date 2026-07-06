"""edge mask ユーティリティ

撮像系の境界アーティファクト (画像両端のフリンジ等) を loss/quantile/score
計算から除外するためのヘルパー。学習時 (train_func_monochro.py) と推論時
(evaluation_pipeline.py / eval_edge_mask_sweep.py) で共通利用する。

設計指針:
- マスクは tensor の最後の次元 (W) 両端 ``edge_mask_w`` 列を対象とする。
- ``edge_mask_w <= 0`` では入力をそのまま返す (no-op、後方互換)。
- マスク後の loss は「両端を除いた中央領域だけ」で計算したいので、
  値を 0 で上書きするより slice の方が安全 (mean / quantile を歪めない)。
"""
from typing import Optional

import torch
from torch import Tensor


def slice_edge_excluded(tensor: Tensor, edge_mask_w: int) -> Tensor:
    """tensor の最後の次元 (W) から両端 edge_mask_w 列を切り捨てた view を返す。

    mean/quantile 計算では 0 で塗りつぶすより slice の方が正確 (両端を
    「存在しないもの」として扱える)。

    Args:
        tensor: 任意 shape の tensor (最後の次元が W)。
        edge_mask_w: 両端から切り捨てる列数。0 以下なら入力をそのまま返す。

    Returns:
        中央 ``W - 2*edge_mask_w`` 列の view。
    """
    if edge_mask_w <= 0:
        return tensor
    W = tensor.shape[-1]
    if edge_mask_w * 2 >= W:
        raise ValueError(
            f'edge_mask_w={edge_mask_w} は tensor 幅 W={W} に対し過大'
        )
    return tensor[..., edge_mask_w:W - edge_mask_w]


def apply_edge_mask_zero(tensor: Tensor, edge_mask_w: int) -> Tensor:
    """tensor の両端 edge_mask_w 列を 0 で上書きしたコピーを返す。

    主に推論時 score 計算 (max を取る用途) で使用。元の shape を保ちたい
    場合に slice_edge_excluded ではなくこちらを使う。

    Args:
        tensor: 任意 shape の tensor。
        edge_mask_w: 両端 0 化する列数。0 以下なら入力をそのまま返す。

    Returns:
        両端 0 化された clone。
    """
    if edge_mask_w <= 0:
        return tensor
    W = tensor.shape[-1]
    if edge_mask_w * 2 >= W:
        raise ValueError(
            f'edge_mask_w={edge_mask_w} は tensor 幅 W={W} に対し過大'
        )
    out = tensor.clone()
    out[..., :edge_mask_w] = 0.0
    out[..., -edge_mask_w:] = 0.0
    return out


def masked_quantile(tensor: Tensor, q: float, edge_mask_w: int = 0) -> Tensor:
    """両端を除外した上で quantile を計算する。

    Args:
        tensor: 任意 shape (最後の次元が W)。
        q: quantile (0〜1)。
        edge_mask_w: 両端から切り捨てる列数。

    Returns:
        scalar tensor。
    """
    sliced = slice_edge_excluded(tensor, edge_mask_w)
    flat = sliced.flatten()
    return torch.quantile(flat, q=q)


def masked_max(tensor: Tensor, edge_mask_w: int = 0) -> float:
    """両端を除外した上で max を取り float で返す。"""
    sliced = slice_edge_excluded(tensor, edge_mask_w)
    return float(sliced.max().item())
