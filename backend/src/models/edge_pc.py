"""エッジPC `edge_pc` の ORM モデル（edge data model）。

migration `0006_create_edge_pc` と一致。ONNX 配信先（検査PC）の接続情報。
配信は有効な全台（find_enabled）へ・ポートは model_port。パスワードは平文（任意）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class EdgePc(Base):
    """エッジPC（ver2 DB・Alembic 管理）。"""

    __tablename__ = "edge_pc"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str]
    host: Mapped[str]
    username: Mapped[str | None] = mapped_column(default=None)
    password: Mapped[str | None] = mapped_column(default=None)
    model_port: Mapped[int | None] = mapped_column(Integer, default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")

    last_ftp_ok: Mapped[bool | None] = mapped_column(Boolean, default=None)
    last_ftp_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
