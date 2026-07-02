"""閾値 API（R1, R2, R4, R5, R6）の api テスト。

- POST 201 / 重複 409 / 検証 422、GET 一覧・個別、PATCH 200、effective 解決、Basic 認証。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

_PER_COLOR = {
    "metric": "ng_rate",
    "scope": "per_color",
    "color_no": "501",
    "size": "05",
    "chain": "CZT8",
    "tape": "",
    "value_pct": 5.0,
    "valid_from": "2026-01-01T00:00:00Z",
    "valid_to": "2026-02-01T00:00:00Z",
}


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
def test_create_returns_201(client: TestClient) -> None:
    res = client.post("/api/thresholds", json=_PER_COLOR)
    assert res.status_code == 201
    body = res.json()
    assert body["metric"] == "ng_rate"
    assert body["id"] > 0


@pytest.mark.api
def test_create_conflict_returns_409(client: TestClient) -> None:
    assert client.post("/api/thresholds", json=_PER_COLOR).status_code == 201
    overlap = {**_PER_COLOR, "valid_from": "2026-01-15T00:00:00Z", "valid_to": None}
    assert client.post("/api/thresholds", json=overlap).status_code == 409


@pytest.mark.api
def test_create_validation_returns_422(client: TestClient) -> None:
    bad = {**_PER_COLOR, "value_pct": 150.0}
    assert client.post("/api/thresholds", json=bad).status_code == 422


@pytest.mark.api
def test_list_and_get(client: TestClient) -> None:
    created = client.post("/api/thresholds", json=_PER_COLOR).json()

    listed = client.get("/api/thresholds", params={"metric": "ng_rate"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    got = client.get(f"/api/thresholds/{created['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == created["id"]

    assert client.get("/api/thresholds/999999").status_code == 404


@pytest.mark.api
def test_patch_updates_value(client: TestClient) -> None:
    created = client.post("/api/thresholds", json=_PER_COLOR).json()
    res = client.patch(f"/api/thresholds/{created['id']}", json={"value_pct": 7.5})
    assert res.status_code == 200
    assert res.json()["value_pct"] == 7.5


@pytest.mark.api
def test_effective_resolves(client: TestClient) -> None:
    client.post("/api/thresholds", json=_PER_COLOR)
    res = client.get(
        "/api/thresholds/effective",
        params={
            "metric": "ng_rate",
            "color_no": "501",
            "size": "05",
            "chain": "CZT8",
            "tape": "",
            "at": "2026-01-15T00:00:00Z",
        },
    )
    assert res.status_code == 200
    assert res.json()["scope"] == "per_color"


@pytest.mark.api
def test_effective_404_when_none(client: TestClient) -> None:
    res = client.get(
        "/api/thresholds/effective",
        params={
            "metric": "ng_rate",
            "color_no": "999",
            "size": "05",
            "chain": "CZT8",
            "tape": "",
            "at": "2026-01-15T00:00:00Z",
        },
    )
    assert res.status_code == 404


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
        with TestClient(app) as test_client:
            assert test_client.get("/api/thresholds").status_code == 401
    finally:
        app.dependency_overrides.clear()
