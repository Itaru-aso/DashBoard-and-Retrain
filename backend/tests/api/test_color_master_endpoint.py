"""色マスター API（color C-R1, C-R5, C-R6）の api テスト。"""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

TUPLE = dict(color_no="001", size="05", chain="CZT8", tape="")


def _seed(db: Session):
    from src.repositories.color_master_repository import ColorMasterRepository

    return ColorMasterRepository(db).create(**TUPLE, rgb_r=1)


def _xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(
        ["status", "size", "chain", "tape", "color_no", "R", "G", "B", "L", "a", "b", "update_date"]
    )
    ws.append(["", "05", "CZT8", "", "002", 10, 20, 30, 1.0, 2.0, 3.0, ""])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


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
    color = _seed(db_session)
    listed = client.get("/api/colors", params={"status": "未実施"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    got = client.get(f"/api/colors/{color.id}")
    assert got.status_code == 200
    assert got.json()["color_no"] == "001"


@pytest.mark.api
def test_import(client: TestClient) -> None:
    res = client.post(
        "/api/colors/import",
        files={
            "file": (
                "colors.xlsx",
                _xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert res.status_code == 200
    assert res.json()["created"] == 1


@pytest.mark.api
def test_patch_updates_sample_but_not_status(client: TestClient, db_session: Session) -> None:
    color = _seed(db_session)
    # status を送っても無視され、色見本のみ更新される
    res = client.patch(f"/api/colors/{color.id}", json={"rgb_r": 99, "status": "実生産"})
    assert res.status_code == 200
    body = res.json()
    assert body["rgb_r"] == 99
    assert body["status"] == "未実施"  # 手動変更不可


@pytest.mark.api
def test_evaluate(client: TestClient) -> None:
    res = client.post("/api/colors/evaluate", json={})
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
            assert c.get("/api/colors").status_code == 401
    finally:
        app.dependency_overrides.clear()
