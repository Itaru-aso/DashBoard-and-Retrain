"""エッジPC Service（edge E-R1, E-R5）。

CRUD と FTP 送信可否確認（`check_ftp`）。実 FTP I/O は `ftplib`（ver1 踏襲・平文）。
接続テスト失敗は例外にせず結果（last_ftp_ok=False）として記録する。
"""

from __future__ import annotations

import logging
from ftplib import FTP

from sqlalchemy.orm import Session

from src.models.edge_pc import EdgePc
from src.repositories.edge_pc_repository import EdgePcRepository
from src.schemas.edge_pc import EdgePcCreate, EdgePcUpdate

logger = logging.getLogger(__name__)


class EdgePcService:
    """エッジPC の CRUD と FTP 送信可否確認。"""

    def __init__(self, session: Session) -> None:
        self._repo = EdgePcRepository(session)

    def create(self, data: EdgePcCreate) -> EdgePc:
        """登録する。"""
        return self._repo.create(data)

    def get(self, edge_id: int) -> EdgePc | None:
        """id で取得する。"""
        return self._repo.get(edge_id)

    def list(self) -> list[EdgePc]:
        """一覧する。"""
        return self._repo.list()

    def update(self, edge_id: int, data: EdgePcUpdate) -> EdgePc | None:
        """更新する。"""
        return self._repo.update(edge_id, data)

    def delete(self, edge_id: int) -> bool:
        """削除する。"""
        return self._repo.delete(edge_id)

    def check_ftp(self, edge_id: int) -> EdgePc | None:
        """FTP 送信可否を確認し結果を記録する（失敗は False として記録）。"""
        edge = self._repo.get(edge_id)
        if edge is None:
            return None
        ok = self._probe(edge)
        return self._repo.record_ftp_result(edge_id, ok)

    @staticmethod
    def _probe(edge: EdgePc) -> bool:
        """対象エッジPC へ FTP 接続を試みる（到達可否のみ）。"""
        try:
            ftp = FTP()
            ftp.connect(edge.host, edge.model_port or 21, timeout=5)
            if edge.username:
                ftp.login(edge.username, edge.password or "")
            ftp.quit()
            return True
        except Exception:
            logger.warning("エッジPC への FTP 接続に失敗: %s", edge.name, exc_info=True)
            return False
