"""保守タスク API（task R1.4, R3, R4, R5, R6）。

一覧・詳細・状態遷移（前進のみ・違反 409）・コメント追加・手動 evaluate。
**手動作成は無し**（自動起票のみ）。get_db（ver2）依存・Basic 認証ゲート。
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.api.security import require_auth
from src.database import get_db
from src.repositories.task_repository import TaskRepository, TaskTransitionError
from src.schemas.task import (
    CommentCreate,
    EvaluateRequest,
    StatusTransitionRequest,
    TaskFilter,
    TaskOut,
)
from src.services.breach_evaluation_service import BreachEvaluationService

router = APIRouter(
    prefix="/api/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_auth)],
)


@router.get("", response_model=list[TaskOut])
def list_tasks(
    db: Annotated[Session, Depends(get_db)],
    status_: Annotated[str | None, Query(alias="status")] = None,
    color_no: str | None = None,
    size: str | None = None,
    chain: str | None = None,
    tape: str | None = None,
    task_type: str | None = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> list[TaskOut]:
    """タスクを絞り込んで一覧する。"""
    try:
        TaskFilter(
            status=status_,  # type: ignore[arg-type]
            color_no=color_no,
            size=size,
            chain=chain,
            tape=tape,
            task_type=task_type,  # type: ignore[arg-type]
            date_from=date_from,
            date_to=date_to,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="フィルタが不正です") from exc

    rows = TaskRepository(db).list(
        status=status_,
        color_no=color_no,
        size=size,
        chain=chain,
        tape=tape,
        task_type=task_type,
        date_from=date_from,
        date_to=date_to,
    )
    return [TaskOut.model_validate(r) for r in rows]


@router.post("/evaluate")
def evaluate(payload: EvaluateRequest, db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """手動で逸脱判定を実行する（テスト・即時実行用）。"""
    BreachEvaluationService(db).evaluate(payload.window_days)
    return {"status": "completed"}


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Annotated[Session, Depends(get_db)]) -> TaskOut:
    """タスク詳細（コメント含む）。"""
    task = TaskRepository(db).get(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="タスクが見つかりません")
    return TaskOut.model_validate(task)


@router.patch("/{task_id}/status", response_model=TaskOut)
def transition_status(
    task_id: int,
    payload: StatusTransitionRequest,
    db: Annotated[Session, Depends(get_db)],
) -> TaskOut:
    """状態遷移（前進のみ・違反は 409・未存在は 404）。"""
    repo = TaskRepository(db)
    if repo.get(task_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="タスクが見つかりません")
    try:
        task = repo.transition_status(task_id, payload.status)
    except TaskTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TaskOut.model_validate(task)


@router.post("/{task_id}/comments", response_model=TaskOut)
def add_comment(
    task_id: int,
    payload: CommentCreate,
    db: Annotated[Session, Depends(get_db)],
) -> TaskOut:
    """コメントを追加する（経過・再発防止策）。"""
    task = TaskRepository(db).append_comment(task_id, payload.body)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="タスクが見つかりません")
    return TaskOut.model_validate(task)
