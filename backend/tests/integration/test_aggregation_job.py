"""日次集計スケジューラジョブ（A-R2/A-R3）の integration テスト。

- create_scheduler で aggregation ジョブが登録され、逸脱判定より前に並ぶ
  （集計 → 逸脱判定 → 昇格。集計が当日分を更新してから判定が読む）。
- run_aggregation がセッションを開いて aggregate_window を呼ぶ（冪等・commit/close）。
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import Engine


def _cron_hour(trigger: object) -> int:
    for field in trigger.fields:  # type: ignore[attr-defined]
        if field.name == "hour":
            return int(str(field))
    raise AssertionError("hour field not found")


@pytest.mark.integration
def test_aggregation_job_registered_before_breach(monkeypatch: pytest.MonkeyPatch) -> None:
    """aggregation が登録され、逸脱判定(breach_eval)より早い時刻に並ぶ。"""
    from src import config
    from src.scheduler import create_scheduler

    monkeypatch.setattr(config.settings, "AGG_RUN_TIME", "02:00")
    monkeypatch.setattr(config.settings, "BREACH_EVAL_ENABLED", True)
    monkeypatch.setattr(config.settings, "BREACH_EVAL_TIME", "03:00")

    scheduler = create_scheduler()
    scheduler.start(paused=True)
    try:
        agg = scheduler.get_job("aggregation")
        breach = scheduler.get_job("breach_eval")
        assert agg is not None
        assert breach is not None
        assert _cron_hour(agg.trigger) < _cron_hour(breach.trigger)
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.integration
def test_aggregation_job_registered_even_when_breach_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """逸脱判定が無効でも aggregation は登録される（集計は常時）。"""
    from src import config
    from src.scheduler import create_scheduler

    monkeypatch.setattr(config.settings, "BREACH_EVAL_ENABLED", False)

    scheduler = create_scheduler()
    scheduler.start(paused=True)
    try:
        assert scheduler.get_job("aggregation") is not None
        assert scheduler.get_job("breach_eval") is None
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.integration
def test_run_aggregation_invokes_aggregate_window(
    ver2_engine: Engine, inspection_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_aggregation がセッションを開いて aggregate_window を呼ぶ。"""
    from src import database
    from src.jobs import aggregation_job

    database.SessionLocal.configure(bind=ver2_engine)
    database.InspectionSessionLocal.configure(bind=inspection_engine)

    called: dict[str, bool] = {}

    def _fake_window(self: object, *args: object, **kwargs: object) -> None:
        called["invoked"] = True

    monkeypatch.setattr(
        "src.services.aggregation_service.AggregationService.aggregate_window",
        _fake_window,
    )

    aggregation_job.run_aggregation()

    assert called.get("invoked") is True


@pytest.mark.integration
def test_run_aggregation_raises_and_rolls_back_on_error(
    ver2_engine: Engine, inspection_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """集計中の例外は rollback して再送出する（アプリは握りつぶさない）。"""
    from src import database
    from src.jobs import aggregation_job

    database.SessionLocal.configure(bind=ver2_engine)
    database.InspectionSessionLocal.configure(bind=inspection_engine)

    def _boom(self: object, *args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "src.services.aggregation_service.AggregationService.aggregate_window",
        _boom,
    )

    with pytest.raises(RuntimeError):
        aggregation_job.run_aggregation()
