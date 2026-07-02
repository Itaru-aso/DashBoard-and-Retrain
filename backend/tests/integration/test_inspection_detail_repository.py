"""明細 Repository（dashboard R4.2）の integration テスト。

app_db 代役の `annotation.image_base` をキーセット（カーソル (inspect_timestamp, image_id)）で
読み、期間・フルタプル・号機フィルタ、next_cursor、安定順序を検証する。
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session


def _insert(
    session: Session,
    image_id: int,
    ts: datetime,
    unit: str = "1",
    color: str = "501",
) -> None:
    session.execute(
        text(
            "INSERT INTO annotation.image_base "
            "(image_id, inspect_timestamp, unit, camera_model, judgment_result, extra_info) "
            "VALUES (:id, :ts, :unit, 'camera1_image', 0, CAST(:extra AS jsonb))"
        ),
        {
            "id": image_id,
            "ts": ts,
            "unit": unit,
            "extra": json.dumps({"colorNo": color, "size": "05", "chain": "CZT8", "tape": ""}),
        },
    )


@pytest.fixture
def _seeded(inspection_session: Session) -> Session:
    # 同日内に image_id 昇順、翌日も1件
    _insert(inspection_session, 1, datetime(2026, 7, 1, 10, 0, 0), unit="1", color="501")
    _insert(inspection_session, 2, datetime(2026, 7, 1, 11, 0, 0), unit="2", color="501")
    _insert(inspection_session, 3, datetime(2026, 7, 1, 12, 0, 0), unit="1", color="777")
    _insert(inspection_session, 4, datetime(2026, 7, 2, 9, 0, 0), unit="1", color="501")
    inspection_session.flush()
    return inspection_session


@pytest.mark.integration
def test_read_details_period_and_order(_seeded: Session) -> None:
    from src.repositories.inspection_detail_repository import InspectionDetailRepository

    repo = InspectionDetailRepository(_seeded)
    page = repo.read_details(datetime(2026, 7, 1), datetime(2026, 7, 3), limit=50)
    assert [r.image_id for r in page.rows] == [1, 2, 3, 4]  # (ts, image_id) 昇順
    assert page.next_cursor is None


@pytest.mark.integration
def test_read_details_keyset_pagination(_seeded: Session) -> None:
    from src.repositories.inspection_detail_repository import InspectionDetailRepository

    repo = InspectionDetailRepository(_seeded)
    first = repo.read_details(datetime(2026, 7, 1), datetime(2026, 7, 3), limit=2)
    assert [r.image_id for r in first.rows] == [1, 2]
    assert first.next_cursor is not None

    second = repo.read_details(
        datetime(2026, 7, 1), datetime(2026, 7, 3), limit=2, cursor=first.next_cursor
    )
    assert [r.image_id for r in second.rows] == [3, 4]
    assert second.next_cursor is None


@pytest.mark.integration
def test_read_details_filters_unit_and_color(_seeded: Session) -> None:
    from src.repositories.inspection_detail_repository import InspectionDetailRepository

    repo = InspectionDetailRepository(_seeded)
    by_unit = repo.read_details(
        datetime(2026, 7, 1), datetime(2026, 7, 3), unit_ids=["1"], limit=50
    )
    assert [r.image_id for r in by_unit.rows] == [1, 3, 4]

    by_color = repo.read_details(
        datetime(2026, 7, 1),
        datetime(2026, 7, 3),
        color_no="777",
        size="05",
        chain="CZT8",
        tape="",
        limit=50,
    )
    assert [r.image_id for r in by_color.rows] == [3]
    assert by_color.rows[0].color_no == "777"
