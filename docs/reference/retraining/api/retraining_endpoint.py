"""モデル再学習ワークフローの API・WebSocket（ver2）。

配置先: backend/src/api/retraining_endpoint.py

エンドポイント（すべて Basic 認証ゲート通過。WS は接続後に購読）:
- POST   /api/retraining/jobs              起票（color_master 存在チェック → QUEUED 作成 → キュー投入）
- GET    /api/retraining/jobs              履歴一覧（status 絞り込み・ページング）
- GET    /api/retraining/jobs/{id}         詳細
- POST   /api/retraining/jobs/{id}/cancel  キャンセル（QUEUED 除外 / RUNNING はプロセスグループ kill）
- WS     /api/retraining/jobs/{id}/progress 進捗（標準出力を素通し配信・None で終了）
- GET    /api/retraining/deployed          現行配信モデル一覧
- POST   /api/retraining/jobs/{id}/deploy  手動配信（将来用。v1 は完了時に自動配信）

依存（プロジェクトに合わせて実体を注入）:
- `get_db`            : ver2 同期 Session（基盤整備）
- `verify_basic_auth` : Basic 認証依存（基盤整備）
- `get_training_service` : TrainingService シングルトン（services.training_service）
- `get_deployment_service` : DeploymentService（手動配信用）
- `get_color_master_repo`  : color_master 存在チェック用 repo（`exists_by_tuple(...) -> bool`。色マスター spec）
"""
from __future__ import annotations

from typing import Protocol

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.orm import Session

from repositories.retraining_repository import RetrainingRepository
from schemas.retraining import (
    CancelResponse,
    DeployResponse,
    DeployedModelResponse,
    JobCreateRequest,
    JobListResponse,
    JobResponse,
)
from services.training_service import get_training_service

# 基盤整備が提供する依存（実体に合わせて import を調整）
from database import get_db                      # ver2 Session
from auth import verify_basic_auth               # Basic 認証
from dependencies import (                       # DI ファクトリ（プロジェクトに合わせて）
    get_color_master_repo,
    get_deployment_service,
)

router = APIRouter(
    prefix="/api/retraining",
    tags=["retraining"],
    dependencies=[Depends(verify_basic_auth)],
)


class _ColorMasterRepo(Protocol):
    def exists_by_tuple(self, color_no: str, size: str, chain: str, tape: str) -> bool: ...


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    req: JobCreateRequest,
    db: Session = Depends(get_db),
    color_repo: _ColorMasterRepo = Depends(get_color_master_repo),
) -> JobResponse:
    """再学習ジョブを起票する。color_master に存在する色のみ受理（M-R1）。"""
    if not color_repo.exists_by_tuple(req.color_no, req.size, req.chain, req.tape or ""):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"color_master に存在しない色です: "
                f"({req.color_no},{req.size},{req.chain},{req.tape})"
            ),
        )
    repo = RetrainingRepository(db)
    job = repo.create_job(
        color_no=req.color_no, size=req.size, chain=req.chain, tape=req.tape or "",
        created_by=req.created_by,
    )
    db.commit()        # ワーカが別 Session で読めるよう、投入前に確定
    db.refresh(job)
    get_training_service().enqueue(job.id)
    return JobResponse.model_validate(job)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> JobListResponse:
    jobs = RetrainingRepository(db).list_jobs(limit=limit, offset=offset, status=status_filter)
    return JobListResponse(
        items=[JobResponse.model_validate(j) for j in jobs], limit=limit, offset=offset,
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobResponse:
    job = RetrainingRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ジョブが見つかりません")
    return JobResponse.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=CancelResponse)
async def cancel_job(job_id: int, db: Session = Depends(get_db)) -> CancelResponse:
    job = RetrainingRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ジョブが見つかりません")
    if job.status in ("COMPLETED", "FAILED", "CANCELLED"):
        # 既に終端：冪等に false を返す（エラーにしない）
        return CancelResponse(job_id=job_id, accepted=False)
    accepted = await get_training_service().cancel(job_id)
    return CancelResponse(job_id=job_id, accepted=accepted)


@router.get("/deployed", response_model=list[DeployedModelResponse])
def list_deployed(db: Session = Depends(get_db)) -> list[DeployedModelResponse]:
    rows = RetrainingRepository(db).list_deployed()
    return [DeployedModelResponse.model_validate(r) for r in rows]


@router.post("/jobs/{job_id}/deploy", response_model=DeployResponse)
async def deploy_job(
    job_id: int,
    deployment_service=Depends(get_deployment_service),
) -> DeployResponse:
    """手動配信（将来用）。COMPLETED ジョブの ONNX を再配信し現行モデルを更新する。"""
    import asyncio

    try:
        result = await asyncio.to_thread(deployment_service.deploy_job, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return DeployResponse(**result)


@router.websocket("/jobs/{job_id}/progress")
async def progress_ws(websocket: WebSocket, job_id: int) -> None:
    """進捗の WebSocket 配信。標準出力の各行を素通しで送り、None センチネルで終了する（揮発）。"""
    await websocket.accept()
    service = get_training_service()
    queue = service.subscribe(job_id)
    try:
        while True:
            line = await queue.get()
            if line is None:        # ストリーム終了
                await websocket.close()
                break
            await websocket.send_text(line)
    except WebSocketDisconnect:
        pass
    finally:
        service.unsubscribe(job_id, queue)
