"""03CZT8専用のmonochro margin用Datasetクラスのテスト。

`items/item_03czt8/margin_dataset.py` の `Item03CZT8RawShiftImageFolder` を対象とする。
既存の `utils/raw_shift_dataset.py` の `RawShiftImageFolder` は一切変更しない
（`.kiro/specs/retraining/new-item-03czt8-model-creation.md` v3.0 決定3）。

実行: cd training && python -m pytest tests/items/test_item_03czt8_margin_dataset.py -v
"""
import cv2
import numpy as np
import pytest
from PIL import Image

from train.item_03czt8.margin_dataset import Item03CZT8RawShiftImageFolder


def _write_gradient_image(path, width=2048, height=1220):
    xs = np.arange(width, dtype=np.uint8) % 256
    ys = np.arange(height, dtype=np.uint8) % 256
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :, 0] = xs[np.newaxis, :]
    img[:, :, 1] = ys[:, np.newaxis]
    cv2.imwrite(str(path), img)


class TestItem03CZT8RawShiftImageFolderMonochro:
    def test_len_is_double_when_sample_mode_both(self, tmp_path):
        for i in range(3):
            _write_gradient_image(tmp_path / f"raw_{i}.bmp")
        ds = Item03CZT8RawShiftImageFolder(
            raw_root=str(tmp_path), mode="monochro",
            image_size_width=512, image_size_height=384,
            crop_x0=655, crop_width=950, overlap=50,
        )
        assert len(ds) == 6

    def test_getitem_returns_pil_image_with_expected_size(self, tmp_path):
        _write_gradient_image(tmp_path / "raw_0.bmp")
        ds = Item03CZT8RawShiftImageFolder(
            raw_root=str(tmp_path), mode="monochro",
            image_size_width=512, image_size_height=384,
            crop_x0=655, crop_width=950, overlap=50,
        )
        img = ds[0]
        assert isinstance(img, Image.Image)
        assert img.size == (512, 384)

    def test_seed_makes_shift_reproducible(self, tmp_path):
        _write_gradient_image(tmp_path / "raw_0.bmp")
        ds1 = Item03CZT8RawShiftImageFolder(
            raw_root=str(tmp_path), mode="monochro",
            image_size_width=950, image_size_height=384,
            crop_x0=655, crop_width=950, overlap=50,
            crop_shift_max_px=20, seed=42,
        )
        ds2 = Item03CZT8RawShiftImageFolder(
            raw_root=str(tmp_path), mode="monochro",
            image_size_width=950, image_size_height=384,
            crop_x0=655, crop_width=950, overlap=50,
            crop_shift_max_px=20, seed=42,
        )
        img1 = np.array(ds1[0])
        img2 = np.array(ds2[0])
        assert np.array_equal(img1, img2)

    def test_no_shift_when_crop_shift_max_px_zero(self, tmp_path):
        _write_gradient_image(tmp_path / "raw_0.bmp")
        ds = Item03CZT8RawShiftImageFolder(
            raw_root=str(tmp_path), mode="monochro",
            image_size_width=950, image_size_height=384,
            crop_x0=655, crop_width=950, overlap=50,
            crop_shift_max_px=0,
        )
        assert ds._sample_offset() == 0


class TestItem03CZT8RawShiftImageFolderColorGuard:
    def test_color_rejects_positive_crop_shift_max_px(self, tmp_path):
        _write_gradient_image(tmp_path / "raw_0.bmp", width=2432, height=2040)
        with pytest.raises(ValueError):
            Item03CZT8RawShiftImageFolder(
                raw_root=str(tmp_path), mode="color",
                image_size_width=384, image_size_height=384,
                crop_x0=418, crop_width=1280, overlap=50,
                crop_shift_max_px=20,
            )


class TestItem03CZT8RawShiftImageFolderEmptyRoot:
    def test_raises_when_no_images_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Item03CZT8RawShiftImageFolder(
                raw_root=str(tmp_path), mode="monochro",
                image_size_width=512, image_size_height=384,
                crop_x0=655, crop_width=950, overlap=50,
            )
