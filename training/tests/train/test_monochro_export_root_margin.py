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

from train.monochro import (
    _build_datasets, _resolve_margin_good_root, _split_tight_good, _sync_margin_cache,
)


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


def _cfg(margin_export_root="", dataset_id_monochro_margin="", pool_train_ratio=0.7,
         raw_shift_cache_dir=""):
    return OmegaConf.create({
        "margin_export_root": margin_export_root,
        "dataset_id_monochro_margin": dataset_id_monochro_margin,
        "pool_train_ratio": pool_train_ratio,
        "raw_shift_cache_dir": raw_shift_cache_dir,
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
    """検証基準6・7 (dataset-export-root-migration.md v1.7 で更新、
    eval-calibration-leak-fixes.md 決定2〜4 で再更新):
    use_raw_shift=True 時の train/val Dataset合体。マージンあり画像は
    pool_train_ratioで**ファイル(撮像)単位**にtrain/valへ分割され、val側はoffset=0固定。
    tight側は`train/good`をTIGHT_TRAIN_RATIO(0.8)で分割し、`test/good`は参照しない。"""

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

        # train/good(3件・g0/g1/g2は各々別product)をTIGHT_TRAIN_RATIO=0.8で分割:
        # round(3*0.8)=2 -> train=2 / val=1。`test/good`(2件)は参照しない（決定2）。
        # defectは一切含まれない（defectの5件は含まれない）。
        assert len(train_set) == 2
        assert len(validation_set) == 1
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
        cfg = _cfg(margin_export_root=margin_root, dataset_id_monochro_margin="ds-margin-1",
                   pool_train_ratio=0.7, raw_shift_cache_dir=str(tmp_path / "_cache"))

        train_set, validation_set, full_train_set = _build_datasets(
            cfg, dataset_path, "001", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
        )

        # マージン(2ファイル→top/bottom4件)はファイル単位でint(0.7*2)=1ファイルがtrain、
        # 1ファイルがval（各2件）に分割される（決定4）。
        # train = マージンtrain(2) + tight train(2) = 4。defectは含まれない。
        assert len(train_set) == 4
        # validation = マージンval(2) + tight val(1) = 3。`test/good`は参照しない。
        assert len(validation_set) == 3
        assert len(full_train_set) == len(train_set)
        # crop_shift_max_pxがRawShiftImageFolderまで正しく配線されていること
        # (train側はshift_max=20、val側はoffset=0固定=shift_max=0)。
        margin_train_dataset = train_set.datasets[0]
        assert margin_train_dataset.dataset.shift_max == 20
        margin_val_dataset = validation_set.datasets[0]
        assert margin_val_dataset.dataset.shift_max == 0

    def test_validation_set_includes_margin_split(self, tmp_path):
        """valはマージンデータのpool_train_ratio残り分（offset=0固定）と、export_root
        `train/good`のTIGHT_TRAIN_RATIO残り分の合成になること（決定2・4で更新）。"""
        dataset_path = self._make_dataset_path(tmp_path, n_train_good=1, n_test_good=1)
        margin_root = str(tmp_path / "export_root_margin")
        _write_margin_metadata(margin_root, "ds-margin-1", categories=[
            {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
        ])
        for i in range(5):
            _write_fake_image(
                os.path.join(margin_root, "ds-margin-1", "binary", "001", "cat-good", f"raw_{i}.bmp"))
        cfg = _cfg(margin_export_root=margin_root, dataset_id_monochro_margin="ds-margin-1",
                   pool_train_ratio=0.7, raw_shift_cache_dir=str(tmp_path / "_cache"))

        train_set, validation_set, _ = _build_datasets(
            cfg, dataset_path, "001", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
        )

        # マージン側は5ファイル(raw)→10件。ファイル単位でint(0.7*5)=3ファイル(6件)がtrain、
        # 2ファイル(4件)がvalに分割される（決定4）。
        # tight側はtrain/good=1件(=1product)のみなので max(1, round(1*0.8))=1 -> train=1/val=0。
        # train = マージンtrain(6) + tight train(1) = 7。
        assert len(train_set) == 7
        # validation = マージンval(4) + tight val(0) = 4。マージン混入なし、ではなく
        # 意図的にマージンのval分が含まれることを確認する。
        assert len(validation_set) == 4

    def test_margin_split_ratio_follows_pool_train_ratio(self, tmp_path):
        """pool_train_ratioを変えるとマージンのtrain/val分割数が追従すること。"""
        dataset_path = self._make_dataset_path(tmp_path, n_train_good=1, n_test_good=1)
        margin_root = str(tmp_path / "export_root_margin")
        _write_margin_metadata(margin_root, "ds-margin-1", categories=[
            {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
        ])
        for i in range(5):
            _write_fake_image(
                os.path.join(margin_root, "ds-margin-1", "binary", "001", "cat-good", f"raw_{i}.bmp"))
        # pool_train_ratio=0.5: マージン5ファイル -> train=int(0.5*5)=2ファイル(4件)/
        # val=3ファイル(6件)。
        cfg = _cfg(margin_export_root=margin_root, dataset_id_monochro_margin="ds-margin-1",
                   pool_train_ratio=0.5, raw_shift_cache_dir=str(tmp_path / "_cache"))

        train_set, validation_set, _ = _build_datasets(
            cfg, dataset_path, "001", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
        )

        # train = マージンtrain(4) + tight train(1) = 5。
        assert len(train_set) == 5
        # validation = マージンval(6) + tight val(0) = 6。
        assert len(validation_set) == 6


class TestLeakPrevention:
    """eval-calibration-leak-fixes.md 検証基準1〜3（集合の非交差）。

    リーク解消の完成条件は指標の数値ではなく「学習・較正に使った集合と評価に使った
    集合が交差しないこと」で定義する。
    """

    def _margin_root_with(self, tmp_path, n_files):
        margin_root = str(tmp_path / "export_root_margin")
        _write_margin_metadata(margin_root, "ds-margin-1", categories=[
            {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
        ])
        good_dir = os.path.join(margin_root, "ds-margin-1", "binary", "001", "cat-good")
        for i in range(n_files):
            _write_fake_image(os.path.join(good_dir, f"raw_{i}.bmp"))
        return margin_root

    def test_build_datasets_succeeds_without_test_good_directory(self, tmp_path):
        """検証基準1: `test/good` が存在しなくても構築できる（＝参照していない証拠）。"""
        dataset_path = str(tmp_path / "4_dataset" / "001" / "monochro")
        for i in range(4):
            _write_fake_image(
                os.path.join(dataset_path, "train", "good", f"g{i}.png"), shape=(16, 16, 3))
        assert not os.path.exists(os.path.join(dataset_path, "test", "good", "images"))
        cfg = _cfg()

        train_set, validation_set, _ = _build_datasets(
            cfg, dataset_path, "001", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
        )

        # round(4*0.8)=3 -> train=3 / val=1。
        assert len(train_set) == 3
        assert len(validation_set) == 1

    def test_test_good_size_does_not_affect_train_or_validation(self, tmp_path):
        """検証基準1: `test/good` を増やしても train/val のサイズが変わらない。"""
        sizes = []
        for n_test_good in (1, 50):
            dataset_path = str(tmp_path / f"ds{n_test_good}" / "001" / "monochro")
            for i in range(4):
                _write_fake_image(
                    os.path.join(dataset_path, "train", "good", f"g{i}.png"), shape=(16, 16, 3))
            for i in range(n_test_good):
                _write_fake_image(
                    os.path.join(dataset_path, "test", "good", "images", f"t{i}.png"),
                    shape=(16, 16, 3))
            train_set, validation_set, _ = _build_datasets(
                _cfg(), dataset_path, "001", train_tf=None,
                use_raw_shift=True, crop_shift_max_px=20,
                image_size_width=16, image_size_height=16, seed=42,
            )
            sizes.append((len(train_set), len(validation_set)))

        assert sizes[0] == sizes[1]

    def test_margin_train_and_val_never_share_a_raw_file(self, tmp_path):
        """検証基準2: 同一 raw ファイル由来のサンプルが train と val に跨らない。"""
        dataset_path = str(tmp_path / "4_dataset" / "001" / "monochro")
        _write_fake_image(
            os.path.join(dataset_path, "train", "good", "g0.png"), shape=(16, 16, 3))
        margin_root = self._margin_root_with(tmp_path, n_files=10)
        cfg = _cfg(margin_export_root=margin_root,
                   dataset_id_monochro_margin="ds-margin-1", pool_train_ratio=0.7,
                   raw_shift_cache_dir=str(tmp_path / "_cache"))

        train_set, validation_set, _ = _build_datasets(
            cfg, dataset_path, "001", train_tf=None,
            use_raw_shift=True, crop_shift_max_px=20,
            image_size_width=16, image_size_height=16, seed=42,
        )

        margin_train, margin_val = train_set.datasets[0], validation_set.datasets[0]
        samples_per_file = len(margin_train.dataset) // len(margin_train.dataset.paths)
        assert samples_per_file == 2  # sample_mode="both" (top/bottom)
        train_file_ids = {i // samples_per_file for i in margin_train.indices}
        val_file_ids = {i // samples_per_file for i in margin_val.indices}

        assert train_file_ids & val_file_ids == set()
        assert len(train_file_ids) + len(val_file_ids) == 10
        # 各ファイルは top/bottom の2件そろって同じ側に入る。
        assert len(margin_train.indices) == 2 * len(train_file_ids)
        assert len(margin_val.indices) == 2 * len(val_file_ids)

    def test_tight_split_keeps_product_faces_together(self, tmp_path):
        """検証基準3: 同一 product_id (`_0`/`_1`) が train と val に跨らない。"""
        train_good = str(tmp_path / "4_dataset" / "001" / "monochro" / "train" / "good")
        for cap in range(5):
            for face in (0, 1):
                _write_fake_image(
                    os.path.join(train_good, f"cap{cap}_{face}.png"), shape=(16, 16, 3))

        train_set, validation_set = _split_tight_good(train_good, train_tf=None, seed=42)

        def _product_ids(subset):
            return {
                os.path.basename(subset.dataset.samples[i]).rsplit("_", 1)[0]
                for i in subset.indices
            }

        assert _product_ids(train_set) & _product_ids(validation_set) == set()
        # round(5*0.8)=4 product が train、残り1 product が val。各 product は2面そろう。
        assert len(train_set) == 8
        assert len(validation_set) == 2


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


class TestSyncMarginCache:
    """`_sync_margin_cache`（ネットワーク共有→ローカル一時キャッシュ）のテスト。

    @.kiro/specs/retraining/monochro-margin-local-cache.md の検証基準。
    """

    def test_copies_all_images_from_source(self, tmp_path):
        src = tmp_path / "margin_root"
        for i in range(3):
            _write_fake_image(str(src / f"raw_{i}.bmp"), shape=(16, 16, 3))
        cache_dir = str(tmp_path / "_cache")

        result = _sync_margin_cache(str(src), cache_dir)

        assert result == cache_dir
        copied = sorted(os.listdir(cache_dir))
        assert copied == ["raw_0.bmp", "raw_1.bmp", "raw_2.bmp"]

    def test_ignores_non_image_files(self, tmp_path):
        src = tmp_path / "margin_root"
        _write_fake_image(str(src / "raw_0.bmp"), shape=(16, 16, 3))
        os.makedirs(src, exist_ok=True)
        with open(src / "_import_done.marker", "w", encoding="utf-8") as f:
            f.write("")
        cache_dir = str(tmp_path / "_cache")

        _sync_margin_cache(str(src), cache_dir)

        assert os.listdir(cache_dir) == ["raw_0.bmp"]

    def test_clears_previous_cache_content_before_copying(self, tmp_path):
        cache_dir = str(tmp_path / "_cache")
        os.makedirs(cache_dir, exist_ok=True)
        stale_path = os.path.join(cache_dir, "stale_from_other_color.bmp")
        with open(stale_path, "w", encoding="utf-8") as f:
            f.write("")

        src = tmp_path / "margin_root"
        _write_fake_image(str(src / "raw_0.bmp"), shape=(16, 16, 3))

        _sync_margin_cache(str(src), cache_dir)

        assert os.listdir(cache_dir) == ["raw_0.bmp"]
