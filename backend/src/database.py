"""ver2 DB のデータベース基盤（F2/F3）。

本タスク（F3）では ver2 の declarative `Base` のみを定義する。
2エンジン（ver2 / 業者検査 DB）のエンジン・セッション・DI は後続タスク（F2）で追加する。

`Base` は **Alembic の対象**（`alembic/env.py` の `target_metadata`）。
業者検査 DB 用の読み取り専用モデルは別基盤 `ExternalBase`（Alembic 対象外）に載せる。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """ver2 DB（自前・読み書き）の declarative base（Alembic 管理対象）。"""
