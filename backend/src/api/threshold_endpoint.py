"""閾値管理 API（R1, R2, R4, R5, R6）。

`/api/thresholds` の CRUD と `/api/thresholds/effective`（有効閾値解決）。Basic 認証を適用。
重複は 409、検証失敗は 422（Pydantic）、未存在は 404。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.security import require_auth
from src.database import get_db
from src.schemas.threshold import ThresholdCreate, ThresholdOut, ThresholdUpdate
from src.services.threshold_service import (
    ThresholdConflictError,
    ThresholdService,
)

router = APIRouter(
    prefix="/api/thresholds",
    tags=["thresholds"],
    dependencies=[Depends(require_auth)],
)


@router.post("", response_model=ThresholdOut, status_code=status.HTTP_201_CREATED)
def create_threshold(
    payload: ThresholdCreate, db: Annotated[Session, Depends(get_db)]
) -> ThresholdOut:
    """閾値を作成する（重複は 409）。"""
    service = ThresholdService(db)
    try:
        row = service.create(payload)
    except ThresholdConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ThresholdOut.model_validate(row)


@router.get("", response_model=list[ThresholdOut])
def list_thresholds(
    db: Annotated[Session, Depends(get_db)],
    metric: str | None = None,
    scope: str | None = None,
) -> list[ThresholdOut]:
    """閾値を一覧する（メトリクス・スコープで絞り込み）。"""
    rows = ThresholdService(db).list(metric=metric, scope=scope)
    return [ThresholdOut.model_validate(r) for r in rows]


@router.get("/effective", response_model=ThresholdOut)
def get_effective_threshold(
    db: Annotated[Session, Depends(get_db)],
    metric: str,
    color_no: str,
    size: str,
    chain: str,
    tape: str,
    at: datetime,
) -> ThresholdOut:
    """有効閾値を解決する（色別 → global → 404）。"""
    resolved = ThresholdService(db).resolve_effective(metric, (color_no, size, chain, tape), at)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="有効な閾値がありません")
    return ThresholdOut.model_validate(resolved)


@router.get("/{threshold_id}", response_model=ThresholdOut)
def get_threshold(threshold_id: int, db: Annotated[Session, Depends(get_db)]) -> ThresholdOut:
    """閾値を個別参照する（未存在は 404）。"""
    row = ThresholdService(db).get(threshold_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="閾値が見つかりません")
    return ThresholdOut.model_validate(row)


@router.patch("/{threshold_id}", response_model=ThresholdOut)
def update_threshold(
    threshold_id: int,
    payload: ThresholdUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> ThresholdOut:
    """閾値を更新する（重複は 409・未存在は 404）。"""
    service = ThresholdService(db)
    try:
        row = service.update(threshold_id, payload)
    except ThresholdConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="閾値が見つかりません")
    return ThresholdOut.model_validate(row)
