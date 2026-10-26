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

    # 分割はハッシュ方式（pool-dataset-sync-split.md 決定1）に変わったため、旧方式の実測リストは固定しない。
    # cfg の pool/dataset パスが配線され、全画像がちょうど1回置かれ、報告件数と一致することを見る。
    assert sorted(train_good + test_good) == sorted(os.listdir(good_pool))
    assert sorted(train_defect + test_defect) == sorted(os.listdir(defect_pool))
    assert result["good_to_train"] == len(train_good)
    assert result["good_to_test"] == len(test_good)
    assert result["defect_to_train"] == len(train_defect)
    assert result["defect_to_test"] == len(test_defect)


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
