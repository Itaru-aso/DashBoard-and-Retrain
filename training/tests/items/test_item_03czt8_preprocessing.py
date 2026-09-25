"""03CZT8専用の画像前処理(crop+分割+リサイズ)関数のテスト。

`items/item_03czt8/preprocessing.py` の `process_image_item()` を対象とする。
既存の `utils/image_preprocessing.py` の `process_image()` は一切変更しない
（`.kiro/specs/retraining/new-item-03czt8-model-creation.md` v3.0 決定3）。

実行: cd training && python -m pytest tests/items/test_item_03czt8_preprocessing.py -v
"""
import cv2
import numpy as np
import pytest

from train.item_03czt8.preprocessing import process_image_item


def _make_gradient_bytes(width, height):
    xs = np.arange(width, dtype=np.uint8) % 256
    ys = np.arange(height, dtype=np.uint8) % 256
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :, 0] = xs[np.newaxis, :]
    img[:, :, 1] = ys[:, np.newaxis]
    ok, encoded = cv2.imencode(".bmp", img)
    assert ok
    return encoded.tobytes()


class TestProcessImageItemMonochro:
    def test_returns_resized_top_and_bottom(self):
        image_data = _make_gradient_bytes(width=2048, height=1220)
        top, bottom, elapsed = process_image_item(
            image_data, image_size_width=512, image_size_height=384, mode="monochro",
            crop_x0=655, crop_width=950, overlap=50,
        )
        assert top.shape == (384, 512, 3)
        assert bottom.shape == (384, 512, 3)
        assert elapsed >= 0

    def test_crop_offset_x_shifts_crop_position(self):
        """crop_offset_xはmonochro専用のランダムシフト(既存RawShiftImageFolderと同等機能)。"""
        image_data = _make_gradient_bytes(width=2048, height=1220)
        top_no_offset, _, _ = process_image_item(
            image_data, image_size_width=950, image_size_height=384, mode="monochro",
            crop_x0=655, crop_width=950, overlap=50, crop_offset_x=0,
        )
        top_with_offset, _, _ = process_image_item(
            image_data, image_size_width=950, image_size_height=384, mode="monochro",
            crop_x0=655, crop_width=950, overlap=50, crop_offset_x=10,
        )
        # crop_offset_x=10だけx方向にずれているため、リサイズなし(width=950=crop_width)の
        # 先頭列の値が10だけ異なるはず。
        assert int(top_no_offset[0, 0, 0]) != int(top_with_offset[0, 0, 0])
        assert int(top_with_offset[0, 0, 0]) == (655 + 10) % 256


class TestProcessImageItemColor:
    def test_returns_resized_top_and_bottom(self):
        image_data = _make_gradient_bytes(width=2432, height=2040)
        top, bottom, elapsed = process_image_item(
            image_data, image_size_width=384, image_size_height=384, mode="color",
            crop_x0=418, crop_width=1280, overlap=50,
        )
        assert top.shape == (384, 384, 3)
        assert bottom.shape == (384, 384, 3)

    def test_color_rejects_nonzero_crop_offset_x(self):
        """既存RawShiftImageFolderのガード(color+shift>0はエラー)と同等の制約。"""
        image_data = _make_gradient_bytes(width=2432, height=2040)
        with pytest.raises(ValueError):
            process_image_item(
                image_data, image_size_width=384, image_size_height=384, mode="color",
                crop_x0=418, crop_width=1280, overlap=50, crop_offset_x=5,
            )
