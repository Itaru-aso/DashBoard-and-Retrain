"""閾値テーブル `threshold` マイグレーション（R1.2–R1.5, R3.5）の integration テスト。

- upgrade で threshold が作られ、downgrade で消える。
- 制約が効く: 期間重複（per_color / global）・値域外・期間逆転・スコープ不整合の
  INSERT が DB に弾かれる（最終保証は DB 制約）。

btree_gist 排他制約に忠実であるため使い捨て Postgres コンテナで検証する。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

# tests/integration/ -> tests/ -> backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]

_VALID_PER_COLOR = (
    "INSERT INTO threshold (metric, scope, color_no, size, chain, tape, value_pct, "
    "valid_from, valid_to) VALUES ('ng_rate', 'per_color', '501', '05', 'CZT8', '', "
    "5.0, '2026-01-01 00:00:00+00', '2026-02-01 00:00:00+00')"
)


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


@pytest.fixture(scope="module")
def threshold_engine() -> Iterator[Engine]:
    """threshold まで upgrade 済みの使い捨て Postgres（module 共有・制約検証用）。"""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:14") as postgres:
        url = postgres.get_connection_url()
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        try:
            command.upgrade(_alembic_config(), "head")
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
        engine = create_engine(url)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def conn(threshold_engine: Engine) -> Iterator[Connection]:
    """挿入を試して ROLLBACK する接続（制約検証を隔離）。"""
    connection = threshold_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.mark.integration
def test_migration_upgrade_and_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    """upgrade で threshold が列付きで作られ、downgrade で消える。"""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:14") as postgres:
        url = postgres.get_connection_url()
        monkeypatch.setenv("DATABASE_URL", url)
        cfg = _alembic_config()

        command.upgrade(cfg, "head")
        engine = create_engine(url)
        try:
            columns = {c["name"] for c in inspect(engine).get_columns("threshold")}
        finally:
            engine.dispose()
        assert {
            "id",
            "metric",
            "scope",
            "color_no",
            "size",
            "chain",
            "tape",
            "value_pct",
            "valid_from",
            "valid_to",
            "created_at",
            "updated_at",
        } <= columns

        command.downgrade(cfg, "0002_create_daily_metrics")
        engine2 = create_engine(url)
        try:
            assert "threshold" not in inspect(engine2).get_table_names()
        finally:
            engine2.dispose()


@pytest.mark.integration
def test_valid_per_color_insert_succeeds(conn: Connection) -> None:
    """正常な per_color 行は挿入できる。"""
    conn.execute(text(_VALID_PER_COLOR))


@pytest.mark.integration
def test_overlapping_per_color_rejected(conn: Connection) -> None:
    """同一フルタプル・メトリクスで期間が重複する per_color は排他制約で弾く。"""
    conn.execute(text(_VALID_PER_COLOR))
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO threshold (metric, scope, color_no, size, chain, tape, "
                "value_pct, valid_from, valid_to) VALUES ('ng_rate', 'per_color', "
                "'501', '05', 'CZT8', '', 7.0, '2026-01-15 00:00:00+00', "
                "'2026-03-01 00:00:00+00')"
            )
        )


@pytest.mark.integration
def test_overlapping_global_rejected(conn: Connection) -> None:
    """同一メトリクスで期間が重複する global は排他制約で弾く（NULL 色でも検出）。"""
    conn.execute(
        text(
            "INSERT INTO threshold (metric, scope, value_pct, valid_from, valid_to) "
            "VALUES ('ng_rate', 'global', 5.0, '2026-01-01 00:00:00+00', "
            "'2026-02-01 00:00:00+00')"
        )
    )
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO threshold (metric, scope, value_pct, valid_from, valid_to) "
                "VALUES ('ng_rate', 'global', 6.0, '2026-01-15 00:00:00+00', "
                "'2026-03-01 00:00:00+00')"
            )
        )


@pytest.mark.integration
def test_value_out_of_range_rejected(conn: Connection) -> None:
    """value_pct が 0–100 の範囲外は CHECK で弾く。"""
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO threshold (metric, scope, value_pct, valid_from) "
                "VALUES ('ng_rate', 'global', 150.0, '2026-01-01 00:00:00+00')"
            )
        )


@pytest.mark.integration
def test_period_reversal_rejected(conn: Connection) -> None:
    """valid_to <= valid_from は CHECK で弾く。"""
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO threshold (metric, scope, value_pct, valid_from, valid_to) "
                "VALUES ('ng_rate', 'global', 5.0, '2026-02-01 00:00:00+00', "
                "'2026-01-01 00:00:00+00')"
            )
        )


@pytest.mark.integration
def test_scope_mismatch_rejected(conn: Connection) -> None:
    """global なのに色カラムが設定されている行は CHECK で弾く。"""
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO threshold (metric, scope, color_no, value_pct, valid_from) "
                "VALUES ('ng_rate', 'global', '501', 5.0, '2026-01-01 00:00:00+00')"
            )
        )
