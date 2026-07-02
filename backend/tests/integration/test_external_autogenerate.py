"""業者外部モデル基盤（F4）の integration テスト。

外部モデルを import して `ExternalBase` に登録した状態でも、Alembic autogenerate
（ver2 `Base.metadata` と DB の比較）が**外部テーブル（annotation.image_base）を対象に
しない**ことを確認する。差分に外部テーブルが現れなければ、外部テーブルは ver2 の
管理対象に漏れていない（ver2 テーブルの差分有無は本テストの対象外）。
"""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Engine


@pytest.mark.integration
def test_external_models_not_in_ver2_autogenerate(ver2_engine: Engine) -> None:
    """外部モデル登録後も ver2 Base の autogenerate 差分に外部テーブルが現れない。"""
    # 外部モデルを import して ExternalBase に登録する（副作用）。
    import src.models.external  # noqa: F401
    from src.database import Base

    with ver2_engine.connect() as conn:
        context = MigrationContext.configure(conn)
        diffs = compare_metadata(context, Base.metadata)

    # 外部テーブル（annotation.image_base）が Base に載っていれば差分に現れるはず。
    # ver2 テーブル（daily_metrics 等）の差分有無は本テストの対象外。
    assert "image_base" not in repr(diffs)
