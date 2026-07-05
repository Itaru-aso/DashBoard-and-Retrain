"""再学習 HTTP API（retraining M-R1, M-R5, M-R7, M-R8, M-R9）の api テスト。

起票（color_master 存在チェック・enqueue）・一覧・詳細・キャンセル（終端は accepted=false）・
現行配信一覧・手動配信・認証を検証する。training_service / deployment_service はフェイク注入。
DB は commit する専用 session_factory を用いる（テスト後に該当テーブルを truncate）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def session_factory(ver2_engine: Engine) -> Iterator[Callable[[], Session]]:
    """commit する ver2 Session を返すファクトリ（テスト後に retraining/color を truncate）。"""
    factory = sessionmaker(bind=ver2_engine)
    try:
        yield factory
    finally:
        with ver2_engine.begin() as conn:
            conn.execute(
                text(
                    "TRUNCATE deployed_model, retraining_job, color_master "
                    "RESTART IDENTITY CASCADE"
                )
            )


class FakeTrainingService:
    """enqueue / cancel を記録するフェイク。"""

    def __init__(self) -> None:
        self.enqueued: list[int] = []
        self.cancelled: list[int] = []

    def enqueue(self, job_id: int) -> None:
        self.enqueued.append(job_id)

    async def cancel(self, job_id: int) -> bool:
        self.cancelled.append(job_id)
        return True


class FakeDeploymentService:
    def deploy_job(self, job_id: int) -> dict:
        return {
            "job_id": job_id,
            "status": "SUCCESS",
            "detail": "{}",
            "edge_pc_count": 1,
        }


def _seed_color(session_factory: Callable[[], Session]) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository

    db = session_factory()
    try:
        ColorMasterRepository(db).create("501", "05", "CZT8", "")
        db.commit()
    finally:
        db.close()


@pytest.fixture
def make_client(session_factory, monkeypatch: pytest.MonkeyPatch):
    from src import config
    from src.api import retraining_endpoint as ep
    from src.database import get_db

    monkeypatch.setattr(config.settings, "ENABLE_BASIC_AUTH", False)
    fake_training = FakeTrainingService()

    def _override_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def _make() -> TestClient:
        app = FastAPI()
        app.include_router(ep.router)
        app.dependency_overrides[get_db] = _override_db
        monkeypatch.setattr(ep, "get_training_service", lambda: fake_training)
        monkeypatch.setattr(ep, "get_deployment_service", lambda: FakeDeploymentService())
        client = TestClient(app)
        client.fake_training = fake_training  # type: ignore[attr-defined]
        return client

    return _make


_BODY = {"color_no": "501", "size": "05", "chain": "CZT8", "tape": "", "created_by": "op1"}


@pytest.mark.api
def test_create_job_ok_enqueues(make_client, session_factory) -> None:
    _seed_color(session_factory)
    client = make_client()
    r = client.post("/api/retraining/jobs", json=_BODY)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "QUEUED" and body["color_no"] == "501"
    assert client.fake_training.enqueued == [body["id"]]


@pytest.mark.api
def test_create_job_rejects_unknown_color(make_client, session_factory) -> None:
    client = make_client()  # color_master に何も seed しない
    r = client.post("/api/retraining/jobs", json={**_BODY, "color_no": "999"})
    assert r.status_code == 404
    assert client.fake_training.enqueued == []  # 起票も投入もされない


@pytest.mark.api
def test_list_and_get_job(make_client, session_factory) -> None:
    _seed_color(session_factory)
    client = make_client()
    created = client.post("/api/retraining/jobs", json=_BODY).json()
    assert client.get("/api/retraining/jobs").json()["items"][0]["id"] == created["id"]
    assert client.get(f"/api/retraining/jobs/{created['id']}").json()["color_no"] == "501"
    assert client.get("/api/retraining/jobs/999999").status_code == 404


@pytest.mark.api
def test_cancel_active_and_terminal(make_client, session_factory) -> None:
    _seed_color(session_factory)
    client = make_client()
    created = client.post("/api/retraining/jobs", json=_BODY).json()

    r = client.post(f"/api/retraining/jobs/{created['id']}/cancel")
    assert r.status_code == 200 and r.json()["accepted"] is True
    assert client.fake_training.cancelled == [created["id"]]

    # 既に終端のジョブは accepted=false で冪等（起動側は呼ばない）。
    from src.repositories.retraining_repository import RetrainingRepository

    db = session_factory()
    try:
        RetrainingRepository(db).mark_completed(created["id"], "/m", "/c")
        db.commit()
    finally:
        db.close()
    r2 = client.post(f"/api/retraining/jobs/{created['id']}/cancel")
    assert r2.status_code == 200 and r2.json()["accepted"] is False


@pytest.mark.api
def test_cancel_missing_returns_404(make_client) -> None:
    client = make_client()
    assert client.post("/api/retraining/jobs/999999/cancel").status_code == 404


@pytest.mark.api
def test_deployed_list_and_manual_deploy(make_client, session_factory) -> None:
    _seed_color(session_factory)
    client = make_client()
    created = client.post("/api/retraining/jobs", json=_BODY).json()
    assert client.get("/api/retraining/deployed").json() == []
    r = client.post(f"/api/retraining/jobs/{created['id']}/deploy")
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS"


@pytest.mark.api
def test_requires_auth_when_enabled(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    from src import config
    from src.api import retraining_endpoint as ep
    from src.database import get_db

    monkeypatch.setattr(config.settings, "ENABLE_BASIC_AUTH", True)
    monkeypatch.setattr(config.settings, "BASIC_AUTH_USER", "shisui")
    monkeypatch.setattr(config.settings, "BASIC_AUTH_PASS", "secret")

    def _override_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(ep.router)
    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as c:
        assert c.get("/api/retraining/jobs").status_code == 401
