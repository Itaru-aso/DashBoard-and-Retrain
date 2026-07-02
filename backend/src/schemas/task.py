"""保守タスク API の入出力スキーマ（task R3, R5）。

enum・状態遷移入力・フィルタ・コメント追加・evaluate を定義する。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TaskType = Literal["ng_rate", "false_alarm_rate", "miss_rate"]
TaskStatus = Literal["OPEN", "IN_PROGRESS", "DONE"]


class TaskFilter(BaseModel):
    """一覧フィルタ（すべて任意）。"""

    status: TaskStatus | None = None
    color_no: str | None = None
    size: str | None = None
    chain: str | None = None
    tape: str | None = None
    task_type: TaskType | None = None
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _validate_period(self) -> "TaskFilter":
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_to < self.date_from
        ):
            raise ValueError("終了日は開始日以降にしてください")
        return self


class StatusTransitionRequest(BaseModel):
    """状態遷移リクエスト（遷移先。前進のみは Service で検証）。"""

    status: TaskStatus


class CommentCreate(BaseModel):
    """コメント追加（本文必須。再発防止策もここに記録）。"""

    body: str = Field(min_length=1)


class EvaluateRequest(BaseModel):
    """手動の逸脱判定リクエスト。"""

    window_days: int | None = Field(default=None, ge=1)


class CommentOut(BaseModel):
    """コメント1件。"""

    body: str
    created_at: datetime


class TaskOut(BaseModel):
    """タスク出力（コメント含む）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    color_no: str
    size: str
    chain: str
    tape: str
    task_type: TaskType
    status: TaskStatus
    detected_value: Decimal | None
    threshold_value: Decimal | None
    evaluation_date: date | None
    comments: list[CommentOut]
    created_at: datetime
    updated_at: datetime
