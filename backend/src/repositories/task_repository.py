"""保守タスク Repository（ver2 DB・task R2, R3, R4, R5）。

- upsert: 無→新規(OPEN) / OPEN→上書き / IN_PROGRESS→保持 / DONE のみ→新規（再発）。
  アクティブ（OPEN/IN_PROGRESS）は部分ユニークで高々1件。
- transition_status: OPEN→IN_PROGRESS→DONE の**隣接前進のみ**（逆遷移・段飛ばしは拒否）。
- append_comment: comments(JSONB) へ追記（匿名・再発防止策もここへ）。
- list: status / 色 / task_type / 期間で絞り込み。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.task import Task

_ACTIVE = ("OPEN", "IN_PROGRESS")
_ORDER = ["OPEN", "IN_PROGRESS", "DONE"]


class TaskTransitionError(Exception):
    """状態遷移が前進（隣接）でない（逆遷移・段飛ばし）。API では 409。"""


class TaskRepository:
    """task（ver2 DB）の upsert・状態遷移・コメント・一覧。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, task_id: int) -> Task | None:
        """id で取得する。"""
        return self._session.get(Task, task_id)

    def find_active(
        self, color_no: str, size: str, chain: str, tape: str, task_type: str
    ) -> Task | None:
        """同キーのアクティブ（OPEN/IN_PROGRESS）タスクを返す（高々1件）。"""
        stmt = select(Task).where(
            Task.color_no == color_no,
            Task.size == size,
            Task.chain == chain,
            Task.tape == tape,
            Task.task_type == task_type,
            Task.status.in_(_ACTIVE),
        )
        return self._session.scalars(stmt).one_or_none()

    def upsert(
        self,
        color_no: str,
        size: str,
        chain: str,
        tape: str,
        task_type: str,
        detected_value: Decimal,
        threshold_value: Decimal,
        evaluation_date: date,
    ) -> Task:
        """逸脱を upsert する（冪等・4系統）。"""
        active = self.find_active(color_no, size, chain, tape, task_type)
        if active is None:
            task = Task(
                color_no=color_no,
                size=size,
                chain=chain,
                tape=tape,
                task_type=task_type,
                status="OPEN",
                detected_value=detected_value,
                threshold_value=threshold_value,
                evaluation_date=evaluation_date,
                comments=[],
            )
            self._session.add(task)
            self._session.flush()
            self._session.refresh(task)
            return task

        if active.status == "OPEN":
            active.detected_value = detected_value
            active.threshold_value = threshold_value
            active.evaluation_date = evaluation_date
            active.updated_at = datetime.now(timezone.utc)
            self._session.flush()
        # IN_PROGRESS は保持（変更しない）。
        return active

    def transition_status(self, task_id: int, target: str) -> Task:
        """隣接前進のみ許可（逆遷移・段飛ばしは TaskTransitionError）。"""
        task = self._session.get(Task, task_id)
        if task is None:
            raise TaskTransitionError(f"task {task_id} が見つかりません")
        current_idx = _ORDER.index(task.status)
        target_idx = _ORDER.index(target)
        if target_idx != current_idx + 1:
            raise TaskTransitionError(
                f"{task.status} -> {target} は許可されない遷移です（隣接前進のみ）"
            )
        task.status = target
        task.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        self._session.refresh(task)
        return task

    def append_comment(self, task_id: int, body: str) -> Task | None:
        """comments(JSONB) にコメントを追記する。"""
        task = self._session.get(Task, task_id)
        if task is None:
            return None
        entry = {"body": body, "created_at": datetime.now(timezone.utc).isoformat()}
        # JSONB は in-place 変更が追跡されないため新リストを代入する。
        task.comments = [*task.comments, entry]
        task.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        self._session.refresh(task)
        return task

    def list(
        self,
        status: str | None = None,
        color_no: str | None = None,
        size: str | None = None,
        chain: str | None = None,
        tape: str | None = None,
        task_type: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[Task]:
        """絞り込んでタスクを一覧する（created_at 降順）。"""
        stmt = select(Task)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if color_no is not None:
            stmt = stmt.where(Task.color_no == color_no)
        if size is not None:
            stmt = stmt.where(Task.size == size)
        if chain is not None:
            stmt = stmt.where(Task.chain == chain)
        if tape is not None:
            stmt = stmt.where(Task.tape == tape)
        if task_type is not None:
            stmt = stmt.where(Task.task_type == task_type)
        if date_from is not None:
            stmt = stmt.where(
                Task.created_at
                >= datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc)
            )
        if date_to is not None:
            end = datetime(date_to.year, date_to.month, date_to.day, tzinfo=timezone.utc)
            stmt = stmt.where(Task.created_at < end.replace(hour=23, minute=59, second=59))
        stmt = stmt.order_by(Task.created_at.desc(), Task.id.desc())
        return list(self._session.scalars(stmt))
