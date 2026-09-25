"""03CZT8専用train_monochro.pyの特性化テスト。

`items/item_03czt8/train_monochro.py` の `_build_datasets()` が、コピー元
(`train/monochro.py`の`_build_datasets()`)と同じDataLoader構築ロジックを保ちつつ、
`Item03CZT8RawShiftImageFolder`（既存`RawShiftImageFolder`ではない）を使うことを
特性化テストで確認する。verbatimコピーのためRED→GREENではなく回帰確認として書く
（`.kiro/specs/retraining/new-item-03czt8-model-creation.md` v3.0 決定10）。

実行: cd training && python -m pytest tests/items/test_item_03czt8_train_monochro.py -v
"""
import json
import os

import cv2
import numpy as np
import pytest
from omegaconf import OmegaConf

from train.item_03czt8.margin_dataset import Item03CZT8RawShiftImageFolder
from train.item_03czt8.train_monochro import CROP_WIDTH, CROP_X0, OVERLAP, _build_datasets


def _write_fake_image(path, shape=(200, 1740, 3)):
    """03CZT8 crop (655, 950, overlap=50) が成立する幅(>=1605)を既定にする。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = np.zeros(shape, dtype=np.uint8)
    cv2.imwrite(str(path), img)


def _write_margin_metadata(margin_root, dataset_id, categories):
    ds_dir = os.path.join(margin_root, dataset_id)
    os.makedirs(ds_dir, exist_ok=True)
    with open(os.path.join(ds_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"id": dataset_id, "name": "monochro_03_CZT8", "category": categories}, f)


def _cfg(margin_export_root="", dataset_id_monochro_margin="", pool_train_ratio=0.7,
         raw_shift_cache_dir=""):
    return OmegaConf.create({
        "margin_export_root": margin_export_root,
        "dataset_id_monochro_margin": dataset_id_monochro_margin,
        "pool_train_ratio": pool_train_ratio,
        "raw_shift_cache_dir": raw_shift_cache_dir,
    })


def _make_dataset_path(tmp_path, n_train_good=3, n_test_good=2):
    dataset_path = str(tmp_path / "4_dataset" / "053" / "monochro")
    for i in range(n_train_good):
        _write_fake_image(os.path.join(dataset_path, "train", "good", f"g{i}.png"), shape=(16, 16, 3))
    for i in range(n_test_good):
        _write_fake_image(
            os.path.join(dataset_path, "test", "good", "images", f"g{i}.png"), shape=(16, 16, 3))
    return dataset_path


class TestBuildDatasetsUsesItem03CZT8RawShiftImageFolder:
    """コピー元との差分（`Item03CZT8RawShiftImageFolder`を使うこと）を確認する。"""

    def test_margin_dataset_is_item_03czt8_class(self, tmp_path):
        dataset_path = _make_dataset_path(tmp_path, n_train_good=1, n_test_good=1)
        margin_root = str(tmp_path / "export_root_margin")
        _write_margin_metadata(margin_root, "ds-margin-1", categories=[
            {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
        ])
        for i in range(2):
            _write_fake_image(
                os.path.join(margin_root, "ds-margin-1", "binary", "053", "cat-good", f"raw_{i}.bmp"))
        cfg = _cfg(margin_export_root=margin_root, dataset_id_monochro_margin="ds-margin-1",
                   pool_train_ratio=0.5, raw_shift_cache_dir=str(tmp_path / "_cache"))

        train_set, validation_set, _ = _build_datasets(
            cfg, dataset_path, "053", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
            crop_x0=CROP_X0, crop_width=CROP_WIDTH, overlap=OVERLAP,
        )

        margin_train_dataset = train_set.datasets[0].dataset
        margin_val_dataset = validation_set.datasets[0].dataset
        assert isinstance(margin_train_dataset, Item03CZT8RawShiftImageFolder)
        assert isinstance(margin_val_dataset, Item03CZT8RawShiftImageFolder)
        # 既存RawShiftImageFolderのインスタンスであってはならない(誤って旧クラスを
        # importしていないことの確認)。
        from utils.raw_shift_dataset import RawShiftImageFolder
        assert not isinstance(margin_train_dataset, RawShiftImageFolder)

    def test_margin_dataset_uses_03czt8_crop_params(self, tmp_path):
        dataset_path = _make_dataset_path(tmp_path, n_train_good=1, n_test_good=1)
        margin_root = str(tmp_path / "export_root_margin")
        _write_margin_metadata(margin_root, "ds-margin-1", categories=[
            {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
        ])
        for i in range(2):
            _write_fake_image(
                os.path.join(margin_root, "ds-margin-1", "binary", "053", "cat-good", f"raw_{i}.bmp"))
        cfg = _cfg(margin_export_root=margin_root, dataset_id_monochro_margin="ds-margin-1",
                   pool_train_ratio=0.5, raw_shift_cache_dir=str(tmp_path / "_cache"))

        train_set, _, _ = _build_datasets(
            cfg, dataset_path, "053", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
            crop_x0=CROP_X0, crop_width=CROP_WIDTH, overlap=OVERLAP,
        )

        margin_train_dataset = train_set.datasets[0].dataset
        assert margin_train_dataset.crop_x0 == 655
        assert margin_train_dataset.crop_width == 950
        assert margin_train_dataset.overlap == 50


class TestBuildDatasetsBehaviorMatchesCopySource:
    """コピー元(`train/monochro.py`)と同じ挙動(件数・分割ロジック)を保つことを確認する。"""

    def test_uses_export_root_only_when_margin_not_found(self, tmp_path):
        dataset_path = _make_dataset_path(tmp_path, n_train_good=3, n_test_good=2)
        cfg = _cfg()

        train_set, validation_set, full_train_set = _build_datasets(
            cfg, dataset_path, "053", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
            crop_x0=CROP_X0, crop_width=CROP_WIDTH, overlap=OVERLAP,
        )

        # TIGHT_TRAIN_RATIO=0.8 で train/good(3件)を分割: train=2 / val=1。
        assert len(train_set) == 2
        assert len(validation_set) == 1
        assert len(full_train_set) == len(train_set)

    def test_merges_margin_and_tight_when_margin_found(self, tmp_path):
        dataset_path = _make_dataset_path(tmp_path, n_train_good=3, n_test_good=2)
        margin_root = str(tmp_path / "export_root_margin")
        _write_margin_metadata(margin_root, "ds-margin-1", categories=[
            {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
        ])
        for i in range(2):
            _write_fake_image(
                os.path.join(margin_root, "ds-margin-1", "binary", "053", "cat-good", f"raw_{i}.bmp"))
        cfg = _cfg(margin_export_root=margin_root, dataset_id_monochro_margin="ds-margin-1",
                   pool_train_ratio=0.7, raw_shift_cache_dir=str(tmp_path / "_cache"))

        train_set, validation_set, full_train_set = _build_datasets(
            cfg, dataset_path, "053", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
            crop_x0=CROP_X0, crop_width=CROP_WIDTH, overlap=OVERLAP,
        )

        # マージン(2ファイル→top/bottom4件)はファイル単位でint(0.7*2)=1ファイルがtrain、
        # 1ファイルがval（各2件）に分割される。
        # train = マージンtrain(2) + tight train(2) = 4。
        assert len(train_set) == 4
        # validation = マージンval(2) + tight val(1) = 3。
        assert len(validation_set) == 3
        assert len(full_train_set) == len(train_set)

    def test_build_datasets_succeeds_without_test_good_directory(self, tmp_path):
        """test/goodが存在しなくても構築できる(参照していない証拠)。"""
        dataset_path = str(tmp_path / "4_dataset" / "053" / "monochro")
        for i in range(4):
            _write_fake_image(
                os.path.join(dataset_path, "train", "good", f"g{i}.png"), shape=(16, 16, 3))
        assert not os.path.exists(os.path.join(dataset_path, "test", "good", "images"))
        cfg = _cfg()

        train_set, validation_set, _ = _build_datasets(
            cfg, dataset_path, "053", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
            crop_x0=CROP_X0, crop_width=CROP_WIDTH, overlap=OVERLAP,
        )

        # round(4*0.8)=3 -> train=3 / val=1。
        assert len(train_set) == 3
        assert len(validation_set) == 1
