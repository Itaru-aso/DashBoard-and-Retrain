"""エッジPC API（edge E-R1, E-R4, E-R5, E-R6）。

CRUD と FTP 送信可否確認。get_db（ver2）依存・Basic 認証ゲート。
name 重複は 409、未存在は 404。接続テスト失敗は結果（last_ftp_ok=False）として返す。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.security import require_auth
from src.database import get_db
from src.schemas.edge_pc import EdgePcCreate, EdgePcOut, EdgePcUpdate
from src.services.edge_pc_service import EdgePcService

router = APIRouter(
    prefix="/api/edge-pcs",
    tags=["edge-pcs"],
    dependencies=[Depends(require_auth)],
)


@router.get("", response_model=list[EdgePcOut])
def list_edge_pcs(db: Annotated[Session, Depends(get_db)]) -> list[EdgePcOut]:
    """エッジPCを一覧する。"""
    return [EdgePcOut.model_validate(e) for e in EdgePcService(db).list()]


@router.post("", response_model=EdgePcOut, status_code=status.HTTP_201_CREATED)
def create_edge_pc(payload: EdgePcCreate, db: Annotated[Session, Depends(get_db)]) -> EdgePcOut:
    """エッジPCを登録する（name 重複は 409）。"""
    try:
        with db.begin_nested():
            edge = EdgePcService(db).create(payload)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="同名のエッジPCが既にあります"
        ) from exc
    return EdgePcOut.model_validate(edge)


@router.get("/{edge_id}", response_model=EdgePcOut)
def get_edge_pc(edge_id: int, db: Annotated[Session, Depends(get_db)]) -> EdgePcOut:
    """エッジPCの詳細。"""
    edge = EdgePcService(db).get(edge_id)
    if edge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="エッジPCが見つかりません"
        )
    return EdgePcOut.model_validate(edge)


@router.patch("/{edge_id}", response_model=EdgePcOut)
def update_edge_pc(
    edge_id: int,
    payload: EdgePcUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> EdgePcOut:
    """エッジPCを更新する（name 重複は 409・未存在は 404）。"""
    service = EdgePcService(db)
    try:
        with db.begin_nested():
            edge = service.update(edge_id, payload)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="同名のエッジPCが既にあります"
        ) from exc
    if edge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="エッジPCが見つかりません"
        )
    return EdgePcOut.model_validate(edge)


@router.delete("/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_edge_pc(edge_id: int, db: Annotated[Session, Depends(get_db)]) -> Response:
    """エッジPCを削除する（未存在は 404）。"""
    if not EdgePcService(db).delete(edge_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="エッジPCが見つかりません"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{edge_id}/check-ftp", response_model=EdgePcOut)
def check_ftp(edge_id: int, db: Annotated[Session, Depends(get_db)]) -> EdgePcOut:
    """FTP 送信可否を確認し結果を記録して返す。"""
    edge = EdgePcService(db).check_ftp(edge_id)
    if edge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="エッジPCが見つかりません"
        )
    return EdgePcOut.model_validate(edge)
