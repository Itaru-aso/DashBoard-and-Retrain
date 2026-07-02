"""テスト共有 fixture とテスト配線（F9）。

提供する fixture:
    - `ver2_db_url`: ver2 テスト DB の接続 URL（migration 適用済み）。
      `TEST_DATABASE_URL` があればそれを使い、無ければ使い捨ての Postgres コンテナを
      起動する（認証情報はコンテナが自動生成。ローカル/CI とも Docker があれば動く）。
    - `ver2_engine`: 上記 URL の SQLAlchemy Engine（session スコープ）。
    - `db_session`: 各テストを接続＋トランザクションで囲み、終了時に ROLLBACK して
      隔離する Session（migration を正・テスト間でデータが残らない）。

マーカー（unit / integration / api）は `pyproject.toml` に登録済み。

TODO（依存タスク完了後に追加）:
    - `client`（TestClient）fixture: FastAPI app（F7・task10）と `get_db`（F2・task6）
      の完成後に、DB 依存をテスト DB へ差し替えて提供する。
    - 業者検査 DB 相当（dump 由来スナップショット）fixture: 業者外部モデル（F4・task7）
      と実 dump 入手後に追加する（ライブ DB は再現不可のため固定スナップショットを使う）。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# src.config / src.database の import 時 fail-fast を防ぐための安全な既定 env。
# 実 env（CI の DATABASE_URL 等）は setdefault のため上書きしない。個別テストは
# monkeypatch で上書き/削除できる（設定の fail-fast テスト等）。
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test:test@localhost:5432/ver2_test")
os.environ.setdefault(
    "INSPECTION_DATABASE_URL", "postgresql+psycopg2://test:test@localhost:5432/app_db_test"
)

# tests/ -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    """backend/ 配下の alembic 設定を絶対パスで組み立てる。"""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def _apply_migrations(url: str) -> None:
    """指定 URL の DB に ver2 の migration を head まで適用する（migration を正）。"""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url  # alembic/env.py が読む
    try:
        command.upgrade(_alembic_config(), "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture(scope="session")
def ver2_db_url() -> Iterator[str]:
    """ver2 テスト DB の接続 URL を供給する（migration 適用済み）。

    `TEST_DATABASE_URL` があればそれを使う（CI のサービス DB 等）。無ければ使い捨ての
    Postgres コンテナを起動し、認証情報をコンテナに自動生成させる。
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        _apply_migrations(explicit)
        yield explicit
        return

    # 遅延 import: TEST_DATABASE_URL 経由の実行（CI 等）では testcontainers を要求しない。
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:14") as postgres:
        url = postgres.get_connection_url()
        _apply_migrations(url)
        yield url


@pytest.fixture(scope="session")
def ver2_engine(ver2_db_url: str) -> Iterator[Engine]:
    """ver2 テスト DB の Engine（session スコープで使い回す）。"""
    engine = create_engine(ver2_db_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(ver2_engine: Engine) -> Iterator[Session]:
    """各テストを接続＋トランザクションで囲み、終了時に ROLLBACK して隔離する。"""
    connection = ver2_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
