"""業者検査 DB（app_db・読み取り専用）の ORM モデル群（Alembic 対象外）。

`ExternalBase` に載る手書きモデルを配置する。import した時点で各モデルが
`ExternalBase.metadata` に登録される。
"""

from __future__ import annotations

from src.models.external.base import ExternalBase
from src.models.external.image_base import ImageBase

__all__ = ["ExternalBase", "ImageBase"]
