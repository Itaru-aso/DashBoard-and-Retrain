"""集計トリガー API `POST /api/aggregation/run`（A-R2/A-R4）の api テスト。

- 単日（date）/ 期間（from,to）で集計を起動できる。
- Basic 認証を要求する（有効時、資格なしは 401）。
- date も from/to も無ければバリデーションエラー（422）。

get_db / get_inspection_db をテスト用セッション（ver2 / app_db 代役）へ override する。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

D1 = date(2026, 7, 1)
D2 = date(2026, 7, 2)


def _seed_one(session: Session, image_id: int, day: date) -> None:
    """monochro・正解OK の画像を1件投入する（代役）。"""
    session.execute(
        text(
            "INSERT INTO admin.dataset_category_item (dataset_id, item_id, on_class) "
            "VALUES (1, 10, '0') ON CONFLICT DO NOTHING"
        )
    )
    session.execute(
        text(
            "INSERT INTO annotation.image_base "
            "(image_id, inspect_timestamp, unit, camera_model, judgment_result, extra_info) "
            "VALUES (:id, :ts, '1', 'camera1_image', 0, CAST(:extra AS jsonb))"
        ),
        {
            "id": image_id,
            "ts": datetime(day.year, day.month, day.day, 10, 0, 0),
            "extra": json.dumps({"colorNo": "501", "size": "05", "chain": "CZT8", "tape": ""}),
        },
    )
    session.execute(
        text(
            "INSERT INTO annotation.annotation_item (image_id, dataset_id, item_id, use_flg) "
            "VALUES (:img, 1, 10, true)"
        ),
        {"img": image_id},
    )
    session.flush()


@pytest.fixture
def client(
    db_session: Session, inspection_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """集計 API を載せた app（DI をテストセッションへ差し替え）。既定は認証無効。"""
    from src import config, main
    from src.database import get_db, get_inspection_db

    monkeypatch.setattr(config.settings, "ENABLE_BASIC_AUTH", False)
    app = main.create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_inspection_db] = lambda: inspection_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.api
def test_run_single_day(
    client: TestClient, db_session: Session, inspection_session: Session
) -> None:
    """date 指定で単日集計が走り、daily_metrics に反映される。"""
    from src.repositories.daily_metrics_repository import DailyMetricsRepository

    _seed_one(inspection_session, 1, D1)

    res = client.post("/api/aggregation/run", json={"date": "2026-07-01"})
    assert res.status_code == 200

    assert len(DailyMetricsRepository(db_session).read(D1, D1)) == 1


@pytest.mark.api
def test_run_range(client: TestClient, db_session: Session, inspection_session: Session) -> None:
    """from,to 指定で期間集計（バックフィル）が走る。"""
    from src.repositories.daily_metrics_repository import DailyMetricsRepository

    _seed_one(inspection_session, 1, D1)
    _seed_one(inspection_session, 2, D2)

    res = client.post("/api/aggregation/run", json={"from": "2026-07-01", "to": "2026-07-02"})
    assert res.status_code == 200

    repo = DailyMetricsRepository(db_session)
    assert len(repo.read(D1, D1)) == 1
    assert len(repo.read(D2, D2)) == 1


@pytest.mark.api
def test_validation_error_when_no_params(client: TestClient) -> None:
    """date も from/to も無ければ 422。"""
    res = client.post("/api/aggregation/run", json={})
    assert res.status_code == 422


@pytest.mark.api
def test_validation_error_when_from_after_to(client: TestClient) -> None:
    """from が to より後なら 422。"""
    res = client.post("/api/aggregation/run", json={"from": "2026-07-02", "to": "2026-07-01"})
    assert res.status_code == 422


@pytest.mark.api
def test_requires_auth_when_enabled(
    db_session: Session, inspection_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """認証有効時、資格なしは 401。"""
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
            res = test_client.post("/api/aggregation/run", json={"date": "2026-07-01"})
        assert res.status_code == 401
    finally:
        app.dependency_overrides.clear()
