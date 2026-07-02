"""色マスター API（color C-R1, C-R5, C-R6）。

一覧・詳細・取り込み（xlsx multipart）・色見本更新（status は自動管理・手動変更不可）・
手動 evaluate。get_db（ver2）依存・Basic 認証ゲート。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from src.api.security import require_auth
from src.database import get_db
from src.repositories.color_master_repository import ColorMasterRepository
from src.schemas.color_master import ColorOut, ColorSampleUpdate, ImportResult
from src.services.color_import_service import ColorImportService
from src.services.color_lifecycle_service import ColorLifecycleService

router = APIRouter(
    prefix="/api/colors",
    tags=["colors"],
    dependencies=[Depends(require_auth)],
)


@router.get("", response_model=list[ColorOut])
def list_colors(
    db: Annotated[Session, Depends(get_db)],
    status: str | None = None,
    color_no: str | None = None,
    size: str | None = None,
    chain: str | None = None,
    tape: str | None = None,
) -> list[ColorOut]:
    """色を絞り込んで一覧する。"""
    rows = ColorMasterRepository(db).list(
        status=status, color_no=color_no, size=size, chain=chain, tape=tape
    )
    return [ColorOut.model_validate(r) for r in rows]


@router.post("/import", response_model=ImportResult)
async def import_colors(db: Annotated[Session, Depends(get_db)], file: UploadFile) -> ImportResult:
    """色一覧ファイル（xlsx）を取り込む。"""
    data = await file.read()
    return ColorImportService(db).import_workbook(data)


@router.post("/evaluate")
def evaluate(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """手動でライフサイクル判定を実行する（テスト・即時実行用）。"""
    ColorLifecycleService(db).evaluate()
    return {"status": "completed"}


@router.get("/{color_id}", response_model=ColorOut)
def get_color(color_id: int, db: Annotated[Session, Depends(get_db)]) -> ColorOut:
    """色の詳細。"""
    color = ColorMasterRepository(db).get(color_id)
    if color is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="色が見つかりません")
    return ColorOut.model_validate(color)


@router.patch("/{color_id}", response_model=ColorOut)
def update_color_sample(
    color_id: int,
    payload: ColorSampleUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> ColorOut:
    """色見本（RGB/Lab）のみ更新する（status は自動管理・手動変更不可）。"""
    values = payload.model_dump(exclude_unset=True)
    color = ColorMasterRepository(db).update_sample(color_id, values)
    if color is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="色が見つかりません")
    return ColorOut.model_validate(color)
