"""monochro.py の export_root/export_root_margin 対応 DataLoader構築のテスト。

dataset-export-root-migration.md v1.4 決定15〜19 に対応。検証基準6・7を確認する。
train.monochro.RawShiftImageFolder 呼び出し方式・DataLoader構築部分のみが対象
（決定20の例外範囲）。process_image/RawShiftImageFolderのcrop式自体は変更していない
（決定18）ため、本テストでは raw margin 画像の crop 座標系までは検証しない。

実行: cd training && python -m pytest tests/train/test_monochro_export_root_margin.py -v
"""
import json
import os

import cv2
import numpy as np
import pytest
from omegaconf import OmegaConf

from train.monochro import _build_datasets, _resolve_margin_good_root


def _write_fake_image(path, shape=(200, 1740, 3)):
    """monochro crop (485+offset, 0, 1250, H) が成立する幅 (>=1735) を既定にする。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = np.zeros(shape, dtype=np.uint8)
    cv2.imwrite(str(path), img)


def _write_margin_metadata(margin_root, dataset_id, categories):
    ds_dir = os.path.join(margin_root, dataset_id)
    os.makedirs(ds_dir, exist_ok=True)
    with open(os.path.join(ds_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"id": dataset_id, "name": "monochro_5_YY", "category": categories}, f)


def _cfg(margin_export_root="", dataset_id_monochro_margin=""):
    return OmegaConf.create({
        "margin_export_root": margin_export_root,
        "dataset_id_monochro_margin": dataset_id_monochro_margin,
    })


class TestResolveMarginGoodRoot:
    def test_returns_none_when_margin_export_root_unset(self):
        cfg = _cfg(margin_export_root="", dataset_id_monochro_margin="ds-1")
        assert _resolve_margin_good_root(cfg, "001") is None

    def test_returns_none_when_dataset_id_unset(self, tmp_path):
        cfg = _cfg(margin_export_root=str(tmp_path), dataset_id_monochro_margin="")
        assert _resolve_margin_good_root(cfg, "001") is None

    def test_returns_none_when_dataset_id_folder_missing(self, tmp_path):
        cfg = _cfg(margin_export_root=str(tmp_path), dataset_id_monochro_margin="no-such-id")
        assert _resolve_margin_good_root(cfg, "001") is None

    def test_finds_good_category_excludes_defect_and_invalid(self, tmp_path):
        margin_root = str(tmp_path / "export_root_margin")
        _write_margin_metadata(margin_root, "ds-1", categories=[
            {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
            {"category_id": "cat-defect", "on_class": "1", "invalid_flg": "0"},
            {"category_id": "cat-invalid-good", "on_class": "0", "invalid_flg": "1"},
        ])
        for cid in ("cat-good", "cat-defect", "cat-invalid-good"):
            _write_fake_image(os.path.join(margin_root, "ds-1", "binary", "001", cid, "raw_1.bmp"))

        cfg = _cfg(margin_export_root=margin_root, dataset_id_monochro_margin="ds-1")
        resolved = _resolve_margin_good_root(cfg, "001")

        assert resolved == os.path.join(margin_root, "ds-1", "binary", "001", "cat-good")

    def test_raises_when_multiple_good_categories_found(self, tmp_path):
        margin_root = str(tmp_path / "export_root_margin")
        _write_margin_metadata(margin_root, "ds-1", categories=[
            {"category_id": "cat-good-1", "on_class": "0", "invalid_flg": "0"},
            {"category_id": "cat-good-2", "on_class": "0", "invalid_flg": "0"},
        ])
        for cid in ("cat-good-1", "cat-good-2"):
            _write_fake_image(os.path.join(margin_root, "ds-1", "binary", "001", cid, "raw_1.bmp"))

        cfg = _cfg(margin_export_root=margin_root, dataset_id_monochro_margin="ds-1")
        with pytest.raises(ValueError, match="複数"):
            _resolve_margin_good_root(cfg, "001")


class TestBuildDatasetsRawShift:
    """検証基準6・7: use_raw_shift=True 時の train/val Dataset合体。"""

    def _make_dataset_path(
        self, tmp_path, n_train_good=3, n_test_good=2, n_train_defect=0, n_test_defect=0
    ):
        dataset_path = str(tmp_path / "4_dataset" / "001" / "monochro")
        for i in range(n_train_good):
            _write_fake_image(os.path.join(dataset_path, "train", "good", f"g{i}.png"), shape=(16, 16, 3))
        for i in range(n_train_defect):
            _write_fake_image(os.path.join(dataset_path, "train", "defect", f"d{i}.png"), shape=(16, 16, 3))
        for i in range(n_test_good):
            _write_fake_image(
                os.path.join(dataset_path, "test", "good", "images", f"g{i}.png"), shape=(16, 16, 3))
        for i in range(n_test_defect):
            _write_fake_image(
                os.path.join(dataset_path, "test", "defect", "images", f"d{i}.png"), shape=(16, 16, 3))
        return dataset_path

    def test_uses_export_root_only_when_margin_not_found(self, tmp_path):
        dataset_path = self._make_dataset_path(
            tmp_path, n_train_good=3, n_test_good=2, n_train_defect=5, n_test_defect=4)
        cfg = _cfg()  # margin_export_root/dataset_id_monochro_margin 未設定

        train_set, validation_set, full_train_set = _build_datasets(
            cfg, dataset_path, "001", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
        )

        # defectは一切含まれない（train/good=3件のみ、defectの5件は含まれない）。
        assert len(train_set) == 3
        assert len(validation_set) == 2
        assert len(full_train_set) == len(train_set)

    def test_merges_margin_and_tight_when_margin_found(self, tmp_path):
        dataset_path = self._make_dataset_path(tmp_path, n_train_good=3, n_test_good=2)
        margin_root = str(tmp_path / "export_root_margin")
        _write_margin_metadata(margin_root, "ds-margin-1", categories=[
            {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
            {"category_id": "cat-defect", "on_class": "1", "invalid_flg": "0"},
        ])
        # good: raw画像2枚 (RawShiftImageFolderはsample_mode="both"既定でtop/bottom2枚/raw画像 = 4件)
        for i in range(2):
            _write_fake_image(
                os.path.join(margin_root, "ds-margin-1", "binary", "001", "cat-good", f"raw_{i}.bmp"))
        # defect: margin側にも紛れ込ませて、混入しないことを確認する
        _write_fake_image(
            os.path.join(margin_root, "ds-margin-1", "binary", "001", "cat-defect", "raw_d.bmp"))
        cfg = _cfg(margin_export_root=margin_root, dataset_id_monochro_margin="ds-margin-1")

        train_set, validation_set, full_train_set = _build_datasets(
            cfg, dataset_path, "001", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
        )

        # マージン(2枚→top/bottom4件) + tight train(3件) = 7件。defectは含まれない。
        assert len(train_set) == 7
        # validationはexport_root(マージンなし)のtest/goodのみ（マージン混入なし）。
        assert len(validation_set) == 2
        assert len(full_train_set) == len(train_set)
        # crop_shift_max_pxがRawShiftImageFolderまで正しく配線されていること。
        margin_dataset = train_set.datasets[0]
        assert margin_dataset.shift_max == 20

    def test_validation_set_excludes_margin_data(self, tmp_path):
        """val/testはexport_root（マージンなし・good）のtest分のみで構成され、
        マージンデータを含まないこと（検証基準7）。"""
        dataset_path = self._make_dataset_path(tmp_path, n_train_good=1, n_test_good=1)
        margin_root = str(tmp_path / "export_root_margin")
        _write_margin_metadata(margin_root, "ds-margin-1", categories=[
            {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
        ])
        for i in range(5):
            _write_fake_image(
                os.path.join(margin_root, "ds-margin-1", "binary", "001", "cat-good", f"raw_{i}.bmp"))
        cfg = _cfg(margin_export_root=margin_root, dataset_id_monochro_margin="ds-margin-1")

        _, validation_set, _ = _build_datasets(
            cfg, dataset_path, "001", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
        )

        # マージン側は5枚(raw)→10件相当だが、validation_setは常にtight test/goodのみ=1件。
        assert len(validation_set) == 1


class TestBuildDatasetsLegacySplit:
    """use_raw_shift=False（既存動作）の回帰確認。"""

    def test_random_split_ratio_unchanged(self, tmp_path):
        from utils.common import ImageFolderWithoutTarget

        dataset_path = str(tmp_path / "4_dataset" / "001" / "monochro")
        for i in range(10):
            _write_fake_image(os.path.join(dataset_path, "train", "good", f"g{i}.png"), shape=(16, 16, 3))
        cfg = _cfg()

        train_set, validation_set, full_train_set = _build_datasets(
            cfg, dataset_path, "001", train_tf=None,
            use_raw_shift=False, crop_shift_max_px=0,
            image_size_width=16, image_size_height=16, seed=42,
        )

        assert isinstance(full_train_set, ImageFolderWithoutTarget)
        assert len(full_train_set) == 10
        assert len(train_set) == 8
        assert len(validation_set) == 2
