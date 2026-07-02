"""色マスター `color_master` の ORM モデル（color data model）。

migration `0005_create_color_master` と一致。同一性タプル＋色見本(RGB/Lab)＋
ライフサイクル status（自動管理・未実施 → 量産検証 → 実生産）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class ColorMaster(Base):
    """色マスター（ver2 DB・Alembic 管理）。"""

    __tablename__ = "color_master"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 同一性タプル（文字列保持・ゼロ埋め維持）
    color_no: Mapped[str]
    size: Mapped[str]
    chain: Mapped[str]
    tape: Mapped[str]

    # 色見本（1色1基準値・列保持）
    rgb_r: Mapped[int | None] = mapped_column(Integer, default=None)
    rgb_g: Mapped[int | None] = mapped_column(Integer, default=None)
    rgb_b: Mapped[int | None] = mapped_column(Integer, default=None)
    lab_l: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), default=None)
    lab_a: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), default=None)
    lab_b: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), default=None)

    status: Mapped[str] = mapped_column(server_default="未実施")

    verification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    production_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
