"""app_db `annotation.image_base` の読み取り専用モデル（F4・サンプル/パターン）。

業者検査 DB は読み取り専用（Alembic 対象外）。列は実スキーマに合わせて手書きする
（`docs/reference/schema-spec-mapping.md` 準拠）。本モデルは読み取り専用モデルの
**パターン例**であり、具体列の拡充は各機能 spec が本モデルに追記する。

フルタプルは `extra_info`(jsonb) の `colorNo`/`size`/`chain`/`tape`、monochro は
`camera_model='camera1_image'`、AI 判定は `judgment_result`(0:OK/1:NG)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.external.base import ExternalBase


class ImageBase(ExternalBase):
    """`annotation.image_base`（検査結果・日次パーティション）の読み取り専用モデル。"""

    __tablename__ = "image_base"
    __table_args__ = {"schema": "annotation"}

    image_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    inspect_timestamp: Mapped[datetime] = mapped_column(DateTime)
    unit: Mapped[str | None] = mapped_column(String)
    camera_model: Mapped[str | None] = mapped_column(String)
    judgment_result: Mapped[int | None] = mapped_column(Integer)
    extra_info: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
