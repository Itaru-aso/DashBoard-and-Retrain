"""ORM モデル `ColorMaster`（color data model）の integration テスト。round-trip・enum。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session


@pytest.mark.integration
def test_color_master_round_trip(db_session: Session) -> None:
    from src.models.color_master import ColorMaster

    row = ColorMaster(
        color_no="001",
        size="05",
        chain="CZT8",
        tape="",
        rgb_r=10,
        rgb_g=20,
        rgb_b=30,
        lab_l=Decimal("50.00"),
        lab_a=Decimal("1.00"),
        lab_b=Decimal("-2.00"),
    )
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)

    fetched = db_session.get(ColorMaster, row.id)
    assert fetched is not None
    assert fetched.color_no == "001"  # 文字列保持（ゼロ埋め）
    assert fetched.status == "未実施"  # 既定
    assert fetched.rgb_r == 10
    assert float(fetched.lab_l) == 50.0
    assert fetched.verification_at is None
    assert fetched.created_at is not None
