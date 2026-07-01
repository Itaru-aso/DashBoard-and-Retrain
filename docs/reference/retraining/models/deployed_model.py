"""現行配信モデル（ver2 DB）。

色（フルタプル）ごとに、いま検査PCへ配信されている現行モデルを1件保持する（M-R8.3）。
- フルタプル単位でユニーク（案A）。upsert で最新の配信に置き換える。
- 配信（FTP）は `deployment_service` が担い、結果（全台成功/一部失敗）を `deploy_status` に記録する。
  FTP 失敗時もジョブ自体は COMPLETED のまま、本レコードを `FAILED`/`PARTIAL` として再配信可能にする。

注: `Base` は ver2 用 declarative_base（`database.py`）を想定。
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class DeployStatus(str, enum.Enum):
    """配信結果。"""

    SUCCESS = "SUCCESS"   # 全有効エッジPCへ配信成功
    PARTIAL = "PARTIAL"   # 一部のエッジPCで失敗（再配信可）
    FAILED = "FAILED"     # 全て失敗（再配信可）


_DEPLOY_STATUS_VALUES = tuple(s.value for s in DeployStatus)


class DeployedModel(Base):
    """色（フルタプル）ごとの現行配信モデル。"""

    __tablename__ = "deployed_model"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 対象色（フルタプル・ユニーク）
    color_no: Mapped[str] = mapped_column(String(50), nullable=False)
    size: Mapped[str] = mapped_column(String(50), nullable=False)
    chain: Mapped[str] = mapped_column(String(50), nullable=False)
    tape: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")

    # 由来ジョブ
    job_id: Mapped[int] = mapped_column(
        ForeignKey("retraining_job.id", ondelete="RESTRICT"), nullable=False
    )

    # 配信した成果物（monochro / color）
    onnx_monochro_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    onnx_color_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # 配信結果
    deploy_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DeployStatus.SUCCESS.value,
        server_default=DeployStatus.SUCCESS.value,
    )
    # 全台ぶんの配信結果詳細（任意・エッジPC名→成否/メッセージの JSON）
    deploy_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "color_no", "size", "chain", "tape", name="uq_deployed_model_tuple"
        ),
        CheckConstraint(
            "deploy_status IN ('SUCCESS','PARTIAL','FAILED')",
            name="ck_deployed_model_status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<DeployedModel tuple=({self.color_no},{self.size},{self.chain},{self.tape}) "
            f"job_id={self.job_id} status={self.deploy_status}>"
        )
