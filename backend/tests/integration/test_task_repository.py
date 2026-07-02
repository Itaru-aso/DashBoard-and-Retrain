"""保守タスク Repository（task R2, R3, R4, R5）の integration テスト。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

KEY = dict(color_no="501", size="05", chain="CZT8", tape="", task_type="ng_rate")


def _upsert(repo: object, **over: object):
    params: dict[str, object] = dict(
        **KEY,
        detected_value=Decimal("6.0"),
        threshold_value=Decimal("5.0"),
        evaluation_date=date(2026, 7, 1),
    )
    params.update(over)
    return repo.upsert(**params)  # type: ignore[attr-defined]


@pytest.mark.integration
def test_upsert_creates_when_absent(db_session: Session) -> None:
    from src.repositories.task_repository import TaskRepository

    repo = TaskRepository(db_session)
    task = _upsert(repo)
    assert task.status == "OPEN"
    assert float(task.detected_value) == 6.0


@pytest.mark.integration
def test_upsert_overwrites_open(db_session: Session) -> None:
    from src.repositories.task_repository import TaskRepository

    repo = TaskRepository(db_session)
    first = _upsert(repo, detected_value=Decimal("6.0"))
    second = _upsert(repo, detected_value=Decimal("9.0"))
    assert first.id == second.id  # 同一タスクを上書き
    assert float(second.detected_value) == 9.0
    assert len(repo.list()) == 1


@pytest.mark.integration
def test_upsert_keeps_in_progress(db_session: Session) -> None:
    from src.repositories.task_repository import TaskRepository

    repo = TaskRepository(db_session)
    task = _upsert(repo)
    repo.transition_status(task.id, "IN_PROGRESS")
    kept = _upsert(repo, detected_value=Decimal("9.0"))
    assert kept.id == task.id
    assert kept.status == "IN_PROGRESS"
    assert float(kept.detected_value) == 6.0  # 保持（上書きしない）


@pytest.mark.integration
def test_upsert_new_when_only_done(db_session: Session) -> None:
    from src.repositories.task_repository import TaskRepository

    repo = TaskRepository(db_session)
    task = _upsert(repo)
    repo.transition_status(task.id, "IN_PROGRESS")
    repo.transition_status(task.id, "DONE")
    reopened = _upsert(repo)  # DONE のみ → 再発として新規
    assert reopened.id != task.id
    assert reopened.status == "OPEN"
    assert len(repo.list()) == 2


@pytest.mark.integration
def test_transition_forward_ok_and_invalid_rejected(db_session: Session) -> None:
    from src.repositories.task_repository import TaskRepository, TaskTransitionError

    repo = TaskRepository(db_session)
    task = _upsert(repo)
    repo.transition_status(task.id, "IN_PROGRESS")
    with pytest.raises(TaskTransitionError):
        repo.transition_status(task.id, "OPEN")  # 逆遷移
    task2 = _upsert(repo, color_no="777")
    with pytest.raises(TaskTransitionError):
        repo.transition_status(task2.id, "DONE")  # 段飛ばし（OPEN→DONE）


@pytest.mark.integration
def test_append_comment(db_session: Session) -> None:
    from src.repositories.task_repository import TaskRepository

    repo = TaskRepository(db_session)
    task = _upsert(repo)
    repo.append_comment(task.id, "対応開始")
    repo.append_comment(task.id, "再発防止: 清掃手順見直し")
    refreshed = repo.get(task.id)
    assert len(refreshed.comments) == 2
    assert refreshed.comments[0]["body"] == "対応開始"


@pytest.mark.integration
def test_list_filters_by_status_and_type(db_session: Session) -> None:
    from src.repositories.task_repository import TaskRepository

    repo = TaskRepository(db_session)
    _upsert(repo)  # ng_rate OPEN
    _upsert(repo, color_no="777", task_type="miss_rate")

    assert len(repo.list(status="OPEN")) == 2
    assert len(repo.list(task_type="miss_rate")) == 1
