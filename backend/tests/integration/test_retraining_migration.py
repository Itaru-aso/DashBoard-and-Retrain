"""再学習 `retraining_job` / `deployed_model` マイグレーション（retraining M-R7, M-R8.3）の integration テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[2]


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
            job_cols = {c["name"] for c in inspect(engine).get_columns("retraining_job")}
            deployed_cols = {c["name"] for c in inspect(engine).get_columns("deployed_model")}
        finally:
            engine.dispose()
        assert {
            "id",
            "color_no",
            "size",
            "chain",
            "tape",
            "status",
            "queued_at",
            "started_at",
            "finished_at",
            "error_message",
            "onnx_monochro_path",
            "onnx_color_path",
            "created_by",
            "created_at",
            "updated_at",
        } <= job_cols
        assert {
            "id",
            "color_no",
            "size",
            "chain",
            "tape",
            "job_id",
            "onnx_monochro_path",
            "onnx_color_path",
            "deploy_status",
            "deploy_detail",
            "deployed_at",
            "updated_at",
        } <= deployed_cols

        command.downgrade(_cfg(), "0006_create_edge_pc")
        engine2 = create_engine(url)
        try:
            names = inspect(engine2).get_table_names()
        finally:
            engine2.dispose()
        assert "retraining_job" not in names
        assert "deployed_model" not in names


@pytest.mark.integration
def test_deployed_model_tuple_unique_rejected(db_session: Session) -> None:
    job_id = db_session.execute(
        text(
            "INSERT INTO retraining_job (color_no, size, chain, tape, status) "
            "VALUES ('001', '05', 'CZT8', '', 'COMPLETED') RETURNING id"
        )
    ).scalar_one()
    insert_deployed = text(
        "INSERT INTO deployed_model (color_no, size, chain, tape, job_id) "
        "VALUES ('001', '05', 'CZT8', '', :job_id)"
    )
    db_session.execute(insert_deployed, {"job_id": job_id})
    with pytest.raises(IntegrityError):
        db_session.execute(insert_deployed, {"job_id": job_id})


@pytest.mark.integration
def test_job_status_check_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO retraining_job (color_no, size, chain, tape, status) "
                "VALUES ('001', '05', 'CZT8', '', 'INVALID')"
            )
        )
