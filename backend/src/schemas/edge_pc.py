"""エッジPC API の入出力スキーマ（edge E-R1）。登録・更新・出力。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EdgePcCreate(BaseModel):
    """エッジPC 登録。"""

    name: str
    host: str
    username: str | None = None
    password: str | None = None
    model_port: int | None = None
    enabled: bool = True


class EdgePcUpdate(BaseModel):
    """エッジPC 更新（指定項目のみ）。"""

    name: str | None = None
    host: str | None = None
    username: str | None = None
    password: str | None = None
    model_port: int | None = None
    enabled: bool | None = None


class EdgePcOut(BaseModel):
    """エッジPC 出力。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    username: str | None
    password: str | None
    model_port: int | None
    enabled: bool
    last_ftp_ok: bool | None
    last_ftp_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime
