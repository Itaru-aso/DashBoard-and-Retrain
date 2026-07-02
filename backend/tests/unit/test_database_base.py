"""ver2 declarative `Base`（F3）の unit テスト。

空ベースライン時点では ver2 テーブルは未定義（`Base.metadata` は空）であることを確認する。
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_ver2_base_metadata_is_empty() -> None:
    """空ベースライン: `Base.metadata` にテーブルが無い。"""
    from src.database import Base

    assert Base.metadata.tables == {}
