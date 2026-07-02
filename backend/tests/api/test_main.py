"""アプリ骨格 `src.main`（F7）の api テスト。

- 起動が通る（lifespan でスケジューラ起動/停止）。
- `/health`: ver2 DB 疎通が必須（失敗で 503・unhealthy）、業者 DB 疎通は参考
  （失敗しても 200・結果に併記）。
- `ENVIRONMENT=production`: フロント `dist/` を配信し SPA フォールバックする。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine


@pytest.mark.api
def test_health_healthy_when_ver2_up() -> None:
    """ver2・業者ともに疎通していれば 200 / healthy。"""
    from src.main import app, check_inspection_db, check_ver2_db

    app.dependency_overrides[check_ver2_db] = lambda: True
    app.dependency_overrides[check_inspection_db] = lambda: True
    try:
        with TestClient(app) as client:
            res = client.get("/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "healthy"
        assert body["ver2_db"] == "ok"
        assert body["inspection_db"] == "ok"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.api
def test_health_unhealthy_when_ver2_down() -> None:
    """ver2 DB が落ちていれば 503 / unhealthy（必須）。"""
    from src.main import app, check_inspection_db, check_ver2_db

    app.dependency_overrides[check_ver2_db] = lambda: False
    app.dependency_overrides[check_inspection_db] = lambda: True
    try:
        with TestClient(app) as client:
            res = client.get("/health")
        assert res.status_code == 503
        body = res.json()
        assert body["status"] == "unhealthy"
        assert body["ver2_db"] == "error"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.api
def test_health_inspection_is_reference_only() -> None:
    """業者 DB が落ちていても致命にしない（200・unavailable を併記）。"""
    from src.main import app, check_inspection_db, check_ver2_db

    app.dependency_overrides[check_ver2_db] = lambda: True
    app.dependency_overrides[check_inspection_db] = lambda: False
    try:
        with TestClient(app) as client:
            res = client.get("/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "healthy"
        assert body["inspection_db"] == "unavailable"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.api
def test_production_serves_spa_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """本番は dist/ を配信し、未知パスは index.html に SPA フォールバックする。"""
    from src import config, main

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa-root</html>", encoding="utf-8")

    monkeypatch.setattr(config.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(main, "FRONTEND_DIST", dist)

    app = main.create_app()
    with TestClient(app) as client:
        spa = client.get("/some/client/route")
        assert spa.status_code == 200
        assert "spa-root" in spa.text


@pytest.mark.integration
def test_health_healthy_against_real_db(
    ver2_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """実 DB（テストコンテナ）疎通で /health が healthy を返す（疎通確認の実経路）。"""
    from src import database, main

    # 業者検査 DB はテストコンテナを代役にする（実 app_db スナップショットは各機能）。
    monkeypatch.setattr(database, "ver2_engine", ver2_engine)
    monkeypatch.setattr(database, "inspection_engine", ver2_engine)

    with TestClient(main.app) as client:
        res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


@pytest.mark.unit
def test_check_ver2_db_false_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """ver2 DB 到達不能時は疎通確認が False（例外を握りつぶす）。"""
    from sqlalchemy import create_engine

    from src import database, main

    dead = create_engine("postgresql+psycopg2://x:x@127.0.0.1:59999/none")
    monkeypatch.setattr(database, "ver2_engine", dead)
    try:
        assert main.check_ver2_db() is False
    finally:
        dead.dispose()


@pytest.mark.unit
def test_check_inspection_db_false_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """業者 DB 到達不能時は疎通確認が False（参考・非致命）。"""
    from sqlalchemy import create_engine

    from src import database, main

    dead = create_engine("postgresql+psycopg2://x:x@127.0.0.1:59999/none")
    monkeypatch.setattr(database, "inspection_engine", dead)
    try:
        assert main.check_inspection_db() is False
    finally:
        dead.dispose()
