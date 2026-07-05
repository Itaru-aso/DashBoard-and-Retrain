"""モデル再学習 API・WebSocket（ver2・retraining M-R1, M-R5〜M-R9）。

- HTTP エンドポイント（起票・一覧・詳細・キャンセル・現行配信・手動配信）は各ルートに
  Basic 認証ゲート（`require_auth`）を付与する。
- WS `/api/retraining/jobs/{id}/progress`: `training_service.subscribe` を購読し各行を素通し配信する。
  None センチネルで close（揮発）。切断・終了時は購読解除する。WebSocket には HTTPBasic 依存を
  載せない（ハンドシェイクを壊すため。購読は接続後）。
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from src.api.security import require_auth
from src.database import get_db
from src.repositories.color_master_repository import ColorMasterRepository
from src.repositories.retraining_repository import RetrainingRepository
from src.schemas.retraining import (
    CancelResponse,
    DeployedModelResponse,
    DeployResponse,
    JobCreateRequest,
    JobListResponse,
    JobResponse,
)
from src.services.deployment_service import get_deployment_service
from src.services.training_service import get_training_service

router = APIRouter(prefix="/api/retraining", tags=["retraining"])

_AUTH = [Depends(require_auth)]

# 終端状態（キャンセル冪等判定用）。
_TERMINAL = ("COMPLETED", "FAILED", "CANCELLED")


@router.post(
    "/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_AUTH,
)
def create_job(payload: JobCreateRequest, db: Annotated[Session, Depends(get_db)]) -> JobResponse:
    """再学習ジョブを起票する。color_master に存在する色のみ受理（M-R1）。"""
    tape = payload.tape or ""
    exists = ColorMasterRepository(db).find_by_tuple(
        payload.color_no, payload.size, payload.chain, tape
    )
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "color_master に存在しない色です: "
                f"({payload.color_no},{payload.size},{payload.chain},{tape})"
            ),
        )
    job = RetrainingRepository(db).create_job(
        color_no=payload.color_no,
        size=payload.size,
        chain=payload.chain,
        tape=tape,
        created_by=payload.created_by,
    )
    db.commit()  # ワーカが別 Session で読めるよう、投入前に確定
    db.refresh(job)
    get_training_service().enqueue(job.id)
    return JobResponse.model_validate(job)


@router.get("/jobs", response_model=JobListResponse, dependencies=_AUTH)
def list_jobs(
    db: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListResponse:
    """再学習ジョブの履歴一覧（status 絞り込み・ページング）。"""
    jobs = RetrainingRepository(db).list_jobs(limit=limit, offset=offset, status=status_filter)
    return JobListResponse(
        items=[JobResponse.model_validate(j) for j in jobs], limit=limit, offset=offset
    )


@router.get("/jobs/{job_id}", response_model=JobResponse, dependencies=_AUTH)
def get_job(job_id: int, db: Annotated[Session, Depends(get_db)]) -> JobResponse:
    """再学習ジョブの詳細。"""
    job = RetrainingRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ジョブが見つかりません")
    return JobResponse.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=CancelResponse, dependencies=_AUTH)
async def cancel_job(job_id: int, db: Annotated[Session, Depends(get_db)]) -> CancelResponse:
    """ジョブをキャンセルする（終端は accepted=false で冪等）。"""
    job = RetrainingRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ジョブが見つかりません")
    if job.status in _TERMINAL:
        return CancelResponse(job_id=job_id, accepted=False)
    accepted = await get_training_service().cancel(job_id)
    return CancelResponse(job_id=job_id, accepted=accepted)


@router.get("/deployed", response_model=list[DeployedModelResponse], dependencies=_AUTH)
def list_deployed(db: Annotated[Session, Depends(get_db)]) -> list[DeployedModelResponse]:
    """色ごとの現行配信モデル一覧。"""
    rows = RetrainingRepository(db).list_deployed()
    return [DeployedModelResponse.model_validate(r) for r in rows]


@router.post("/jobs/{job_id}/deploy", response_model=DeployResponse, dependencies=_AUTH)
async def deploy_job(job_id: int) -> DeployResponse:
    """手動配信（将来用）。COMPLETED ジョブの ONNX を再配信し現行モデルを更新する。"""
    try:
        result = await asyncio.to_thread(get_deployment_service().deploy_job, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DeployResponse(**result)


@router.websocket("/jobs/{job_id}/progress")
async def progress_ws(websocket: WebSocket, job_id: int) -> None:
    """進捗の WebSocket 配信（揮発）。各行を素通しし、None センチネルで close する。"""
    await websocket.accept()
    service = get_training_service()
    queue = service.subscribe(job_id)
    try:
        while True:
            line = await queue.get()
            if line is None:  # ストリーム終了
                await websocket.close()
                break
            await websocket.send_text(line)
    except WebSocketDisconnect:
        pass
    finally:
        service.unsubscribe(job_id, queue)
