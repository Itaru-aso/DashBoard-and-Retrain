"""2エンジン DB 接続 `src.database`（F2）の integration テスト。

- `get_db`: 正常時 commit / 例外時 rollback。
- `get_inspection_db`: 読み取りできる（commit しない）。
- 業者 DB 断: `OperationalError` を捕捉できる（アプリを落とさず握りつぶせる。F2.3）。

ver2 テスト DB（conftest の使い捨て Postgres）を用いる。業者検査 DB の読み取りは
本タスクでは同一コンテナを代役にする（実 app_db スナップショットは F4/task7 以降）。
"""

from __future__ import annotations

from collections.abc import Iterator
from types import ModuleType

import pytest
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    insert,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

_meta = MetaData()
_probe = Table(
    "t_getdb_probe",
    _meta,
    Column("id", Integer, primary_key=True),
    Column("val", String(20)),
)


def _drive_to_completion(gen: Iterator[object]) -> None:
    """ジェネレータ依存を最後まで回し、yield 後の後処理（commit/close）を実行させる。"""
    try:
        next(gen)
    except StopIteration:
        pass


@pytest.fixture
def bound_database(ver2_engine: Engine) -> Iterator[ModuleType]:
    """SessionLocal / InspectionSessionLocal をテスト用コンテナへ束ね、検証テーブルを用意する。"""
    from src import database

    database.SessionLocal.configure(bind=ver2_engine)
    database.InspectionSessionLocal.configure(bind=ver2_engine)
    _meta.create_all(ver2_engine)
    try:
        yield database
    finally:
        _meta.drop_all(ver2_engine)


def _count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(_probe)).scalar_one()


@pytest.mark.integration
def test_get_db_commits_on_success(bound_database: ModuleType, ver2_engine: Engine) -> None:
    """正常終了で commit され、別接続から挿入が見える。"""
    gen = bound_database.get_db()
    db = next(gen)
    db.execute(insert(_probe).values(val="c"))
    _drive_to_completion(gen)

    assert _count(ver2_engine) == 1


@pytest.mark.integration
def test_get_db_rolls_back_on_exception(bound_database: ModuleType, ver2_engine: Engine) -> None:
    """例外時は rollback され、別接続から挿入が見えない。"""
    gen = bound_database.get_db()
    db = next(gen)
    db.execute(insert(_probe).values(val="r"))
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))

    assert _count(ver2_engine) == 0


@pytest.mark.integration
def test_get_inspection_db_can_read(bound_database: ModuleType) -> None:
    """業者検査 DB セッションで読み取りできる（commit しない）。"""
    gen = bound_database.get_inspection_db()
    db = next(gen)
    assert db.execute(text("SELECT 1")).scalar_one() == 1
    _drive_to_completion(gen)


@pytest.mark.integration
def test_inspection_db_down_raises_operational_error() -> None:
    """業者 DB 到達不能時は OperationalError を捕捉できる（アプリは落とさない）。"""
    from src import database

    dead = create_engine("postgresql+psycopg2://x:x@127.0.0.1:59999/none", pool_pre_ping=True)
    database.InspectionSessionLocal.configure(bind=dead)
    try:
        gen = database.get_inspection_db()
        db = next(gen)
        with pytest.raises(OperationalError):
            db.execute(text("SELECT 1"))
        gen.close()
    finally:
        dead.dispose()
