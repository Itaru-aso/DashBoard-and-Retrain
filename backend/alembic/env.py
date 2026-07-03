"""Alembic 環境設定（ver2 DB のみ対象）。

- 接続 URL は環境変数 `DATABASE_URL`（ver2 DB）から取得する。
- `target_metadata` は ver2 の `Base.metadata` のみ。業者検査 DB の `ExternalBase` は
  含めない（autogenerate が業者テーブルを管理対象と誤認しないため）。
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.database import Base

# Alembic の Config オブジェクト（alembic.ini の値へアクセス）。
config = context.config

if config.config_file_name is not None:
    # Windows の既定エンコーディング(cp932)を避け、UTF-8 で ini を読む。
    fileConfig(config.config_file_name, encoding="utf-8")

# 接続先は ver2 DB（DATABASE_URL）。秘密情報は ini に書かず env から取得する。
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL が未設定です（Alembic は ver2 DB のみを対象とします）")
config.set_main_option("sqlalchemy.url", database_url)

# ver2 のみを管理対象にする（ExternalBase は含めない）。
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """オフライン（SQL 出力）モードでマイグレーションを実行する。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """オンライン（DB 接続）モードでマイグレーションを実行する。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
