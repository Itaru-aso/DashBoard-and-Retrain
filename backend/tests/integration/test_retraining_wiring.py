"""再学習の配線（retraining task10）テスト。

- config に training_dir/model_dir/python の設定がある。
- main._init_retraining_services が training/deployment シングルトンを生成し、
  COMPLETED 自動配信フックを配線する。
- training_service.start の復旧処理は DB エラーに耐える（起動をクラッシュさせない）。
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_training_settings_present() -> None:
    from src.config import settings

    assert hasattr(settings, "TRAINING_DIR")
    assert hasattr(settings, "TRAINING_MODEL_DIR")
    assert settings.TRAINING_PYTHON  # 既定は "python"


@pytest.mark.integration
def test_init_retraining_services_wires_singletons() -> None:
    from src import main
    from src.services import deployment_service as ds
    from src.services import training_service as ts

    svc = main._init_retraining_services()

    assert ts.get_training_service() is svc
    assert ds.get_deployment_service() is not None
    # COMPLETED 時の自動配信フックが配線されている（v1）。
    assert svc._on_completed is not None


@pytest.mark.integration
def test_recover_on_start_is_resilient_to_db_errors() -> None:
    from src.services.training_service import TrainingConfig, TrainingService

    def bad_factory():
        raise OSError("db down")

    svc = TrainingService(bad_factory, TrainingConfig(training_dir="x", model_dir="y"))
    # 復旧処理は DB エラーを握りつぶし、例外を伝播しない。
    svc._recover_on_start()
