"""モデル再学習ジョブ `retraining_job` の ORM モデル（retraining M-R7）。

migration `0007_create_retraining` と一致。
- 同一性はフルタプル（color_no/size/chain/tape）で保持する（学習起動時は color_no のみを `training/` へ渡す）。
- 状態は QUEUED → RUNNING → COMPLETED/FAILED/CANCELLED（前進のみ）。DB を正として都度永続する。
- 成果物（ONNX）は完了時にローカル所定パスを記録する（成功判定は ONNX 生成有無＋完了マーカー）。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class JobStatus(str, enum.Enum):
    """再学習ジョブの状態（前進のみ）。"""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# 終端状態（これ以降は遷移しない）。
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}
)


class RetrainingJob(Base):
    """再学習ジョブ（履歴・実行状態）。1ジョブ＝monochro/color の1対を学習する。"""

    __tablename__ = "retraining_job"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 対象色（フルタプル）。tape は空文字も値として保持（基本空白だがキーの一部）。
    color_no: Mapped[str] = mapped_column(String(50))
    size: Mapped[str] = mapped_column(String(50), server_default="")
    chain: Mapped[str] = mapped_column(String(50), server_default="")
    tape: Mapped[str] = mapped_column(String(100), server_default="")

    status: Mapped[str] = mapped_column(String(20), server_default=JobStatus.QUEUED.value)

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    # 成果物（完了時に記録。mode 文字列は monochro / color）。
    onnx_monochro_path: Mapped[str | None] = mapped_column(String(1024), default=None)
    onnx_color_path: Mapped[str | None] = mapped_column(String(1024), default=None)

    # 起票者（作業者手動起票・任意）。
    created_by: Mapped[str | None] = mapped_column(String(100), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_retraining_job_status",
        ),
        Index("ix_retraining_job_tuple", "color_no", "size", "chain", "tape"),
        Index("ix_retraining_job_status", "status"),
    )

    @property
    def is_terminal(self) -> bool:
        """終端状態（COMPLETED/FAILED/CANCELLED）なら True。"""
        return self.status in TERMINAL_STATUSES
