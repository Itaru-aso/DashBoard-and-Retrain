"""業者外部モデル基盤（F4）の integration テスト。

外部モデルを import して `ExternalBase` に登録した状態でも、Alembic autogenerate
（ver2 `Base.metadata` と空ベースライン適用済み DB の比較）が**外部テーブルを対象に
しない**ことを確認する。差分が空であれば、外部テーブルは ver2 の管理対象に漏れていない。
"""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Engine


@pytest.mark.integration
def test_external_models_not_in_ver2_autogenerate(ver2_engine: Engine) -> None:
    """外部モデル登録後も ver2 Base の autogenerate 差分は空（外部テーブルは対象外）。"""
    # 外部モデルを import して ExternalBase に登録する（副作用）。
    import src.models.external  # noqa: F401
    from src.database import Base

    with ver2_engine.connect() as conn:
        context = MigrationContext.configure(conn)
        diffs = compare_metadata(context, Base.metadata)

    # 空ベースライン適用済み DB と ver2 Base（空）の差分は無い。
    # 外部テーブルが Base に載っていれば add_table 差分が出るはず。
    assert diffs == []
