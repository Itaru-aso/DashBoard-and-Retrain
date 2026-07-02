"""逸脱評価 Service（task R1, R2）の integration テスト（ver2 単一 DB）。

- 閾値駆動で `値 > 閾値` の単位に起票／閾値なしは判定しない／KPI NULL はスキップ／
  再実行で冪等／閾値内に戻っても自動クローズしない。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

D1 = date(2026, 7, 1)
D2 = date(2026, 7, 2)
COLOR = dict(color_no="501", size="05", chain="CZT8", tape="")


def _metric_row(day_repo: object, day: date, **over: object) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricRow

    base: dict[str, object] = {
        **COLOR,
        "unit": "1",
        "monochro_count": 10,
        "ng_count": 2,
        "fp_num": 0,
        "miss_num": 0,
        "annotated_count": 5,
    }
    base.update(over)
    day_repo.upsert_day(day, [DailyMetricRow(**base)])  # type: ignore[attr-defined]


def _threshold(db: Session, metric: str, value_pct: float) -> None:
    from src.schemas.threshold import ThresholdCreate
    from src.services.threshold_service import ThresholdService

    ThresholdService(db).create(
        ThresholdCreate(
            metric=metric,
            scope="per_color",
            **COLOR,
            value_pct=value_pct,
            valid_from=datetime(2026, 6, 1, tzinfo=timezone.utc),
            valid_to=None,
        )
    )


@pytest.mark.integration
def test_breach_creates_task(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.repositories.task_repository import TaskRepository
    from src.services.breach_evaluation_service import BreachEvaluationService

    _metric_row(DailyMetricsRepository(db_session), D1)  # ng_rate = 2/10 = 20%
    _threshold(db_session, "ng_rate", 5.0)

    BreachEvaluationService(db_session).evaluate(window_days=1, end_date=D1)

    tasks = TaskRepository(db_session).list()
    assert len(tasks) == 1
    assert tasks[0].task_type == "ng_rate"
    assert float(tasks[0].detected_value) == pytest.approx(20.0)
    assert float(tasks[0].threshold_value) == pytest.approx(5.0)


@pytest.mark.integration
def test_no_threshold_no_task(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.repositories.task_repository import TaskRepository
    from src.services.breach_evaluation_service import BreachEvaluationService

    _metric_row(DailyMetricsRepository(db_session), D1)  # 閾値なし
    BreachEvaluationService(db_session).evaluate(window_days=1, end_date=D1)
    assert TaskRepository(db_session).list() == []


@pytest.mark.integration
def test_kpi_null_skipped(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.repositories.task_repository import TaskRepository
    from src.services.breach_evaluation_service import BreachEvaluationService

    # annotated=0 → false_alarm_rate は NULL
    _metric_row(DailyMetricsRepository(db_session), D1, annotated_count=0, fp_num=0)
    _threshold(db_session, "false_alarm_rate", 1.0)
    BreachEvaluationService(db_session).evaluate(window_days=1, end_date=D1)
    # false_alarm_rate は NULL でスキップ → 起票なし
    assert [t for t in TaskRepository(db_session).list() if t.task_type == "false_alarm_rate"] == []


@pytest.mark.integration
def test_idempotent(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.repositories.task_repository import TaskRepository
    from src.services.breach_evaluation_service import BreachEvaluationService

    _metric_row(DailyMetricsRepository(db_session), D1)
    _threshold(db_session, "ng_rate", 5.0)
    svc = BreachEvaluationService(db_session)
    svc.evaluate(window_days=1, end_date=D1)
    svc.evaluate(window_days=1, end_date=D1)  # 再実行
    assert len(TaskRepository(db_session).list()) == 1


@pytest.mark.integration
def test_no_auto_close(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.repositories.task_repository import TaskRepository
    from src.services.breach_evaluation_service import BreachEvaluationService

    repo = DailyMetricsRepository(db_session)
    _metric_row(repo, D1, ng_count=2)  # D1: 20% > 5% 逸脱
    _metric_row(repo, D2, ng_count=0)  # D2: 0% ≤ 5% 閾値内
    _threshold(db_session, "ng_rate", 5.0)

    BreachEvaluationService(db_session).evaluate(window_days=2, end_date=D2)

    tasks = TaskRepository(db_session).list()
    assert len(tasks) == 1
    assert tasks[0].status == "OPEN"  # 閾値内に戻っても自動クローズしない
