"""export_root（binary/ + metadata.json）から直接 pool を構築する新選定ロジックのテスト。

dataset-export-root-migration.md v1.4 決定2・3・7・8・9・11 に対応。
FTP/1_download 経由の旧挙動 (process_annotated_images) は
test_manager_characterization.py から本ファイルへ移動した。

実行: cd training && python -m pytest tests/dataset/test_manager_export_root.py -v
"""
import json
import os

import cv2
import numpy as np
import pytest
from omegaconf import OmegaConf

from utils.split_manager import _extract_product_id


def _make_cfg(tmp_path, target_color="001"):
    return OmegaConf.create({
        "common": {
            "target_color": target_color,
            "export_root": str(tmp_path / "export_root"),
            "dataset_id_monochro": "ds-monochro",
            "dataset_id_color": "ds-color",
            "pool_base": str(tmp_path / "3_pool"),
            "dataset_path": str(tmp_path / "4_dataset"),
            "model_dir": str(tmp_path / "6_model"),
            "backup_dir": str(tmp_path / "7_backup"),
        },
        "color": {"image_size_height": 16, "image_size_width": 24},
        "monochro": {"image_size_height": 16, "image_size_width": 24},
    })


def _write_fake_image(path, shape=(40, 60, 3)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = np.zeros(shape, dtype=np.uint8)
    cv2.imwrite(str(path), img)


def _write_metadata(export_root, dataset_id, categories):
    ds_dir = os.path.join(export_root, dataset_id)
    os.makedirs(ds_dir, exist_ok=True)
    metadata = {
        "id": dataset_id,
        "name": "monochro_5_YY",
        "description": None,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "category": categories,
        "provenance": {"project_id": "1", "project_name": "test"},
    }
    with open(os.path.join(ds_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f)


def test_export_root_builds_good_and_defect_pool_and_excludes_invalid(tmp_path):
    from dataset import DatasetManager

    cfg = _make_cfg(tmp_path)
    export_root = cfg.common.export_root
    dataset_id = cfg.common.dataset_id_monochro
    _write_metadata(export_root, dataset_id, categories=[
        {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
        {"category_id": "cat-defect", "on_class": "1", "invalid_flg": "0"},
        {"category_id": "cat-invalid", "on_class": "1", "invalid_flg": "1"},
    ])
    binary_base = os.path.join(export_root, dataset_id, "binary", cfg.common.target_color)
    _write_fake_image(os.path.join(binary_base, "cat-good", "OK_image_1_top.bmp"))
    _write_fake_image(os.path.join(binary_base, "cat-good", "OK_image_1_bottom.bmp"))
    _write_fake_image(os.path.join(binary_base, "cat-defect", "NG_image_2_top.bmp"))
    _write_fake_image(os.path.join(binary_base, "cat-defect", "NG_image_2_bottom.bmp"))
    _write_fake_image(os.path.join(binary_base, "cat-invalid", "NG_image_3_top.bmp"))

    mgr = DatasetManager(cfg)
    mgr.process_annotated_images(modes=("monochro",))

    good_pool = os.path.join(cfg.common.pool_base, cfg.common.target_color, "monochro", "good_pool")
    defect_pool = os.path.join(cfg.common.pool_base, cfg.common.target_color, "monochro", "defect_pool")

    # ファイル名正規化 (_top→_0, _bottom→_1)
    assert sorted(os.listdir(good_pool)) == ["OK_image_1_0.bmp", "OK_image_1_1.bmp"]
    assert sorted(os.listdir(defect_pool)) == ["NG_image_2_0.bmp", "NG_image_2_1.bmp"]

    # invalid_flg=1 のカテゴリはどちらのpoolにも現れない
    all_files = os.listdir(good_pool) + os.listdir(defect_pool)
    assert not any("NG_image_3" in f for f in all_files)

    # pool格納後の画像サイズがconfigのimage_sizeにリサイズされていること
    resized = cv2.imread(os.path.join(good_pool, "OK_image_1_0.bmp"))
    assert resized.shape[:2] == (cfg.monochro.image_size_height, cfg.monochro.image_size_width)


def test_normalized_filenames_group_by_product_id_via_extract_product_id(tmp_path):
    """正規化後のファイル名に対し、既存 _extract_product_id (無改修) が
    同一製品のtop/bottomを正しく同一グループとして扱うことを確認する (回帰テスト)。"""
    from dataset import DatasetManager

    top = DatasetManager._normalize_export_filename("OK_image_1_top.bmp")
    bottom = DatasetManager._normalize_export_filename("OK_image_1_bottom.bmp")
    other = DatasetManager._normalize_export_filename("NG_image_2_top.bmp")

    assert top == "OK_image_1_0.bmp"
    assert bottom == "OK_image_1_1.bmp"
    assert _extract_product_id(top) == _extract_product_id(bottom) == "OK_image_1"
    assert _extract_product_id(other) != _extract_product_id(top)


def test_target_color_mismatch_raises_clear_error_not_silent_zero(tmp_path):
    from dataset import DatasetManager

    cfg = _make_cfg(tmp_path, target_color="001")
    export_root = cfg.common.export_root
    dataset_id = cfg.common.dataset_id_monochro
    _write_metadata(export_root, dataset_id, categories=[
        {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
    ])
    # binary/ 配下は "999" (cfg.common.target_color="001" と不一致)
    binary_base = os.path.join(export_root, dataset_id, "binary", "999")
    _write_fake_image(os.path.join(binary_base, "cat-good", "OK_image_1_top.bmp"))

    mgr = DatasetManager(cfg)
    with pytest.raises(FileNotFoundError, match="binary/001"):
        mgr.process_annotated_images(modes=("monochro",))


def _pools(cfg, mode="monochro"):
    base = os.path.join(cfg.common.pool_base, cfg.common.target_color, mode)
    return os.path.join(base, "good_pool"), os.path.join(base, "defect_pool")


def _setup_good_defect(tmp_path):
    cfg = _make_cfg(tmp_path)
    export_root = cfg.common.export_root
    dataset_id = cfg.common.dataset_id_monochro
    _write_metadata(export_root, dataset_id, categories=[
        {"category_id": "cat-good", "on_class": "0", "invalid_flg": "0"},
        {"category_id": "cat-defect", "on_class": "1", "invalid_flg": "0"},
        {"category_id": "cat-invalid", "on_class": "1", "invalid_flg": "1"},
    ])
    binary_base = os.path.join(export_root, dataset_id, "binary", cfg.common.target_color)
    for category_id in ("cat-good", "cat-defect", "cat-invalid"):
        os.makedirs(os.path.join(binary_base, category_id), exist_ok=True)
    return cfg, binary_base


class TestPoolMirrorsExportRoot:
    """pool を export_root に同期する（pool-dataset-sync-split.md 決定3）。"""

    def test_relabeled_good_to_ng_is_removed_from_good_pool(self, tmp_path):
        from dataset import DatasetManager

        cfg, binary_base = _setup_good_defect(tmp_path)
        good_src = os.path.join(binary_base, "cat-good", "OK_image_1_top.bmp")
        _write_fake_image(good_src)
        _write_fake_image(os.path.join(binary_base, "cat-good", "OK_image_2_top.bmp"))
        mgr = DatasetManager(cfg)
        mgr.process_annotated_images(modes=("monochro",))

        # export_root 側で good → ng に付け替え
        os.replace(good_src, os.path.join(binary_base, "cat-defect", "OK_image_1_top.bmp"))
        mgr.process_annotated_images(modes=("monochro",))

        good_pool, defect_pool = _pools(cfg)
        assert sorted(os.listdir(good_pool)) == ["OK_image_2_0.bmp"]
        assert sorted(os.listdir(defect_pool)) == ["OK_image_1_0.bmp"]

    def test_image_gone_from_export_root_is_removed_from_pool(self, tmp_path):
        from dataset import DatasetManager

        cfg, binary_base = _setup_good_defect(tmp_path)
        gone = os.path.join(binary_base, "cat-defect", "NG_image_3_bottom.bmp")
        _write_fake_image(gone)
        _write_fake_image(os.path.join(binary_base, "cat-defect", "NG_image_3_top.bmp"))
        mgr = DatasetManager(cfg)
        mgr.process_annotated_images(modes=("monochro",))

        os.remove(gone)
        mgr.process_annotated_images(modes=("monochro",))

        _, defect_pool = _pools(cfg)
        assert sorted(os.listdir(defect_pool)) == ["NG_image_3_0.bmp"]

    def test_moved_to_invalid_category_is_removed_from_pool(self, tmp_path):
        from dataset import DatasetManager

        cfg, binary_base = _setup_good_defect(tmp_path)
        src = os.path.join(binary_base, "cat-defect", "NG_image_4_top.bmp")
        _write_fake_image(src)
        # クラスの最後の1枚は消さない仕様のため、defect に別の画像を残す
        _write_fake_image(os.path.join(binary_base, "cat-defect", "NG_image_8_top.bmp"))
        mgr = DatasetManager(cfg)
        mgr.process_annotated_images(modes=("monochro",))

        os.replace(src, os.path.join(binary_base, "cat-invalid", "NG_image_4_top.bmp"))
        mgr.process_annotated_images(modes=("monochro",))

        _, defect_pool = _pools(cfg)
        assert os.listdir(defect_pool) == ["NG_image_8_0.bmp"]

    def test_undecodable_export_image_keeps_existing_pool_copy(self, tmp_path):
        """一時的なデコード失敗で既存コピーを失わない。"""
        from dataset import DatasetManager

        cfg, binary_base = _setup_good_defect(tmp_path)
        src = os.path.join(binary_base, "cat-good", "OK_image_5_top.bmp")
        _write_fake_image(src)
        # 空クラスガードで偶然通らないよう、正常な良品をもう1枚置く
        _write_fake_image(os.path.join(binary_base, "cat-good", "OK_image_12_top.bmp"))
        mgr = DatasetManager(cfg)
        mgr.process_annotated_images(modes=("monochro",))

        with open(src, "wb") as f:  # 0 byte = デコード失敗
            f.write(b"")
        mgr.process_annotated_images(modes=("monochro",))

        good_pool, _ = _pools(cfg)
        assert sorted(os.listdir(good_pool)) == ["OK_image_12_0.bmp", "OK_image_5_0.bmp"]

    def test_non_image_files_in_pool_are_left_alone(self, tmp_path):
        from dataset import DatasetManager

        cfg, binary_base = _setup_good_defect(tmp_path)
        _write_fake_image(os.path.join(binary_base, "cat-good", "OK_image_6_top.bmp"))
        good_pool, _ = _pools(cfg)
        os.makedirs(good_pool, exist_ok=True)
        with open(os.path.join(good_pool, "README.txt"), "w") as f:
            f.write("x")

        DatasetManager(cfg).process_annotated_images(modes=("monochro",))

        assert sorted(os.listdir(good_pool)) == ["OK_image_6_0.bmp", "README.txt"]

    def test_export_class_with_no_images_keeps_that_pool(self, tmp_path):
        """export_root で良品が0枚・不良はある場合、good_pool は消さず defect_pool は同期する。"""
        from dataset import DatasetManager

        cfg, binary_base = _setup_good_defect(tmp_path)
        good_src = os.path.join(binary_base, "cat-good", "OK_image_9_top.bmp")
        _write_fake_image(good_src)
        _write_fake_image(os.path.join(binary_base, "cat-defect", "NG_image_10_top.bmp"))
        gone = os.path.join(binary_base, "cat-defect", "NG_image_11_top.bmp")
        _write_fake_image(gone)
        mgr = DatasetManager(cfg)
        mgr.process_annotated_images(modes=("monochro",))

        os.remove(good_src)
        os.remove(gone)
        mgr.process_annotated_images(modes=("monochro",))

        good_pool, defect_pool = _pools(cfg)
        assert os.listdir(good_pool) == ["OK_image_9_0.bmp"]
        assert os.listdir(defect_pool) == ["NG_image_10_0.bmp"]

    def test_empty_export_root_does_not_wipe_pool(self, tmp_path):
        """export_root 側が一時的に空に見えても（共有の同期途中等）pool を丸ごと消さない。"""
        from dataset import DatasetManager

        cfg, binary_base = _setup_good_defect(tmp_path)
        src = os.path.join(binary_base, "cat-good", "OK_image_7_top.bmp")
        _write_fake_image(src)
        mgr = DatasetManager(cfg)
        mgr.process_annotated_images(modes=("monochro",))

        os.remove(src)
        mgr.process_annotated_images(modes=("monochro",))

        good_pool, _ = _pools(cfg)
        assert os.listdir(good_pool) == ["OK_image_7_0.bmp"]

    def test_unknown_category_folder_skips_sync_deletion_for_the_mode(self, tmp_path):
        """metadata に無いカテゴリのフォルダがある（metadata が古い・書き込み途中）ときは削除しない。"""
        from dataset import DatasetManager

        cfg, binary_base = _setup_good_defect(tmp_path)
        gone = os.path.join(binary_base, "cat-good", "OK_image_13_top.bmp")
        _write_fake_image(gone)
        _write_fake_image(os.path.join(binary_base, "cat-good", "OK_image_14_top.bmp"))
        mgr = DatasetManager(cfg)
        mgr.process_annotated_images(modes=("monochro",))

        os.remove(gone)
        _write_fake_image(os.path.join(binary_base, "cat-unknown", "OK_image_15_top.bmp"))
        mgr.process_annotated_images(modes=("monochro",))

        good_pool, _ = _pools(cfg)
        assert sorted(os.listdir(good_pool)) == ["OK_image_13_0.bmp", "OK_image_14_0.bmp"]

    def test_extension_case_change_in_export_keeps_pool_copy(self, tmp_path):
        """export 側の拡張子の大文字小文字が変わっても pool の既存コピーを消さない（Windows は区別しない）。"""
        from dataset import DatasetManager

        cfg, binary_base = _setup_good_defect(tmp_path)
        src = os.path.join(binary_base, "cat-good", "OK_image_16_top.bmp")
        _write_fake_image(src)
        _write_fake_image(os.path.join(binary_base, "cat-good", "OK_image_17_top.bmp"))
        mgr = DatasetManager(cfg)
        mgr.process_annotated_images(modes=("monochro",))

        os.replace(src, os.path.join(binary_base, "cat-good", "OK_image_16_top.BMP"))
        mgr.process_annotated_images(modes=("monochro",))

        good_pool, _ = _pools(cfg)
        assert sorted(f.lower() for f in os.listdir(good_pool)) == [
            "ok_image_16_0.bmp", "ok_image_17_0.bmp"]


class TestPoolSyncDeleteRatioGuard:
    """一覧が部分的に見えた等で大量削除になるときは止める（pool-dataset-sync-split.md 決定3）。"""

    def _build(self, tmp_path, n_good, ratio=None):
        from dataset import DatasetManager

        cfg, binary_base = _setup_good_defect(tmp_path)
        if ratio is not None:
            cfg.common.pool_sync_max_delete_ratio = ratio
        good_dir = os.path.join(binary_base, "cat-good")
        srcs = [os.path.join(good_dir, f"OK_image_{i}_top.bmp") for i in range(n_good)]
        for src in srcs:
            _write_fake_image(src)
        mgr = DatasetManager(cfg)
        mgr.process_annotated_images(modes=("monochro",))
        return cfg, mgr, srcs

    def test_mass_deletion_over_ratio_is_skipped(self, tmp_path):
        cfg, mgr, srcs = self._build(tmp_path, n_good=40)
        for src in srcs[:15]:  # 15/40 = 37.5% > 20% かつ 15 > 10 枚
            os.remove(src)

        mgr.process_annotated_images(modes=("monochro",))

        good_pool, _ = _pools(cfg)
        assert len(os.listdir(good_pool)) == 40

    def test_deletion_within_ratio_is_applied(self, tmp_path):
        cfg, mgr, srcs = self._build(tmp_path, n_good=60)
        for src in srcs[:11]:  # 11/60 = 18% <= 20%
            os.remove(src)

        mgr.process_annotated_images(modes=("monochro",))

        good_pool, _ = _pools(cfg)
        assert len(os.listdir(good_pool)) == 49

    def test_deletion_exactly_at_ratio_is_applied(self, tmp_path):
        cfg, mgr, srcs = self._build(tmp_path, n_good=60)
        for src in srcs[:12]:  # 12/60 = ちょうど 20%（超えていない）
            os.remove(src)

        mgr.process_annotated_images(modes=("monochro",))

        good_pool, _ = _pools(cfg)
        assert len(os.listdir(good_pool)) == 48

    def test_deletion_of_exactly_count_limit_is_applied(self, tmp_path):
        cfg, mgr, srcs = self._build(tmp_path, n_good=12)
        for src in srcs[:10]:  # 83% だがちょうど 10 枚（超えていない）
            os.remove(src)

        mgr.process_annotated_images(modes=("monochro",))

        good_pool, _ = _pools(cfg)
        assert len(os.listdir(good_pool)) == 2

    def test_small_deletion_count_is_applied_even_over_ratio(self, tmp_path):
        cfg, mgr, srcs = self._build(tmp_path, n_good=12)
        for src in srcs[:6]:  # 50% だが 6 枚 <= 10 枚
            os.remove(src)

        mgr.process_annotated_images(modes=("monochro",))

        good_pool, _ = _pools(cfg)
        assert len(os.listdir(good_pool)) == 6

    def test_ratio_can_be_raised_by_config(self, tmp_path):
        cfg, mgr, srcs = self._build(tmp_path, n_good=40, ratio=0.5)
        for src in srcs[:15]:
            os.remove(src)

        mgr.process_annotated_images(modes=("monochro",))

        good_pool, _ = _pools(cfg)
        assert len(os.listdir(good_pool)) == 25
