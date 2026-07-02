"""ダッシュボード API（dashboard R1–R7）の api テスト。

trends / summary / records / threshold-overlay / machines のステータス・系列形状・
NULL 表現・号機フィルタ・認証ゲート・業者 DB 接続断時の挙動。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

D1 = date(2026, 7, 1)


def _seed_daily(db: Session) -> None:
    from src.repositories.daily_metrics_repository import (
        DailyMetricRow,
        DailyMetricsRepository,
    )

    DailyMetricsRepository(db).upsert_day(
        D1,
        [
            DailyMetricRow("501", "05", "CZT8", "", "1", 10, 2, 1, 1, 5),
            DailyMetricRow("501", "05", "CZT8", "", "2", 4, 0, 0, 0, 2),
        ],
    )


def _seed_image(inspection: Session) -> None:
    inspection.execute(
        text(
            "INSERT INTO annotation.image_base "
            "(image_id, inspect_timestamp, unit, camera_model, judgment_result, extra_info) "
            "VALUES (1, :ts, '1', 'camera1_image', 0, CAST(:e AS jsonb))"
        ),
        {
            "ts": datetime(2026, 7, 1, 10, 0, 0),
            "e": json.dumps({"colorNo": "501", "size": "05", "chain": "CZT8", "tape": ""}),
        },
    )
    inspection.flush()


@pytest.fixture
def client(
    db_session: Session, inspection_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    from src import config, main
    from src.database import get_db, get_inspection_db

    monkeypatch.setattr(config.settings, "ENABLE_BASIC_AUTH", False)
    app = main.create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_inspection_db] = lambda: inspection_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _range() -> dict[str, str]:
    return {"from": "2026-07-01", "to": "2026-07-03"}


@pytest.mark.api
def test_trends_returns_series(client: TestClient, db_session: Session) -> None:
    _seed_daily(db_session)
    res = client.get(
        "/api/dashboard/trends",
        params={**_range(), "color_no": "501", "size": "05", "chain": "CZT8", "tape": ""},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["throughput"] == 14  # 10 + 4（全号機合算）
    assert body[0]["ng_rate"] == pytest.approx(2 / 14)


@pytest.mark.api
def test_trends_machine_filter(client: TestClient, db_session: Session) -> None:
    _seed_daily(db_session)
    res = client.get(
        "/api/dashboard/trends",
        params={
            **_range(),
            "color_no": "501",
            "size": "05",
            "chain": "CZT8",
            "tape": "",
            "machine_ids": ["1"],
        },
    )
    assert res.status_code == 200
    assert res.json()[0]["throughput"] == 10  # unit=1 のみ


@pytest.mark.api
def test_summary_returns(client: TestClient, db_session: Session) -> None:
    _seed_daily(db_session)
    res = client.get("/api/dashboard/summary", params=_range())
    assert res.status_code == 200
    assert res.json()["throughput"] == 14


@pytest.mark.api
def test_records_returns(client: TestClient, inspection_session: Session) -> None:
    _seed_image(inspection_session)
    res = client.get("/api/dashboard/records", params=_range())
    assert res.status_code == 200
    body = res.json()
    assert len(body["records"]) == 1
    assert body["records"][0]["image_id"] == 1


@pytest.mark.api
def test_overlay_returns(client: TestClient, db_session: Session) -> None:
    from src.schemas.threshold import ThresholdCreate
    from src.services.threshold_service import ThresholdService

    ThresholdService(db_session).create(
        ThresholdCreate(
            metric="ng_rate",
            scope="global",
            value_pct=5.0,
            valid_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
            valid_to=datetime(2026, 7, 4, tzinfo=timezone.utc),
        )
    )
    res = client.get(
        "/api/dashboard/threshold-overlay",
        params={
            "metric": "ng_rate",
            "color_no": "501",
            "size": "05",
            "chain": "CZT8",
            "tape": "",
            **_range(),
        },
    )
    assert res.status_code == 200
    assert len(res.json()) == 3  # D1..D3 各日


@pytest.mark.api
def test_machines_returns(client: TestClient, db_session: Session) -> None:
    _seed_daily(db_session)
    res = client.get("/api/dashboard/machines")
    assert res.status_code == 200
    assert {m["unit"] for m in res.json()} == {"1", "2"}


@pytest.mark.api
def test_invalid_period_returns_422(client: TestClient) -> None:
    res = client.get("/api/dashboard/trends", params={"from": "2026-07-03", "to": "2026-07-01"})
    assert res.status_code == 422


@pytest.mark.api
def test_records_503_when_inspection_down(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import config, main
    from src.database import get_db, get_inspection_db

    monkeypatch.setattr(config.settings, "ENABLE_BASIC_AUTH", False)
    dead = create_engine("postgresql+psycopg2://x:x@127.0.0.1:59999/none")
    dead_session = Session(bind=dead)

    app = main.create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_inspection_db] = lambda: dead_session
    try:
        with TestClient(app) as test_client:
            res = test_client.get("/api/dashboard/records", params=_range())
        assert res.status_code == 503
    finally:
        app.dependency_overrides.clear()
        dead_session.close()
        dead.dispose()


@pytest.mark.api
def test_requires_auth_when_enabled(
    db_session: Session, inspection_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import config, main
    from src.database import get_db, get_inspection_db

    monkeypatch.setattr(config.settings, "ENABLE_BASIC_AUTH", True)
    monkeypatch.setattr(config.settings, "BASIC_AUTH_USER", "shisui")
    monkeypatch.setattr(config.settings, "BASIC_AUTH_PASS", "secret")
    app = main.create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_inspection_db] = lambda: inspection_session
    try:
        with TestClient(app) as test_client:
            assert test_client.get("/api/dashboard/machines").status_code == 401
    finally:
        app.dependency_overrides.clear()
