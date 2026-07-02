"""業者検査 DB（app_db・読み取り専用）の宣言基盤（F4）。

`ExternalBase` は ver2 の `Base` とは**別の宣言基盤**であり、Alembic の
`target_metadata` に**含めない**（autogenerate が業者テーブルを ver2 の管理対象と
誤認しないため）。読み取り専用は「業者エンジン＋非 commit セッション＋
リポジトリで書かない」で担保する（`src.database.get_inspection_db`）。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class ExternalBase(DeclarativeBase):
    """業者検査 DB の読み取り専用モデルの宣言基盤（Alembic 対象外）。"""
