"""app_db `annotation.annotation_item` の読み取り専用モデル（F4・schema-spec-mapping 準拠）。

画像の注釈項目。正解は image_id→annotation_item→dataset_category_item.on_class で導出する
（use_flg は学習対象フラグでありメトリクスの母集団では絞らない）。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.models.external.base import ExternalBase


class AnnotationItem(ExternalBase):
    """`annotation.annotation_item`（読み取り専用）。"""

    __tablename__ = "annotation_item"
    __table_args__ = {"schema": "annotation"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    image_id: Mapped[int] = mapped_column(BigInteger)
    dataset_id: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[int] = mapped_column(Integer)
    use_flg: Mapped[bool | None] = mapped_column(Boolean)
