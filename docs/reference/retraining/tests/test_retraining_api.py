"""retraining API・WebSocket のテスト（依存を override）。

配置先: backend/tests/api/test_retraining_api.py
要: fastapi TestClient。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import retraining_endpoint as ep
from database import get_db
from auth import verify_basic_auth
from dependencies import get_color_master_repo, get_deployment_service
from services.training_service import get_training_service


# ---- フェイク依存 ----

class FakeColorRepo:
    def __init__(self, exists=True): self._exists = exists
    def exists_by_tuple(self, color_no, size, chain, tape): return self._exists


class FakeTrainingService:
    def __init__(self): self.enqueued = []; self.cancelled = []
    def enqueue(self, job_id): self.enqueued.append(job_id)
    async def cancel(self, job_id): self.cancelled.append(job_id); return True
    def subscribe(self, job_id):
        import asyncio
        q = asyncio.Queue(); q.put_nowait("学習開始"); q.put_nowait("パイプライン完了"); q.put_nowait(None)
        return q
    def unsubscribe(self, job_id, q): pass


class FakeDeploymentService:
    def deploy_job(self, job_id):
        return {"job_id": job_id, "status": "SUCCESS", "detail": {"pc1": {"ok": True, "errors": []}},
                "edge_pc_count": 1}


@pytest.fixture()
def client(session_factory, monkeypatch):
    app = FastAPI()
    app.include_router(ep.router)

    fake_training = FakeTrainingService()

    def _override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[verify_basic_auth] = lambda: True
    app.dependency_overrides[get_color_master_repo] = lambda: FakeColorRepo(exists=True)
    app.dependency_overrides[get_deployment_service] = lambda: FakeDeploymentService()
    monkeypatch.setattr(ep, "get_training_service", lambda: fake_training)

    c = TestClient(app)
    c.fake_training = fake_training        # テストから参照
    c.app_ref = app
    return c


def test_create_job_ok_enqueues(client):
    r = client.post("/api/retraining/jobs", json={
        "color_no": "501", "size": "05", "chain": "CZT8", "tape": "", "created_by": "op1"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "QUEUED" and body["color_no"] == "501"
    assert client.fake_training.enqueued == [body["id"]]


def test_create_job_rejects_unknown_color(client):
    client.app_ref.dependency_overrides[get_color_master_repo] = lambda: FakeColorRepo(exists=False)
    r = client.post("/api/retraining/jobs", json={
        "color_no": "999", "size": "05", "chain": "CZT8", "tape": ""})
    assert r.status_code == 404
    assert client.fake_training.enqueued == []        # 起票も投入もされない


def test_list_and_get_job(client):
    created = client.post("/api/retraining/jobs", json={
        "color_no": "501", "size": "05", "chain": "CZT8", "tape": ""}).json()
    assert client.get("/api/retraining/jobs").json()["items"][0]["id"] == created["id"]
    assert client.get(f"/api/retraining/jobs/{created['id']}").json()["color_no"] == "501"
    assert client.get("/api/retraining/jobs/999999").status_code == 404


def test_cancel_active_and_terminal(client):
    created = client.post("/api/retraining/jobs", json={
        "color_no": "501", "size": "05", "chain": "CZT8", "tape": ""}).json()
    r = client.post(f"/api/retraining/jobs/{created['id']}/cancel")
    assert r.status_code == 200 and r.json()["accepted"] is True
    assert client.fake_training.cancelled == [created["id"]]


def test_deployed_list_and_manual_deploy(client):
    created = client.post("/api/retraining/jobs", json={
        "color_no": "501", "size": "05", "chain": "CZT8", "tape": ""}).json()
    assert client.get("/api/retraining/deployed").json() == []
    r = client.post(f"/api/retraining/jobs/{created['id']}/deploy")
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS"


def test_progress_websocket_streams_then_closes(client):
    created = client.post("/api/retraining/jobs", json={
        "color_no": "501", "size": "05", "chain": "CZT8", "tape": ""}).json()
    with client.websocket_connect(f"/api/retraining/jobs/{created['id']}/progress") as ws:
        assert ws.receive_text() == "学習開始"
        assert ws.receive_text() == "パイプライン完了"
        # None センチネルでサーバが close する
