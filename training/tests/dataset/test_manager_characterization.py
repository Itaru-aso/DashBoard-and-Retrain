"""現状の pipline.DatasetManager の挙動を固定するテスト。

Seam6移行(datasetパッケージへの切り出し)前の挙動を記録し、
Task1で移動する dataset.DatasetManager が同じ結果を出すことの比較対象とする。

実行: cd training && python -m pytest tests/dataset/test_manager_characterization.py -v
"""
import os

import cv2
import numpy as np
from omegaconf import OmegaConf


def _make_cfg(tmp_path, target_color="841"):
    return OmegaConf.create({
        "common": {
            "target_color": target_color,
            "download_dir": str(tmp_path / "1_download"),
            "pool_base": str(tmp_path / "2_pool"),
            "staging_dir": str(tmp_path / "3_staging"),
            "dataset_path": str(tmp_path / "4_dataset"),
            "model_dir": str(tmp_path / "6_model"),
            "backup_dir": str(tmp_path / "7_backup"),
        },
        "color": {
            "image_size_height": 32,
            "image_size_width": 32,
            "pool_train_ratio": 0.7,
            "defect_staging": {"auto_split_halves": True, "clear_before_download": False},
        },
        "monochro": {
            "image_size_height": 32,
            "image_size_width": 32,
            "pool_train_ratio": 0.7,
            "defect_staging": {"auto_split_halves": True, "clear_before_download": False},
        },
    })


def _write_fake_image(path, shape):
    img = np.zeros(shape, dtype=np.uint8)
    cv2.imwrite(str(path), img)


def test_process_annotated_images_color_routes_good_and_defect(tmp_path):
    from dataset import DatasetManager

    cfg = _make_cfg(tmp_path)
    color = cfg.common.target_color
    download_base = tmp_path / "1_download" / color / "color"
    good_dir = download_base / "good"
    defect_dir = download_base / "defect"
    good_dir.mkdir(parents=True)
    defect_dir.mkdir(parents=True)
    # color crop は crop_rectangle=(215,0,1675,H) を rotate(90°CW)後の画像に適用する。
    # rotate後の列数は rotate前の行数(H0)に等しいため、H0>=1890 が必要 (215+1675)。
    # 形状(H0,W0,3)=(1900,60,3)。
    _write_fake_image(good_dir / "g1.png", (1900, 60, 3))
    _write_fake_image(defect_dir / "d1.png", (1900, 60, 3))

    mgr = DatasetManager(cfg)
    mgr.process_annotated_images(modes=("color",))

    pool_good = tmp_path / "2_pool" / color / "color" / "good_pool"
    staging = tmp_path / "3_staging" / color / "color"
    assert sorted(os.listdir(pool_good)) == ["g1_0.png", "g1_1.png"]
    assert sorted(os.listdir(staging)) == ["d1_0.png", "d1_1.png"]


def test_process_annotated_images_monochro_routes_good_and_defect(tmp_path):
    from dataset import DatasetManager

    cfg = _make_cfg(tmp_path)
    color = cfg.common.target_color
    download_base = tmp_path / "1_download" / color / "monochro"
    good_dir = download_base / "good"
    defect_dir = download_base / "defect"
    good_dir.mkdir(parents=True)
    defect_dir.mkdir(parents=True)
    # monochro crop は crop_rectangle=(485,0,1250,H) を rotate なしで適用するため、
    # 画像は列数(W0)>=1735 が必要 (485+1250)。形状(H0,W0,3)=(100,1740,3)。
    _write_fake_image(good_dir / "g1.png", (100, 1740, 3))
    _write_fake_image(defect_dir / "d1.png", (100, 1740, 3))

    mgr = DatasetManager(cfg)
    mgr.process_annotated_images(modes=("monochro",))

    pool_good = tmp_path / "2_pool" / color / "monochro" / "good_pool"
    staging = tmp_path / "3_staging" / color / "monochro"
    assert sorted(os.listdir(pool_good)) == ["g1_0.png", "g1_1.png"]
    assert sorted(os.listdir(staging)) == ["d1_0.png", "d1_1.png"]


def test_split_pool_to_dataset_produces_expected_file_lists(tmp_path):
    from dataset import DatasetManager

    cfg = _make_cfg(tmp_path)
    color = cfg.common.target_color
    good_pool = tmp_path / "2_pool" / color / "color" / "good_pool"
    defect_pool = tmp_path / "2_pool" / color / "color" / "defect_pool"
    good_pool.mkdir(parents=True)
    defect_pool.mkdir(parents=True)
    for i in range(10):
        (good_pool / f"good_{i}_0.png").write_bytes(b"")
    for i in range(4):
        (defect_pool / f"defect_{i}_0.png").write_bytes(b"")

    mgr = DatasetManager(cfg)
    result = mgr.split_pool_to_dataset(color, mode="color")

    dataset_path = tmp_path / "4_dataset" / color / "color"
    train_good = sorted(os.listdir(dataset_path / "train" / "good"))
    test_good = sorted(os.listdir(dataset_path / "test" / "good" / "images"))
    train_defect = sorted(os.listdir(dataset_path / "train" / "defect"))
    test_defect = sorted(os.listdir(dataset_path / "test" / "defect" / "images"))

    # seed=42固定・train_ratio=0.7での実測値(既存コードを実行して記録した値)
    assert train_good == [
        "good_2_0.png", "good_3_0.png", "good_5_0.png",
        "good_6_0.png", "good_7_0.png", "good_8_0.png", "good_9_0.png",
    ]
    assert test_good == ["good_0_0.png", "good_1_0.png", "good_4_0.png"]
    assert train_defect == ["defect_1_0.png", "defect_2_0.png", "defect_3_0.png"]
    assert test_defect == ["defect_0_0.png"]
    assert result["defect_to_train"] == 3
    assert result["defect_to_test"] == 1
    assert result["good_to_train"] == 7
    assert result["good_to_test"] == 3


def test_backup_model_copies_model_dir(tmp_path):
    from dataset import DatasetManager

    cfg = _make_cfg(tmp_path)
    color = cfg.common.target_color
    model_mono = tmp_path / "6_model" / color / "monochro"
    model_mono.mkdir(parents=True)
    (model_mono / "para.json").write_text("{}")

    mgr = DatasetManager(cfg)
    mgr.backup_model()

    backup_root = tmp_path / "7_backup" / "model" / color
    timestamps = os.listdir(backup_root)
    assert len(timestamps) == 1
    copied = backup_root / timestamps[0] / "monochro" / "para.json"
    assert copied.is_file()
