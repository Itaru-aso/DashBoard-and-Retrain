"""日次集計テーブル `daily_metrics` マイグレーション（A-R1）の integration テスト。

- upgrade で ver2 DB に `daily_metrics` が作られ、期待する列とユニーク制約
  `(jst_date, color_no, size, chain, tape, unit)` を持つ。
- ユニーク制約: 同一タプル2回目の挿入で IntegrityError。
- downgrade で `daily_metrics` が消える。

Postgres 固有（timestamptz・server_default now()）に忠実であるため、使い捨ての
Postgres コンテナを立てて upgrade/downgrade を検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

# tests/integration/ -> tests/ -> backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]

_IDENTITY = {"jst_date", "color_no", "size", "chain", "tape", "unit"}
_EXPECTED_COLUMNS = _IDENTITY | {
    "id",
    "monochro_count",
    "ng_count",
    "fp_num",
    "miss_num",
    "annotated_count",
    "computed_at",
}

_INSERT = (
    "INSERT INTO daily_metrics "
    "(jst_date, color_no, size, chain, tape, unit, "
    "monochro_count, ng_count, fp_num, miss_num, annotated_count) "
    "VALUES ('2026-07-01', '501', '05', 'CZT8', '', '1', 10, 1, 0, 0, 5)"
)


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


@pytest.mark.integration
def test_daily_metrics_migration_upgrade_unique_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """upgrade で列・ユニーク制約を作り、重複で IntegrityError、downgrade で消える。"""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:14") as postgres:
        url = postgres.get_connection_url()
        monkeypatch.setenv("DATABASE_URL", url)
        cfg = _alembic_config()

        command.upgrade(cfg, "head")

        engine = create_engine(url)
        try:
            insp = inspect(engine)
            assert "daily_metrics" in insp.get_table_names()

            columns = {c["name"] for c in insp.get_columns("daily_metrics")}
            assert _EXPECTED_COLUMNS <= columns

            uniques = insp.get_unique_constraints("daily_metrics")
            assert any(set(u["column_names"]) == _IDENTITY for u in uniques)

            # 同一タプルの2回目は IntegrityError（tape は空文字で保持）
            with engine.begin() as conn:
                conn.execute(text(_INSERT))
            with pytest.raises(IntegrityError):
                with engine.begin() as conn:
                    conn.execute(text(_INSERT))
        finally:
            engine.dispose()

        command.downgrade(cfg, "0001_empty_baseline")

        engine2 = create_engine(url)
        try:
            assert "daily_metrics" not in inspect(engine2).get_table_names()
        finally:
            engine2.dispose()
