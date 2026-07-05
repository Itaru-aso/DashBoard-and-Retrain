"""再学習 WebSocket 進捗（retraining M-R6）の api テスト。

行が素通しで流れる・None センチネルで close・購読解除（unsubscribe）を検証する。
training_service は購読キューを差し替えたフェイクを注入する。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


class FakeTrainingService:
    """subscribe で行＋None を積んだキューを返し、unsubscribe を記録する。"""

    def __init__(self, lines: list[str | None]) -> None:
        self._lines = lines
        self.unsubscribed: list[int] = []

    def subscribe(self, job_id: int) -> asyncio.Queue[str | None]:
        q: asyncio.Queue[str | None] = asyncio.Queue()
        for line in self._lines:
            q.put_nowait(line)
        return q

    def unsubscribe(self, job_id: int, q: asyncio.Queue[str | None]) -> None:
        self.unsubscribed.append(job_id)


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch):
    from src.api import retraining_endpoint as ep

    def _make(fake: FakeTrainingService) -> Iterator[TestClient]:
        app = FastAPI()
        app.include_router(ep.router)
        monkeypatch.setattr(ep, "get_training_service", lambda: fake)
        return TestClient(app)

    return _make


@pytest.mark.api
def test_progress_streams_then_closes(make_client) -> None:
    fake = FakeTrainingService(["学習開始", "パイプライン完了", None])
    client = make_client(fake)
    with client.websocket_connect("/api/retraining/jobs/5/progress") as ws:
        assert ws.receive_text() == "学習開始"
        assert ws.receive_text() == "パイプライン完了"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()  # None センチネルでサーバが close する


@pytest.mark.api
def test_progress_unsubscribes_on_close(make_client) -> None:
    fake = FakeTrainingService(["行1", None])
    client = make_client(fake)
    with client.websocket_connect("/api/retraining/jobs/9/progress") as ws:
        assert ws.receive_text() == "行1"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()
    assert fake.unsubscribed == [9]  # 終了時に購読解除される
