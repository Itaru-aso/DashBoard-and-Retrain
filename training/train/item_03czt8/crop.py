"""03CZT8専用のcrop/上下分割ロジック。

既存の `utils/image_preprocessing.py` の `process_image()` とは意図的に分離した
新規実装であり、既存関数は一切変更しない
（`.kiro/specs/retraining/new-item-03czt8-model-creation.md` v3.0 決定3）。

crop_x0・crop_width・overlapはすべて呼び出し側が明示的に渡す必須パラメータであり、
デフォルト値を持たない。既存色番（05CZT8等）が使う `process_image()` の
crop式(485,1250,overlap=60) / (215,1675,overlap=60) とは完全に独立している。
"""
from __future__ import annotations

import cv2
import numpy as np


def crop_and_split(image_bgr: np.ndarray, crop_x0: int, crop_width: int, overlap: int,
                    mode: str) -> tuple[np.ndarray, np.ndarray]:
    """生画像(BGR)をcrop→上下分割する（リサイズは行わない）。

    Args:
        image_bgr: 生画像(BGR, numpy array)。
        crop_x0: クロップ開始x座標(colorはrotate後の座標系)。
        crop_width: クロップ幅。
        overlap: 上下分割の重なり幅(px)。
        mode: "monochro" または "color"。colorはcrop前に90度回転する。

    Returns:
        (top_half, bottom_half) のタプル(リサイズ前)。

    Raises:
        ValueError: mode不正、crop範囲が画像幅を超える、overlapが不正な場合。
    """
    if mode == "color":
        image_bgr = cv2.rotate(image_bgr, cv2.ROTATE_90_CLOCKWISE)
    elif mode != "monochro":
        raise ValueError(f"mode must be 'monochro' or 'color', got {mode!r}")

    img_h, img_w = image_bgr.shape[:2]
    if crop_x0 < 0 or crop_x0 + crop_width > img_w:
        raise ValueError(
            f"crop_x0={crop_x0} + crop_width={crop_width} が画像幅 {img_w} を超えています"
        )

    cropped = image_bgr[0:img_h, crop_x0:crop_x0 + crop_width]

    half_height = cropped.shape[0] // 2
    if overlap < 0 or overlap >= half_height:
        raise ValueError(
            f"overlap={overlap} は不正です(0 <= overlap < half_height={half_height})"
        )

    top_half = cropped[0:half_height + overlap, :]
    bottom_half = cropped[half_height - overlap:, :]
    return top_half, bottom_half
