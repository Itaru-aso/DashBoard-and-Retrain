"""現状の pipline.DatasetManager の挙動を固定するテスト。

Seam6移行(datasetパッケージへの切り出し)前の挙動を記録し、
Task1で移動する dataset.DatasetManager が同じ結果を出すことの比較対象とする。

`process_annotated_images` (1_download 経由) の挙動は export_root 移行
(dataset-export-root-migration.md v1.4) により置き換えられたため、対応する
特性テストは `test_manager_export_root.py` に移動した。

実行: cd training && python -m pytest tests/dataset/test_manager_characterization.py -v
"""
import os

from omegaconf import OmegaConf


def _make_cfg(tmp_path, target_color="841"):
    return OmegaConf.create({
        "common": {
            "target_color": target_color,
            "pool_base": str(tmp_path / "2_pool"),
            "dataset_path": str(tmp_path / "4_dataset"),
            "model_dir": str(tmp_path / "6_model"),
            "backup_dir": str(tmp_path / "7_backup"),
        },
        "color": {
            "image_size_height": 32,
            "image_size_width": 32,
            "pool_train_ratio": 0.7,
        },
        "monochro": {
            "image_size_height": 32,
            "image_size_width": 32,
            "pool_train_ratio": 0.7,
        },
    })


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
