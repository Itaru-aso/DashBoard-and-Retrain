"""保守タスク `task` の ORM モデル（task data model）。

migration `0004_create_task` と一致。`comments` は JSONB 配列（追記型・記入者なし＝匿名）。
状態は OPEN → IN_PROGRESS → DONE の前進のみ（遷移制御は Service）。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class Task(Base):
    """逸脱検知で自動起票される保守タスク（ver2 DB・Alembic 管理）。"""

    __tablename__ = "task"

    id: Mapped[int] = mapped_column(primary_key=True)

    color_no: Mapped[str]
    size: Mapped[str]
    chain: Mapped[str]
    tape: Mapped[str]

    task_type: Mapped[str]  # ng_rate / false_alarm_rate / miss_rate
    status: Mapped[str] = mapped_column(server_default="OPEN")

    detected_value: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=None)
    threshold_value: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=None)
    evaluation_date: Mapped[date | None] = mapped_column(Date, default=None)

    comments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
