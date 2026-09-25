"""03CZT8専用crop/分割関数のテスト。

`items/item_03czt8/crop.py` の `crop_and_split()` を対象とする。
既存の `utils/image_preprocessing.py` の `process_image()` は一切変更しない
（`.kiro/specs/retraining/new-item-03czt8-model-creation.md` v3.0 決定3）。
crop_x0/crop_width/overlapは03CZT8向けに実測済みの値
（monochro: x0=655,width=950,overlap=50 / color: x0=418,width=1280,overlap=50）を使う。

実行: cd training && python -m pytest tests/items/test_item_03czt8_crop.py -v
"""
import numpy as np
import pytest

from train.item_03czt8.crop import crop_and_split


def _make_gradient_image(width, height):
    """位置がわかる合成画像。img[y, x, 0]=x%256, img[y, x, 1]=y%256, img[y, x, 2]=0。"""
    xs = np.arange(width, dtype=np.uint8) % 256
    ys = np.arange(height, dtype=np.uint8) % 256
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :, 0] = xs[np.newaxis, :]
    img[:, :, 1] = ys[:, np.newaxis]
    return img


class TestCropAndSplitMonochro:
    """monochro: x0=655, width=950, overlap=50（raw高さ1220、half=610）。"""

    def test_top_bottom_shape(self):
        img = _make_gradient_image(width=2048, height=1220)
        top, bottom = crop_and_split(img, crop_x0=655, crop_width=950, overlap=50, mode="monochro")
        assert top.shape == (660, 950, 3)
        assert bottom.shape == (660, 950, 3)

    def test_horizontal_range_matches_crop_x0(self):
        img = _make_gradient_image(width=2048, height=1220)
        top, _ = crop_and_split(img, crop_x0=655, crop_width=950, overlap=50, mode="monochro")
        assert top[0, 0, 0] == 655 % 256
        assert top[0, -1, 0] == (655 + 950 - 1) % 256

    def test_top_starts_at_y0_bottom_ends_at_last_row(self):
        img = _make_gradient_image(width=2048, height=1220)
        top, bottom = crop_and_split(img, crop_x0=655, crop_width=950, overlap=50, mode="monochro")
        assert top[0, 0, 1] == 0
        assert bottom[-1, 0, 1] == 1219 % 256

    def test_overlap_widens_boundary(self):
        """half=610, overlap=50 → top行末=659行目、bottom行頭=560行目 (50行重複)。"""
        img = _make_gradient_image(width=2048, height=1220)
        top, bottom = crop_and_split(img, crop_x0=655, crop_width=950, overlap=50, mode="monochro")
        assert top[-1, 0, 1] == 659 % 256
        assert bottom[0, 0, 1] == 560 % 256


class TestCropAndSplitColor:
    """color: x0=418, width=1280, overlap=50。90度回転後(raw元2040x2432→回転後2432x2040)に適用。"""

    def test_top_bottom_shape(self):
        # 回転前の生画像: height=2040, width=2432 (03CZT8実測: rotated shape=(2432,2040,3))
        img = _make_gradient_image(width=2432, height=2040)
        top, bottom = crop_and_split(img, crop_x0=418, crop_width=1280, overlap=50, mode="color")
        assert top.shape == (1266, 1280, 3)
        assert bottom.shape == (1266, 1280, 3)


class TestCropAndSplitBoundaryChecks:
    def test_raises_when_crop_extends_beyond_width(self):
        img = _make_gradient_image(width=2048, height=1220)
        with pytest.raises(ValueError):
            crop_and_split(img, crop_x0=1200, crop_width=950, overlap=50, mode="monochro")

    def test_raises_when_overlap_negative(self):
        img = _make_gradient_image(width=2048, height=1220)
        with pytest.raises(ValueError):
            crop_and_split(img, crop_x0=655, crop_width=950, overlap=-1, mode="monochro")

    def test_raises_when_overlap_exceeds_half_height(self):
        img = _make_gradient_image(width=2048, height=1220)
        with pytest.raises(ValueError):
            crop_and_split(img, crop_x0=655, crop_width=950, overlap=610, mode="monochro")

    def test_raises_on_unknown_mode(self):
        img = _make_gradient_image(width=2048, height=1220)
        with pytest.raises(ValueError):
            crop_and_split(img, crop_x0=655, crop_width=950, overlap=50, mode="unknown")
