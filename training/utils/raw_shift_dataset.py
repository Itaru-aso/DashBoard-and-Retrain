"""raw 画像から毎回 random crop offset で前処理する Dataset。

学習時のシフト不変性獲得のため、raw 画像 (1220x2048 等) を直接読み、
process_image() を crop_offset_x=random で呼ぶことで、推論時のクロップ位置
ずれに対するロバスト性を学習する。

推論時は ONNX が 256x512 入力を受け取り、C# 側で crop_offset_x=0 で前処理
される (= 学習時の中央クロップに相当)。学習時にだけ ±crop_shift_max_px の
範囲でランダムにずらすことで、推論時に raw 撮像系が ±N pixel ずれても
特徴量レスポンスが大きく変動しないように学習する。
"""
from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset

from utils.image_preprocessing import load_image_as_byte_array, process_image


IMAGE_EXTS = (".bmp", ".png", ".jpg", ".jpeg", ".tiff")


def _list_raw_images(root: str) -> list[Path]:
    """root 配下を再帰的に走査して画像ファイルパスを返す (ソート済)。"""
    p = Path(root)
    if not p.exists():
        return []
    files = []
    for dirpath, _, filenames in os.walk(p):
        for fn in filenames:
            if fn.lower().endswith(IMAGE_EXTS):
                files.append(Path(dirpath) / fn)
    return sorted(files)


class RawShiftImageFolder(Dataset):
    """raw 画像から random crop offset で前処理する PyTorch Dataset。

    各 raw 画像から top/bottom の 2 枚を生成するため、__len__ は画像数の 2 倍。
    __getitem__ ごとに crop_offset_x を `uniform(-crop_shift_max_px, +crop_shift_max_px)`
    で再抽選するため、同じ idx を 2 回引いても異なる augmented 画像が返る。

    Args:
        raw_root: raw 画像のルートディレクトリ (再帰探索)。
        mode: "monochro" or "color" (process_image に渡す)。
        image_size_width: process_image のリサイズ後 width (= ONNX 入力幅)。
        image_size_height: process_image のリサイズ後 height (= ONNX 入力高)。
        crop_shift_max_px: シフト範囲。0 なら固定 (= 従来挙動)。
        transform: PIL.Image を受けて Tensor を返す torchvision Compose 等。
            None なら numpy ndarray (RGB) のまま返す。
        seed: 再現性が必要なテスト用。None なら毎回独立。
        sample_mode: "both" (top/bottom 両方扱い、__len__ = 2N)、
            "top_only" / "bottom_only" (__len__ = N)。デフォルト "both"。

    Note:
        - validation/quantile 計算では augment しない方が望ましいため、
          別途 crop_shift_max_px=0 のインスタンスを作る or 既存の
          ImageFolderWithoutTarget を併用する。
        - top/bottom は同じ raw 画像から派生するため、shuffle=True の
          DataLoader を使うこと推奨。
    """

    def __init__(
        self,
        raw_root: str,
        mode: str,
        image_size_width: int,
        image_size_height: int,
        crop_shift_max_px: int = 0,
        transform: Optional[Callable] = None,
        seed: Optional[int] = None,
        sample_mode: str = "both",
    ) -> None:
        if mode not in ("monochro", "color"):
            raise ValueError(f"mode must be 'monochro' or 'color', got {mode!r}")
        if sample_mode not in ("both", "top_only", "bottom_only"):
            raise ValueError(f"sample_mode invalid: {sample_mode!r}")
        # crop_offset_x は monochro 専用設計 (color は撮像分布が安定しているため不要)。
        # 誤用防止のため color + crop_shift_max_px > 0 は拒否する。
        if mode == "color" and int(crop_shift_max_px) > 0:
            raise ValueError(
                "crop_shift_max_px は monochro 専用です。color では 0 を指定するか "
                "本クラスを使わず ImageFolderWithoutTarget を使用してください。"
            )
        self.raw_root = raw_root
        self.mode = mode
        self.W = int(image_size_width)
        self.H = int(image_size_height)
        self.shift_max = max(0, int(crop_shift_max_px))
        self.transform = transform
        self.sample_mode = sample_mode

        self.paths: list[Path] = _list_raw_images(raw_root)
        if not self.paths:
            raise FileNotFoundError(
                f"raw 画像が見つかりません: {raw_root} (再帰探索)"
            )

        self._rng = random.Random(seed) if seed is not None else random

    def __len__(self) -> int:
        if self.sample_mode == "both":
            return len(self.paths) * 2
        return len(self.paths)

    def _sample_offset(self) -> int:
        if self.shift_max <= 0:
            return 0
        return self._rng.randint(-self.shift_max, +self.shift_max)

    def __getitem__(self, idx: int):
        if self.sample_mode == "both":
            path = self.paths[idx // 2]
            half = idx % 2  # 0=top, 1=bottom
        elif self.sample_mode == "top_only":
            path = self.paths[idx]
            half = 0
        else:  # bottom_only
            path = self.paths[idx]
            half = 1

        raw_bytes = load_image_as_byte_array(str(path))
        offset = self._sample_offset()
        top, bottom, _ = process_image(
            raw_bytes, self.W, self.H, self.mode, crop_offset_x=offset
        )
        img_bgr = top if half == 0 else bottom

        # transform を適用するため PIL に変換 (torchvision の慣例に従う)
        # numpy BGR → RGB → PIL
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(img_rgb)
        if self.transform is not None:
            return self.transform(pil)
        return pil


class _CallableTransformAdapter:
    """既存の TrainTransform (st_image, ae_image を返す) を Dataset に通すアダプタ。

    TrainTransform.__call__(pil) → (st_tensor, ae_tensor) を返すので
    そのまま使える。本クラスは未使用だが将来拡張用に残す。
    """

    def __init__(self, fn: Callable) -> None:
        self.fn = fn

    def __call__(self, pil):
        return self.fn(pil)
