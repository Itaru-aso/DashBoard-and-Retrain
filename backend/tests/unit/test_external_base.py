"""業者外部モデル基盤 `src.models.external`（F4）の unit テスト。

- `ExternalBase` は ver2 の `Base` とは別の宣言基盤である。
- サンプル読み取り専用モデルは `ExternalBase.metadata` のみに登録され、
  `Base.metadata`（Alembic の target_metadata）には入らない。
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_external_base_is_separate_from_ver2_base() -> None:
    """ExternalBase は ver2 Base と別基盤（metadata も別）。"""
    from src.database import Base
    from src.models.external.base import ExternalBase

    assert ExternalBase is not Base
    assert ExternalBase.metadata is not Base.metadata


@pytest.mark.unit
def test_sample_external_model_registered_only_on_external_metadata() -> None:
    """サンプル外部モデルは ExternalBase 側だけに載り、ver2 Base には載らない。"""
    from src.database import Base
    from src.models.external.base import ExternalBase
    from src.models.external.image_base import ImageBase

    assert ImageBase.__tablename__ == "image_base"
    assert "annotation.image_base" in ExternalBase.metadata.tables
    assert "annotation.image_base" not in Base.metadata.tables
