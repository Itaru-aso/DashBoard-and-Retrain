"""ORM モデル `EdgePc`（edge data model）の integration テスト。round-trip。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session


@pytest.mark.integration
def test_edge_pc_round_trip(db_session: Session) -> None:
    from src.models.edge_pc import EdgePc

    row = EdgePc(
        name="検査PC_1",
        host="169.254.93.171",
        username="ykk\\shisui",
        password="pw",
        model_port=2123,
    )
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)

    fetched = db_session.get(EdgePc, row.id)
    assert fetched is not None
    assert fetched.name == "検査PC_1"
    assert fetched.model_port == 2123
    assert fetched.enabled is True  # 既定
    assert fetched.last_ftp_ok is None
    assert fetched.created_at is not None
