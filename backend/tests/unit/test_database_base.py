"""ver2 declarative `Base`（F3）の unit テスト。

ver2 の `Base` は Alembic 管理対象の宣言基盤であり、業者検査 DB（app_db）の
外部テーブルを**含まない**ことを確認する（ver2 テーブルは各機能が随時追加する）。
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_ver2_base_excludes_external_tables() -> None:
    """ver2 Base のメタデータに業者検査 DB の外部テーブルが載らない。"""
    import src.models.external  # noqa: F401  ExternalBase 側へ登録（副作用）
    from src.database import Base

    # 外部テーブル（annotation.image_base）は ExternalBase 側であり ver2 Base には無い。
    assert "annotation.image_base" not in Base.metadata.tables
    assert "image_base" not in Base.metadata.tables
