"""app_db `admin.dataset_category_item` の読み取り専用モデル（F4・schema-spec-mapping 準拠）。

正解ラベルの分類。`on_class`（'0'=正解OK / '1'=正解NG）を持つ。主キーは (dataset_id, item_id)。
"""

from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.models.external.base import ExternalBase


class DatasetCategoryItem(ExternalBase):
    """`admin.dataset_category_item`（読み取り専用）。"""

    __tablename__ = "dataset_category_item"
    __table_args__ = {"schema": "admin"}

    dataset_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    on_class: Mapped[str | None] = mapped_column()
