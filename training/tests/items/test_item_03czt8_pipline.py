"""03CZT8専用pipline.pyの特性化テスト。

`items/item_03czt8/pipline.py` がコピー元(`pipline.py`)と同じオーケストレーション
ロジックを保ちつつ、03CZT8向けの`train_monochro`/`train_color`
（`train.item_03czt8`配下）を使うことを確認する。

実行: cd training && python -m pytest tests/items/test_item_03czt8_pipline.py -v
"""
import inspect

from omegaconf import OmegaConf

import train.item_03czt8.pipline as copied_pipline
import train.item_03czt8.train_color as item_train_color
import train.item_03czt8.train_monochro as item_train_monochro


def test_trainer_run_uses_item_03czt8_train_functions():
    """Trainer.run()のソースが train.item_03czt8 配下の train_monochro/train_color
    を参照している(既存 train.train_monochro/train.train_color ではない)ことを確認する。
    """
    source = inspect.getsource(copied_pipline.Trainer.run)
    assert "train_monochro(sub_cfg" in source
    assert "train_color(sub_cfg" in source
    # importが正しいモジュールから来ていることを確認
    assert copied_pipline.train_monochro is item_train_monochro.train_monochro
    assert copied_pipline.train_color is item_train_color.train_color


def test_build_sub_cfg_merges_common_and_mode():
    cfg = OmegaConf.create({
        "common": {"target_color": "053", "batch_size": 4},
        "monochro": {"image_size_height": 356, "image_size_width": 512},
        "color": {"image_size_height": 384, "image_size_width": 384},
    })
    sub = copied_pipline.build_sub_cfg(cfg, "monochro", gpu_id=0)
    assert sub.target_color == "053"
    assert sub.image_size_height == 356
    assert sub.mode == "monochro"


def test_conf_03czt8_yaml_loads_with_expected_output_paths():
    import os

    config_path = os.path.join(
        os.path.dirname(item_train_monochro.__file__), "conf_03czt8.yaml")
    cfg = OmegaConf.load(config_path)

    assert cfg.common.target_color == "053"
    assert cfg.common.target_item.size == "03"
    assert cfg.common.target_item.chain == "CZT8"
    # 出力パスが05CZT8等の既存パス(./6_model, ./3_pool等)と異なること(決定4)。
    assert cfg.common.model_dir == "./6_model_03czt8"
    assert cfg.common.pool_base == "./3_pool_03czt8"
    assert cfg.common.dataset_path == "./4_dataset_03czt8"
    assert cfg.common.splits_dir == "./5_splits_03czt8"
    assert cfg.common.backup_dir == "./backup_03czt8"
    # dataset_id が03CZT8向けであること。
    assert cfg.common.dataset_id_monochro == "03CZT8-monochro"
    assert cfg.common.dataset_id_color == "03CZT8-color"
    assert cfg.common.dataset_id_monochro_margin == "03CZT8-monochro"
    # リサイズサイズ(決定2)。
    assert cfg.monochro.image_size_height == 356
    assert cfg.monochro.image_size_width == 512
    assert cfg.color.image_size_height == 384
    assert cfg.color.image_size_width == 384
