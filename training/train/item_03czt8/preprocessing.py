"""03CZT8専用の画像前処理(crop→上下分割→リサイズ)。

既存の `utils/image_preprocessing.py` の `process_image()` とは意図的に分離した
新規実装であり、既存関数は一切変更しない
（`.kiro/specs/retraining/new-item-03czt8-model-creation.md` v3.0 決定3）。

保守負債に関する注記: 本モジュールは `process_image()` とcrop→分割→リサイズという
ロジックが重複する。`process_image()` に不具合修正・仕様変更が入る場合は、
本モジュールへの影響有無を確認すること（同ADR「リスク」節参照）。
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from train.item_03czt8.crop import crop_and_split


def process_image_item(
    image_data: bytes,
    image_size_width: int,
    image_size_height: int,
    mode: str,
    crop_x0: int,
    crop_width: int,
    overlap: int,
    crop_offset_x: int = 0,
) -> tuple[np.ndarray, np.ndarray, float]:
    """画像バイト列をcrop→上下分割→リサイズする。

    Args:
        image_data: 画像データのバイト配列。
        image_size_width/image_size_height: リサイズ後のサイズ。
        mode: "monochro" または "color"。
        crop_x0/crop_width/overlap: 03CZT8向けの実測済みクロップパラメータ(必須)。
        crop_offset_x: crop開始x座標のオフセット(monochro専用、学習時のシフト
            augmentation用)。colorで非ゼロを指定するとエラーになる
            (既存RawShiftImageFolderの制約と同等)。

    Returns:
        (resized_top_half, resized_bottom_half, elapsed_time)。

    Raises:
        ValueError: colorでcrop_offset_x != 0が指定された場合。
    """
    if mode == "color" and crop_offset_x != 0:
        raise ValueError("crop_offset_x はmonochro専用です。colorでは0を指定してください。")

    read_img = cv2.imdecode(np.frombuffer(image_data, np.uint8), cv2.IMREAD_COLOR)
    top_half, bottom_half = crop_and_split(
        read_img, crop_x0=crop_x0 + crop_offset_x, crop_width=crop_width,
        overlap=overlap, mode=mode,
    )

    new_size = (image_size_width, image_size_height)
    start_time = time.time()
    resized_top_half = cv2.resize(top_half, new_size, interpolation=cv2.INTER_AREA)
    elapsed_time = time.time() - start_time
    resized_bottom_half = cv2.resize(bottom_half, new_size, interpolation=cv2.INTER_AREA)

    return resized_top_half, resized_bottom_half, elapsed_time
