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
