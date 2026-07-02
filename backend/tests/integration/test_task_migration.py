"""保守タスク `task` テーブル マイグレーション（task R2.5）の integration テスト。

- upgrade/downgrade。
- 部分ユニーク: 同キーのアクティブ（OPEN/IN_PROGRESS）は高々1件。DONE は重複可（再発履歴）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _cfg() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def _insert(conn: Connection | Session, status: str) -> None:
    conn.execute(
        text(
            "INSERT INTO task "
            "(color_no, size, chain, tape, task_type, status, detected_value, "
            "threshold_value, evaluation_date, comments) "
            "VALUES ('501','05','CZT8','','ng_rate',:st, 6.0, 5.0, '2026-07-01', '[]')"
        ),
        {"st": status},
    )


@pytest.mark.integration
def test_migration_upgrade_and_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:14") as pg:
        url = pg.get_connection_url()
        monkeypatch.setenv("DATABASE_URL", url)
        command.upgrade(_cfg(), "head")
        engine = create_engine(url)
        try:
            cols = {c["name"] for c in inspect(engine).get_columns("task")}
        finally:
            engine.dispose()
        assert {
            "id",
            "color_no",
            "size",
            "chain",
            "tape",
            "task_type",
            "status",
            "detected_value",
            "threshold_value",
            "evaluation_date",
            "comments",
            "created_at",
            "updated_at",
        } <= cols

        command.downgrade(_cfg(), "0003_create_threshold")
        engine2 = create_engine(url)
        try:
            assert "task" not in inspect(engine2).get_table_names()
        finally:
            engine2.dispose()


@pytest.mark.integration
def test_active_duplicate_rejected(db_session: Session) -> None:
    _insert(db_session, "OPEN")
    with pytest.raises(IntegrityError):
        _insert(db_session, "IN_PROGRESS")  # 同キーの2件目アクティブ


@pytest.mark.integration
def test_done_duplicates_allowed(db_session: Session) -> None:
    _insert(db_session, "DONE")
    _insert(db_session, "DONE")  # DONE は部分ユニーク対象外＝重複可
    count = db_session.execute(text("SELECT COUNT(*) FROM task WHERE status='DONE'")).scalar_one()
    assert count == 2
