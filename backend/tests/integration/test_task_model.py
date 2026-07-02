"""ORM モデル `Task`（task data model）の integration テスト。round-trip（enum・JSONB）。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session


@pytest.mark.integration
def test_task_round_trip(db_session: Session) -> None:
    from src.models.task import Task

    row = Task(
        color_no="501",
        size="05",
        chain="CZT8",
        tape="",
        task_type="ng_rate",
        detected_value=Decimal("6.00"),
        threshold_value=Decimal("5.00"),
        evaluation_date=date(2026, 7, 1),
        comments=[{"body": "初回検知", "created_at": "2026-07-01T00:00:00Z"}],
    )
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)

    fetched = db_session.get(Task, row.id)
    assert fetched is not None
    assert fetched.task_type == "ng_rate"
    assert fetched.status == "OPEN"  # 既定
    assert fetched.tape == ""
    assert fetched.comments[0]["body"] == "初回検知"
    assert float(fetched.detected_value) == 6.0
    assert fetched.created_at is not None
