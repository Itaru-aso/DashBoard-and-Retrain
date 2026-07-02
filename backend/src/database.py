"""ver2 DB のデータベース基盤（F2/F3）。

- ver2 declarative `Base`（**Alembic の対象**。`alembic/env.py` の `target_metadata`）。
- 2エンジン: `ver2_engine`（読み書き）/ `inspection_engine`（業者検査 DB・読み取り専用）。
  両者に `pool_pre_ping`（接続断検知）。
- セッション: `SessionLocal`（ver2）/ `InspectionSessionLocal`（業者）。
- 依存: `get_db`（正常時 commit / 例外時 rollback / finally close）、
  `get_inspection_db`（**commit しない**・SELECT 専用・finally close）。

業者検査 DB はライブ・リモートのため接続断があり得る。`OperationalError` 等は
Repository/Service で捕捉し、呼び出し側が 503 相当で握りつぶす（アプリは落とさない。F2.3）。
業者検査 DB 用の読み取り専用モデルは別基盤 `ExternalBase`（Alembic 対象外）に載せる。
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import settings


class Base(DeclarativeBase):
    """ver2 DB（自前・読み書き）の declarative base（Alembic 管理対象）。"""


# ver2 DB（自前・読み書き）。
ver2_engine: Engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(
    bind=ver2_engine, autoflush=False, autocommit=False, expire_on_commit=False
)

# 業者検査 DB（外部・読み取り専用）。将来 read-only ユーザで接続する。
inspection_engine: Engine = create_engine(settings.INSPECTION_DATABASE_URL, pool_pre_ping=True)
InspectionSessionLocal = sessionmaker(
    bind=inspection_engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def get_db() -> Iterator[Session]:
    """ver2 DB セッションの依存（正常時 commit / 例外時 rollback / finally close）。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_inspection_db() -> Iterator[Session]:
    """業者検査 DB セッションの依存（読み取り専用・commit しない・finally close）。

    業者 DB の接続断（`OperationalError` 等）は呼び出し側で捕捉する（F2.3）。
    """
    db = InspectionSessionLocal()
    try:
        yield db
    finally:
        db.close()
