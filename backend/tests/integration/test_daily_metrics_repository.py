"""daily_metrics Repository（A-R1/A-R6）の integration テスト。

- upsert_day: 対象日を delete→insert する冪等操作（同日2回で重複なし・消えたタプルは残らない）。
- read: 期間 / フルタプル / 号機フィルタ。
- read_unit_aggregated: 号機合算（unit を畳んで件数合算）。
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

D1 = date(2026, 7, 1)
D2 = date(2026, 7, 2)


def _row(unit: str, **counts: int):
    from src.repositories.daily_metrics_repository import DailyMetricRow

    base = dict(monochro_count=10, ng_count=1, fp_num=0, miss_num=0, annotated_count=5)
    base.update(counts)
    return DailyMetricRow(color_no="501", size="05", chain="CZT8", tape="", unit=unit, **base)


@pytest.mark.integration
def test_upsert_day_is_idempotent(db_session: Session) -> None:
    """同日2回の upsert で重複せず、消えたタプルも残らない（delete→insert）。"""
    from src.repositories.daily_metrics_repository import DailyMetricsRepository

    repo = DailyMetricsRepository(db_session)
    repo.upsert_day(D1, [_row("1", monochro_count=10), _row("2", monochro_count=5)])
    assert len(repo.read(D1, D1)) == 2

    # unit=2 を除いた再集計 → unit=1 のみ・unit=2 は残らない
    repo.upsert_day(D1, [_row("1", monochro_count=12)])
    rows = repo.read(D1, D1)
    assert len(rows) == 1
    assert rows[0].unit == "1"
    assert rows[0].monochro_count == 12


@pytest.mark.integration
def test_read_filters_by_period_tuple_unit(db_session: Session) -> None:
    """期間・フルタプル・号機でフィルタできる。"""
    from src.repositories.daily_metrics_repository import (
        DailyMetricRow,
        DailyMetricsRepository,
    )

    repo = DailyMetricsRepository(db_session)
    other = DailyMetricRow(
        color_no="777",
        size="10",
        chain="CZ",
        tape="TAPE",
        unit="1",
        monochro_count=3,
        ng_count=0,
        fp_num=0,
        miss_num=0,
        annotated_count=0,
    )
    repo.upsert_day(D1, [_row("1"), _row("2"), other])
    repo.upsert_day(D2, [_row("1")])

    assert len(repo.read(D1, D2)) == 4
    assert len(repo.read(D1, D1)) == 3

    tuple_rows = repo.read(D1, D2, color_no="501", size="05", chain="CZT8", tape="")
    assert len(tuple_rows) == 3
    assert all(r.color_no == "501" for r in tuple_rows)

    unit_rows = repo.read(D1, D1, unit_ids=["1"])
    assert {r.unit for r in unit_rows} == {"1"}


@pytest.mark.integration
def test_read_unit_aggregated_sums_over_units(db_session: Session) -> None:
    """号機合算: 同日・同タプルで unit を畳んで件数を合算する。"""
    from src.repositories.daily_metrics_repository import DailyMetricsRepository

    repo = DailyMetricsRepository(db_session)
    repo.upsert_day(
        D1,
        [
            _row("1", monochro_count=10, ng_count=2, fp_num=1, miss_num=1, annotated_count=5),
            _row("2", monochro_count=6, ng_count=1, fp_num=0, miss_num=1, annotated_count=3),
        ],
    )

    agg = repo.read_unit_aggregated(D1, D1, color_no="501", size="05", chain="CZT8", tape="")
    assert len(agg) == 1
    a = agg[0]
    assert a.jst_date == D1
    assert a.monochro_count == 16
    assert a.ng_count == 3
    assert a.fp_num == 1
    assert a.miss_num == 2
    assert a.annotated_count == 8
