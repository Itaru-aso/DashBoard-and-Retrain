"""テスト共有 fixture とテスト配線（F9）。

提供する fixture:
    - `ver2_db_url`: ver2 テスト DB の接続 URL（migration 適用済み）。
      `TEST_DATABASE_URL` があればそれを使い、無ければ使い捨ての Postgres コンテナを
      起動する（認証情報はコンテナが自動生成。ローカル/CI とも Docker があれば動く）。
    - `ver2_engine`: 上記 URL の SQLAlchemy Engine（session スコープ）。
    - `db_session`: 各テストを接続＋トランザクションで囲み、終了時に ROLLBACK して
      隔離する Session（migration を正・テスト間でデータが残らない）。
    - `inspection_engine` / `inspection_session`: 業者検査 DB（app_db）代役。使い捨ての
      Postgres コンテナに schema-spec-mapping 準拠の最小スキーマ（admin/annotation）を
      作成した合成代役（実 dump 入手後に差し替え可能）。inspection_session は ROLLBACK 隔離。

マーカー（unit / integration / api）は `pyproject.toml` に登録済み。

TODO（依存タスク完了後に追加）:
    - `client`（TestClient）fixture: FastAPI app（F7・task10）と `get_db`（F2・task6）
      の完成後に、DB 依存をテスト DB へ差し替えて提供する。
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

# testcontainers の Ryuk（リソース回収コンテナ）を無効化する。コンテナはコンテキスト
# マネージャで明示停止するため Ryuk は不要で、その起動失敗（ポート割当の断続エラー）を避ける。
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

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


# 業者検査 DB（app_db）代役の最小スキーマ（schema-spec-mapping.md 準拠。集計に必要な列のみ）。
_INSPECTION_SCHEMA_DDL = (
    "CREATE SCHEMA IF NOT EXISTS admin",
    "CREATE SCHEMA IF NOT EXISTS annotation",
    (
        "CREATE TABLE annotation.image_base ("
        " image_id bigint PRIMARY KEY,"
        " inspect_timestamp timestamp NOT NULL,"
        " unit text,"
        " camera_model text,"
        " judgment_result integer,"
        " extra_info jsonb)"
    ),
    (
        "CREATE TABLE annotation.annotation_item ("
        " id bigserial PRIMARY KEY,"
        " image_id bigint NOT NULL,"
        " dataset_id integer NOT NULL,"
        " item_id integer NOT NULL,"
        " use_flg boolean)"
    ),
    (
        "CREATE TABLE admin.dataset_category_item ("
        " dataset_id integer NOT NULL,"
        " item_id integer NOT NULL,"
        " on_class text,"
        " PRIMARY KEY (dataset_id, item_id))"
    ),
)


@pytest.fixture(scope="session")
def inspection_engine() -> Iterator[Engine]:
    """業者検査 DB（app_db）代役の Engine（合成スキーマ作成済み・使い捨てコンテナ）。"""
    from sqlalchemy import text
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:14") as postgres:
        engine = create_engine(postgres.get_connection_url())
        with engine.begin() as conn:
            for ddl in _INSPECTION_SCHEMA_DDL:
                conn.execute(text(ddl))
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def inspection_session(inspection_engine: Engine) -> Iterator[Session]:
    """app_db 代役の Session（ROLLBACK 隔離。seed と読み取りを同一トランザクションで行う）。"""
    connection = inspection_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
