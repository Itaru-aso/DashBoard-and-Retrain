"""03CZT8専用: raw画像から毎回random crop offsetで前処理するDataset。

既存の `utils/raw_shift_dataset.py` の `RawShiftImageFolder` とは意図的に分離した
新規実装であり、既存クラスは一切変更しない
（`.kiro/specs/retraining/new-item-03czt8-model-creation.md` v3.0 決定3）。
既存クラスとの違いは、crop_x0/crop_width/overlapを03CZT8向けの値として
明示的に受け取る点のみで、ランダムシフトの仕組み自体は既存クラスと同等。

保守負債に関する注記: `RawShiftImageFolder` と設計・ロジックが重複する。
既存クラスに不具合修正・仕様変更が入る場合は、本クラスへの影響有無を確認すること
（同ADR「リスク」節参照）。
"""
from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Callable, Optional

import cv2
from PIL import Image
from torch.utils.data import Dataset

from train.item_03czt8.preprocessing import process_image_item
from utils.image_preprocessing import load_image_as_byte_array

IMAGE_EXTS = (".bmp", ".png", ".jpg", ".jpeg", ".tiff")


def _list_raw_images(root: str) -> list[Path]:
    p = Path(root)
    if not p.exists():
        return []
    files = []
    for dirpath, _, filenames in os.walk(p):
        for fn in filenames:
            if fn.lower().endswith(IMAGE_EXTS):
                files.append(Path(dirpath) / fn)
    return sorted(files)


class Item03CZT8RawShiftImageFolder(Dataset):
    """03CZT8向け: raw画像からrandom crop offsetで前処理するPyTorch Dataset。

    Args:
        raw_root: raw画像のルートディレクトリ(再帰探索)。
        mode: "monochro" or "color"。
        image_size_width/image_size_height: process_image_itemのリサイズ後サイズ。
        crop_x0/crop_width/overlap: 03CZT8向けの実測済みクロップパラメータ(必須)。
        crop_shift_max_px: シフト範囲。0なら固定(既存RawShiftImageFolderと同じ既定挙動)。
        transform: PIL.Imageを受けてTensorを返すtorchvision Compose等。
        seed: 再現性が必要なテスト用。Noneなら毎回独立。
        sample_mode: "both"(top/bottom両方、__len__=2N)、"top_only"/"bottom_only"(__len__=N)。
    """

    def __init__(
        self,
        raw_root: str,
        mode: str,
        image_size_width: int,
        image_size_height: int,
        crop_x0: int,
        crop_width: int,
        overlap: int,
        crop_shift_max_px: int = 0,
        transform: Optional[Callable] = None,
        seed: Optional[int] = None,
        sample_mode: str = "both",
    ) -> None:
        if mode not in ("monochro", "color"):
            raise ValueError(f"mode must be 'monochro' or 'color', got {mode!r}")
        if sample_mode not in ("both", "top_only", "bottom_only"):
            raise ValueError(f"sample_mode invalid: {sample_mode!r}")
        if mode == "color" and int(crop_shift_max_px) > 0:
            raise ValueError(
                "crop_shift_max_px はmonochro専用です。colorでは0を指定するか"
                "本クラスを使わないでください。"
            )
        self.raw_root = raw_root
        self.mode = mode
        self.W = int(image_size_width)
        self.H = int(image_size_height)
        self.crop_x0 = int(crop_x0)
        self.crop_width = int(crop_width)
        self.overlap = int(overlap)
        self.shift_max = max(0, int(crop_shift_max_px))
        self.transform = transform
        self.sample_mode = sample_mode

        self.paths: list[Path] = _list_raw_images(raw_root)
        if not self.paths:
            raise FileNotFoundError(f"raw画像が見つかりません: {raw_root} (再帰探索)")

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
            half = idx % 2
        elif self.sample_mode == "top_only":
            path = self.paths[idx]
            half = 0
        else:
            path = self.paths[idx]
            half = 1

        raw_bytes = load_image_as_byte_array(str(path))
        offset = self._sample_offset()
        top, bottom, _ = process_image_item(
            raw_bytes, self.W, self.H, self.mode,
            crop_x0=self.crop_x0, crop_width=self.crop_width, overlap=self.overlap,
            crop_offset_x=offset,
        )
        img_bgr = top if half == 0 else bottom

        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(img_rgb)
        if self.transform is not None:
            return self.transform(pil)
        return pil
