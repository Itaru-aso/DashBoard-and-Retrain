"""エッジPC `edge_pc` マイグレーション（edge E-R1）の integration テスト。"""

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
    "INSERT INTO edge_pc (name, host, username, password, model_port, enabled) "
    "VALUES ('検査PC_1', '169.254.93.171', 'ykk\\\\shisui', 'pw', 2123, true)"
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
            cols = {c["name"] for c in inspect(engine).get_columns("edge_pc")}
        finally:
            engine.dispose()
        assert {
            "id",
            "name",
            "host",
            "username",
            "password",
            "model_port",
            "enabled",
            "last_ftp_ok",
            "last_ftp_checked_at",
            "created_at",
            "updated_at",
        } <= cols

        command.downgrade(_cfg(), "0005_create_color_master")
        engine2 = create_engine(url)
        try:
            assert "edge_pc" not in inspect(engine2).get_table_names()
        finally:
            engine2.dispose()


@pytest.mark.integration
def test_name_unique_rejected(db_session: Session) -> None:
    db_session.execute(text(_INSERT))
    with pytest.raises(IntegrityError):
        db_session.execute(text(_INSERT))
