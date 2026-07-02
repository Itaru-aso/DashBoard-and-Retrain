"""閾値テーブル `threshold` の ORM モデル（data model）。

migration `0003_create_threshold` と列・制約を一致させる。metric / scope は許可値のみ
（DB 側 CHECK と Pydantic で担保）、時刻は timestamptz（半開区間 [valid_from, valid_to)）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class Threshold(Base):
    """有効閾値（ver2 DB・Alembic 管理）。per_color は色4項目必須・global は NULL。"""

    __tablename__ = "threshold"

    id: Mapped[int] = mapped_column(primary_key=True)

    metric: Mapped[str]  # ng_rate / false_alarm_rate / miss_rate
    scope: Mapped[str]  # global / per_color

    # フルタプル（per_color 時のみ設定。tape は空文字も許容）
    color_no: Mapped[str | None] = mapped_column(default=None)
    size: Mapped[str | None] = mapped_column(default=None)
    chain: Mapped[str | None] = mapped_column(default=None)
    tape: Mapped[str | None] = mapped_column(default=None)

    value_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
