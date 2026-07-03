"""現行配信モデル `deployed_model` の ORM モデル（retraining M-R8.3）。

migration `0007_create_retraining` と一致。
- 色（フルタプル）ごとに、いま検査PCへ配信されている現行モデルを1件保持する（フルタプル ユニーク・案A）。
- 配信（FTP）は `deployment_service` が担い、結果（全台成功/一部失敗/全失敗）を `deploy_status` に記録する。
  FTP 失敗時もジョブ自体は COMPLETED のまま、本レコードを FAILED/PARTIAL として再配信可能にする。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class DeployStatus(str, enum.Enum):
    """配信結果。"""

    SUCCESS = "SUCCESS"  # 全有効エッジPCへ配信成功
    PARTIAL = "PARTIAL"  # 一部のエッジPCで失敗（再配信可）
    FAILED = "FAILED"  # 全て失敗（再配信可）


class DeployedModel(Base):
    """色（フルタプル）ごとの現行配信モデル。"""

    __tablename__ = "deployed_model"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 対象色（フルタプル・ユニーク）。
    color_no: Mapped[str] = mapped_column(String(50))
    size: Mapped[str] = mapped_column(String(50), server_default="")
    chain: Mapped[str] = mapped_column(String(50), server_default="")
    tape: Mapped[str] = mapped_column(String(100), server_default="")

    # 由来ジョブ。
    job_id: Mapped[int] = mapped_column(ForeignKey("retraining_job.id", ondelete="RESTRICT"))

    # 配信した成果物（monochro / color）。
    onnx_monochro_path: Mapped[str | None] = mapped_column(String(1024), default=None)
    onnx_color_path: Mapped[str | None] = mapped_column(String(1024), default=None)

    deploy_status: Mapped[str] = mapped_column(
        String(20), server_default=DeployStatus.SUCCESS.value
    )
    # 全台ぶんの配信結果詳細（任意・エッジPC名→成否/メッセージの JSON）。
    deploy_detail: Mapped[str | None] = mapped_column(Text, default=None)

    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("color_no", "size", "chain", "tape", name="uq_deployed_model_tuple"),
        CheckConstraint(
            "deploy_status IN ('SUCCESS','PARTIAL','FAILED')",
            name="ck_deployed_model_status",
        ),
    )
