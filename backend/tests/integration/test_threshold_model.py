"""ORM モデル `Threshold`（data model）の integration テスト。

ver2 テスト DB（migration 0003 適用済み）へ round-trip できることを確認する。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session


@pytest.mark.integration
def test_threshold_round_trip(db_session: Session) -> None:
    """per_color の Threshold を保存して読み戻せる（enum・timestamptz の往復）。"""
    from src.models.threshold import Threshold

    row = Threshold(
        metric="ng_rate",
        scope="per_color",
        color_no="501",
        size="05",
        chain="CZT8",
        tape="",
        value_pct=5.0,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_to=None,
    )
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)

    fetched = db_session.get(Threshold, row.id)
    assert fetched is not None
    assert fetched.metric == "ng_rate"
    assert fetched.scope == "per_color"
    assert fetched.color_no == "501"
    assert fetched.tape == ""
    assert float(fetched.value_pct) == 5.0
    assert fetched.valid_from == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert fetched.valid_to is None
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


@pytest.mark.integration
def test_threshold_global_round_trip(db_session: Session) -> None:
    """global の Threshold は色カラムが NULL で保存できる。"""
    from src.models.threshold import Threshold

    row = Threshold(
        metric="miss_rate",
        scope="global",
        value_pct=10.0,
        valid_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    db_session.add(row)
    db_session.flush()

    fetched = db_session.get(Threshold, row.id)
    assert fetched is not None
    assert fetched.scope == "global"
    assert fetched.color_no is None
    assert fetched.size is None
