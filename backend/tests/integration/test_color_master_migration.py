"""色マスター `color_master` マイグレーション（C-R1.1）の integration テスト。

- upgrade/downgrade。
- 同一性タプルのユニーク制約（重複 INSERT を DB が弾く）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[2]

_INSERT = (
    "INSERT INTO color_master "
    "(color_no, size, chain, tape, rgb_r, rgb_g, rgb_b, lab_l, lab_a, lab_b) "
    "VALUES ('001','05','CZT8','', 10, 20, 30, 50.0, 1.0, -2.0)"
)


def _cfg() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


@pytest.mark.integration
def test_migration_upgrade_and_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:14") as pg:
        url = pg.get_connection_url()
        monkeypatch.setenv("DATABASE_URL", url)
        command.upgrade(_cfg(), "head")
        engine = create_engine(url)
        try:
            cols = {c["name"] for c in inspect(engine).get_columns("color_master")}
        finally:
            engine.dispose()
        assert {
            "id",
            "color_no",
            "size",
            "chain",
            "tape",
            "rgb_r",
            "rgb_g",
            "rgb_b",
            "lab_l",
            "lab_a",
            "lab_b",
            "status",
            "verification_at",
            "production_at",
            "created_at",
            "updated_at",
        } <= cols

        command.downgrade(_cfg(), "0004_create_task")
        engine2 = create_engine(url)
        try:
            assert "color_master" not in inspect(engine2).get_table_names()
        finally:
            engine2.dispose()


@pytest.mark.integration
def test_duplicate_tuple_rejected(db_session: Session) -> None:
    db_session.execute(text(_INSERT))
    with pytest.raises(IntegrityError):
        db_session.execute(text(_INSERT))


@pytest.mark.integration
def test_default_status_is_mijisshi(db_session: Session) -> None:
    db_session.execute(text(_INSERT))
    status = db_session.execute(
        text("SELECT status FROM color_master WHERE color_no='001'")
    ).scalar_one()
    assert status == "未実施"
