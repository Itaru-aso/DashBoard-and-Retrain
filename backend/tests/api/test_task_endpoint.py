"""保守タスク API（task R1.4, R3, R4, R5, R6）の api テスト。"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

_KEY = dict(color_no="501", size="05", chain="CZT8", tape="", task_type="ng_rate")


def _seed_task(db: Session):
    from src.repositories.task_repository import TaskRepository

    return TaskRepository(db).upsert(
        **_KEY,
        detected_value=Decimal("20.0"),
        threshold_value=Decimal("5.0"),
        evaluation_date=date(2026, 7, 1),
    )


@pytest.fixture
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from src import config, main
    from src.database import get_db

    monkeypatch.setattr(config.settings, "ENABLE_BASIC_AUTH", False)
    app = main.create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.api
def test_list_and_get(client: TestClient, db_session: Session) -> None:
    task = _seed_task(db_session)
    listed = client.get("/api/tasks", params={"status": "OPEN"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    got = client.get(f"/api/tasks/{task.id}")
    assert got.status_code == 200
    assert got.json()["task_type"] == "ng_rate"
    assert client.get("/api/tasks/999999").status_code == 404


@pytest.mark.api
def test_status_transition_forward_and_conflict(client: TestClient, db_session: Session) -> None:
    task = _seed_task(db_session)
    ok = client.patch(f"/api/tasks/{task.id}/status", json={"status": "IN_PROGRESS"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "IN_PROGRESS"
    # 逆遷移 → 409
    conflict = client.patch(f"/api/tasks/{task.id}/status", json={"status": "OPEN"})
    assert conflict.status_code == 409


@pytest.mark.api
def test_add_comment(client: TestClient, db_session: Session) -> None:
    task = _seed_task(db_session)
    res = client.post(f"/api/tasks/{task.id}/comments", json={"body": "再発防止: 清掃"})
    assert res.status_code == 200
    assert res.json()["comments"][0]["body"] == "再発防止: 清掃"


@pytest.mark.api
def test_comment_validation_422(client: TestClient, db_session: Session) -> None:
    task = _seed_task(db_session)
    res = client.post(f"/api/tasks/{task.id}/comments", json={"body": ""})
    assert res.status_code == 422


@pytest.mark.api
def test_evaluate_runs(client: TestClient) -> None:
    res = client.post("/api/tasks/evaluate", json={"window_days": 7})
    assert res.status_code == 200


@pytest.mark.api
def test_requires_auth_when_enabled(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from src import config, main
    from src.database import get_db

    monkeypatch.setattr(config.settings, "ENABLE_BASIC_AUTH", True)
    monkeypatch.setattr(config.settings, "BASIC_AUTH_USER", "shisui")
    monkeypatch.setattr(config.settings, "BASIC_AUTH_PASS", "secret")
    app = main.create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as c:
            assert c.get("/api/tasks").status_code == 401
    finally:
        app.dependency_overrides.clear()
