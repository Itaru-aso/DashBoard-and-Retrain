"""保守タスク Pydantic スキーマ（task R3, R5）の unit テスト。"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError


@pytest.mark.unit
def test_status_transition_valid() -> None:
    from src.schemas.task import StatusTransitionRequest

    assert StatusTransitionRequest(status="IN_PROGRESS").status == "IN_PROGRESS"


@pytest.mark.unit
def test_status_transition_invalid_enum() -> None:
    from src.schemas.task import StatusTransitionRequest

    with pytest.raises(ValidationError):
        StatusTransitionRequest(status="CLOSED")


@pytest.mark.unit
def test_comment_requires_body() -> None:
    from src.schemas.task import CommentCreate

    assert CommentCreate(body="対応中").body == "対応中"
    with pytest.raises(ValidationError):
        CommentCreate(body="")


@pytest.mark.unit
def test_filter_accepts_optional_fields() -> None:
    from src.schemas.task import TaskFilter

    f = TaskFilter(status="OPEN", task_type="ng_rate", color_no="501")
    assert f.status == "OPEN"
    empty = TaskFilter()
    assert empty.status is None


@pytest.mark.unit
def test_filter_end_before_start_rejected() -> None:
    from src.schemas.task import TaskFilter

    with pytest.raises(ValidationError):
        TaskFilter(date_from=date(2026, 7, 31), date_to=date(2026, 7, 1))
