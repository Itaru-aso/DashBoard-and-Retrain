"""ORM モデル `DailyMetrics`（A-R1）の integration テスト。

ver2 テスト DB（migration 0002 適用済み）へ round-trip できることを確認する。
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session


@pytest.mark.integration
def test_daily_metrics_round_trip(db_session: Session) -> None:
    """DailyMetrics を保存して読み戻せる（tape は空文字も保持）。"""
    from src.models.daily_metrics import DailyMetrics

    row = DailyMetrics(
        jst_date=date(2026, 7, 1),
        color_no="501",
        size="05",
        chain="CZT8",
        tape="",
        unit="1",
        monochro_count=10,
        ng_count=1,
        fp_num=0,
        miss_num=0,
        annotated_count=5,
    )
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)

    fetched = db_session.get(DailyMetrics, row.id)
    assert fetched is not None
    assert fetched.jst_date == date(2026, 7, 1)
    assert fetched.color_no == "501"
    assert fetched.tape == ""
    assert fetched.unit == "1"
    assert fetched.monochro_count == 10
    assert fetched.annotated_count == 5
    assert fetched.computed_at is not None
