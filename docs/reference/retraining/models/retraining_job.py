"""モデル再学習ジョブ（ver2 DB）。

`schema-spec-mapping.md` / `retraining-design.md` 準拠。
- 同一性はフルタプル（color_no/size/chain/tape）で保持する（学習起動時は color_no のみを `training/` へ渡す）。
- 状態は QUEUED → RUNNING → COMPLETED/FAILED/CANCELLED（前進のみ）。DB を正として都度永続する。
- 成果物（ONNX）は完了時にローカル所定パスを記録する（成功判定は ONNX 生成有無＋完了マーカー）。

注: `Base` は ver2 用 declarative_base（`database.py` で定義）を想定。プロジェクトの import レイアウトに合わせて調整する。
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base  # ver2 用 Base（プロジェクトのレイアウトに合わせて調整）


class JobStatus(str, enum.Enum):
    """再学習ジョブの状態（前進のみ）。"""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# 終端状態（これ以降は遷移しない）
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}
)

_STATUS_VALUES = tuple(s.value for s in JobStatus)


class RetrainingJob(Base):
    """再学習ジョブ（履歴・実行状態）。1ジョブ＝monochro/color の1対を学習する。"""

    __tablename__ = "retraining_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 対象色（フルタプル）。tape は空文字も値として保持（基本空白だがキーの一部）。
    color_no: Mapped[str] = mapped_column(String(50), nullable=False)
    size: Mapped[str] = mapped_column(String(50), nullable=False)
    chain: Mapped[str] = mapped_column(String(50), nullable=False)
    tape: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.QUEUED.value,
        server_default=JobStatus.QUEUED.value,
    )

    # 実行時刻
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 結果・エラー
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 成果物（完了時に記録。mode 文字列は monochro / color）
    onnx_monochro_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    onnx_color_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # 起票者（作業者手動起票。任意）
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_retraining_job_status",
        ),
        # 履歴の絞り込み（色×時刻）に効く索引
        Index("ix_retraining_job_tuple", "color_no", "size", "chain", "tape"),
        Index("ix_retraining_job_status", "status"),
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<RetrainingJob id={self.id} "
            f"tuple=({self.color_no},{self.size},{self.chain},{self.tape}) "
            f"status={self.status}>"
        )
