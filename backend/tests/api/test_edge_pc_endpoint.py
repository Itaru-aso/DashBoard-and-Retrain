"""エッジPC API（edge E-R1, E-R4, E-R5, E-R6）の api テスト。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

_BODY = {"name": "検査PC_1", "host": "169.254.93.171", "model_port": 2123}


class _FakeFTP:
    def connect(self, *a: object, **k: object) -> None: ...

    def login(self, *a: object, **k: object) -> None: ...

    def quit(self) -> None: ...


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
def test_crud_flow(client: TestClient) -> None:
    created = client.post("/api/edge-pcs", json=_BODY)
    assert created.status_code == 201
    edge_id = created.json()["id"]

    assert client.get("/api/edge-pcs").status_code == 200
    assert client.get(f"/api/edge-pcs/{edge_id}").status_code == 200
    patched = client.patch(f"/api/edge-pcs/{edge_id}", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert client.delete(f"/api/edge-pcs/{edge_id}").status_code == 204
    assert client.get(f"/api/edge-pcs/{edge_id}").status_code == 404


@pytest.mark.api
def test_duplicate_name_conflict(client: TestClient) -> None:
    assert client.post("/api/edge-pcs", json=_BODY).status_code == 201
    assert client.post("/api/edge-pcs", json=_BODY).status_code == 409


@pytest.mark.api
def test_check_ftp(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.edge_pc_service.FTP", lambda: _FakeFTP())
    edge_id = client.post("/api/edge-pcs", json=_BODY).json()["id"]
    res = client.post(f"/api/edge-pcs/{edge_id}/check-ftp")
    assert res.status_code == 200
    assert res.json()["last_ftp_ok"] is True


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
            assert c.get("/api/edge-pcs").status_code == 401
    finally:
        app.dependency_overrides.clear()
