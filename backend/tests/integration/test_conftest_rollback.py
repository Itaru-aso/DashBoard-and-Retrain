"""conftest のテスト配線（F9）の integration テスト。

`db_session` fixture が各テストを**トランザクション ROLLBACK**で隔離し、
テスト間でデータが残らないことを確認する。

検証用の使い捨てテーブル `t_rollback_probe` を migration 外で作成/破棄し、
2つのテストがそれぞれ「開始時 0 件 → 1 件挿入」を満たすことで隔離を示す
（隔離が壊れていれば後続テストが開始時 1 件を観測して失敗する）。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

_meta = MetaData()
_probe = Table(
    "t_rollback_probe",
    _meta,
    Column("id", Integer, primary_key=True),
    Column("val", String(20)),
)


@pytest.fixture(scope="module", autouse=True)
def _probe_table(ver2_engine: Engine) -> Iterator[None]:
    """使い捨て検証テーブルを（per-test トランザクション外で）作成・破棄する。"""
    _meta.create_all(ver2_engine)
    yield
    _meta.drop_all(ver2_engine)


def _count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(_probe)) or 0


@pytest.mark.integration
def test_rollback_isolation_first(db_session: Session) -> None:
    """開始時は空。1件挿入するとそのトランザクション内では1件見える。"""
    assert _count(db_session) == 0
    db_session.execute(insert(_probe).values(val="a"))
    assert _count(db_session) == 1


@pytest.mark.integration
def test_rollback_isolation_second(db_session: Session) -> None:
    """前テストの挿入が ROLLBACK されており、開始時は再び空。"""
    assert _count(db_session) == 0
    db_session.execute(insert(_probe).values(val="b"))
    assert _count(db_session) == 1
