"""日次集計テーブル `daily_metrics` の ORM モデル（A-R1）。

migration `0002_create_daily_metrics` と列・制約を一致させる。JST日 × フルタプル ×
号機の件数を保持する（率は `services/metrics.py` で算出。件数は保持しない率を含めない）。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class DailyMetrics(Base):
    """JST日 × フルタプル × 号機の集計件数（ver2 DB・Alembic 管理）。"""

    __tablename__ = "daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "jst_date",
            "color_no",
            "size",
            "chain",
            "tape",
            "unit",
            name="uq_daily_metrics_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # フルタプル × 号機 × JST日（識別子。tape は空文字も保持）
    jst_date: Mapped[date]
    color_no: Mapped[str]
    size: Mapped[str]
    chain: Mapped[str]
    tape: Mapped[str]
    unit: Mapped[str]

    # 件数（分子=全カメラ／分母=monochro）
    monochro_count: Mapped[int]
    ng_count: Mapped[int]
    fp_num: Mapped[int]
    miss_num: Mapped[int]
    annotated_count: Mapped[int]

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
