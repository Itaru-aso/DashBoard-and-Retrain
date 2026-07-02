"""Alembic 空ベースライン（F3）の integration テスト。

`alembic upgrade head` が一時 DB に通り、空ベースライン（ver2 テーブルなし・
`alembic_version` に head 記録）が適用されることを確認する。

空ベースラインはテーブルを持たずバックエンド非依存のため、サーバ不要の一時 SQLite
を使い捨て DB として用いる（migration 検証は使い捨て DB を許容: steering test-wiring）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

# tests/integration/ -> tests/ -> backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_alembic_upgrade_head_applies_empty_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一時 SQLite に対し upgrade head が通り、空ベースラインが適用される。"""
    db_file = tmp_path / "ver2_test.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))

    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()

    # 空ベースライン: 管理テーブルは alembic_version のみ（ver2 テーブルなし）
    assert tables == {"alembic_version"}
    assert version == "0001_empty_baseline"
