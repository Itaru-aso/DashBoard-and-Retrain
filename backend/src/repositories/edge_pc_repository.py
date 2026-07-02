"""エッジPC Repository（ver2 DB・edge E-R1, E-R3, E-R4）。

CRUD と `find_enabled()`（配信先解決の参照点。モデル再学習の deployment_service が利用）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.edge_pc import EdgePc
from src.schemas.edge_pc import EdgePcCreate, EdgePcUpdate


class EdgePcRepository:
    """edge_pc（ver2 DB）の CRUD と有効エッジPC取得。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, data: EdgePcCreate) -> EdgePc:
        """エッジPCを登録する。"""
        edge = EdgePc(
            name=data.name,
            host=data.host,
            username=data.username,
            password=data.password,
            model_port=data.model_port,
            enabled=data.enabled,
        )
        self._session.add(edge)
        self._session.flush()
        self._session.refresh(edge)
        return edge

    def get(self, edge_id: int) -> EdgePc | None:
        """id で取得する。"""
        return self._session.get(EdgePc, edge_id)

    def list(self) -> list[EdgePc]:
        """全件を名前順で返す。"""
        return list(self._session.scalars(select(EdgePc).order_by(EdgePc.name)))

    def find_enabled(self) -> Sequence[EdgePc]:
        """有効なエッジPCのみ返す（配信先解決の参照点）。"""
        stmt = select(EdgePc).where(EdgePc.enabled.is_(True)).order_by(EdgePc.name)
        return list(self._session.scalars(stmt))

    def update(self, edge_id: int, data: EdgePcUpdate) -> EdgePc | None:
        """指定項目のみ更新する。"""
        edge = self._session.get(EdgePc, edge_id)
        if edge is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(edge, field, value)
        edge.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        self._session.refresh(edge)
        return edge

    def delete(self, edge_id: int) -> bool:
        """削除する（存在しなければ False）。"""
        edge = self._session.get(EdgePc, edge_id)
        if edge is None:
            return False
        self._session.delete(edge)
        self._session.flush()
        return True

    def record_ftp_result(self, edge_id: int, ok: bool) -> EdgePc | None:
        """FTP 送信可否の結果を記録する（edge E-R5）。"""
        edge = self._session.get(EdgePc, edge_id)
        if edge is None:
            return None
        edge.last_ftp_ok = ok
        edge.last_ftp_checked_at = datetime.now(timezone.utc)
        self._session.flush()
        self._session.refresh(edge)
        return edge
