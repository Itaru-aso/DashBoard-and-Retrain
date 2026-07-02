"""ダッシュボード Service（dashboard R2, R3, R5）の integration テスト。

- get_trends: daily_metrics を読み metrics.py で率算出（KPI=NULL / monochro=0 除外）。
- get_threshold_overlay: 範囲内の各日で ThresholdService.resolve_effective を解決し
  日次系列（階段・欠損）。フルタプル未指定時は重ね描きしない。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

D1 = date(2026, 7, 1)
D2 = date(2026, 7, 2)
D3 = date(2026, 7, 3)
COLOR = ("501", "05", "CZT8", "")


def _row(**over: object):
    from src.repositories.daily_metrics_repository import DailyMetricRow

    base: dict[str, object] = {
        "color_no": "501",
        "size": "05",
        "chain": "CZT8",
        "tape": "",
        "unit": "1",
        "monochro_count": 10,
        "ng_count": 2,
        "fp_num": 1,
        "miss_num": 1,
        "annotated_count": 5,
    }
    base.update(over)
    return DailyMetricRow(**base)


def _svc(db_session: Session) -> object:
    from src.services.dashboard_service import DashboardService

    return DashboardService(db_session)


@pytest.mark.integration
def test_trends_computes_rates(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository

    DailyMetricsRepository(db_session).upsert_day(D1, [_row()])
    points = _svc(db_session).get_trends(D1, D3, *COLOR)  # type: ignore[attr-defined]

    assert len(points) == 1
    p = points[0]
    assert p.jst_date == D1
    assert p.throughput == 10
    assert p.ng_rate == pytest.approx(0.2)
    assert p.false_alarm_rate == pytest.approx(0.1)
    assert p.miss_rate == pytest.approx(0.1)


@pytest.mark.integration
def test_trends_kpi_null_when_no_annotation(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository

    DailyMetricsRepository(db_session).upsert_day(
        D1, [_row(annotated_count=0, fp_num=0, miss_num=0)]
    )
    points = _svc(db_session).get_trends(D1, D3, *COLOR)  # type: ignore[attr-defined]
    assert points[0].false_alarm_rate is None
    assert points[0].miss_rate is None
    assert points[0].ng_rate == pytest.approx(0.2)


@pytest.mark.integration
def test_trends_excludes_monochro_zero(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository

    DailyMetricsRepository(db_session).upsert_day(
        D1, [_row(monochro_count=0, ng_count=0, fp_num=0, miss_num=0, annotated_count=0)]
    )
    points = _svc(db_session).get_trends(D1, D3, *COLOR)  # type: ignore[attr-defined]
    assert points == []


@pytest.mark.integration
def test_threshold_overlay_step_and_gap(db_session: Session) -> None:
    from src.schemas.threshold import ThresholdCreate
    from src.services.threshold_service import ThresholdService

    # global 閾値: D1 は 5.0、D2 以降は 8.0（supersede で階段）。D3 は無し→欠損。
    ts = ThresholdService(db_session)
    created = ts.create(
        ThresholdCreate(
            metric="ng_rate",
            scope="global",
            value_pct=5.0,
            valid_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
            valid_to=datetime(2026, 7, 2, tzinfo=timezone.utc),
        )
    )
    # D2 のみ有効な閾値
    ts.create(
        ThresholdCreate(
            metric="ng_rate",
            scope="global",
            value_pct=8.0,
            valid_from=datetime(2026, 7, 2, tzinfo=timezone.utc),
            valid_to=datetime(2026, 7, 3, tzinfo=timezone.utc),
        )
    )
    assert created.id > 0

    overlay = _svc(db_session).get_threshold_overlay(  # type: ignore[attr-defined]
        "ng_rate", *COLOR, D1, D3
    )
    by_day = {p.jst_date: p.value_pct for p in overlay}
    assert by_day[D1] == pytest.approx(5.0)
    assert by_day[D2] == pytest.approx(8.0)
    assert D3 not in by_day  # 欠損


@pytest.mark.integration
def test_overlay_requires_full_tuple(db_session: Session) -> None:
    overlay = _svc(db_session).get_threshold_overlay(  # type: ignore[attr-defined]
        "ng_rate", None, None, None, None, D1, D3
    )
    assert overlay == []
