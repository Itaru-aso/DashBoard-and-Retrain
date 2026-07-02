"""明細 Repository（業者検査 DB・読み取り専用・dashboard R4.2）。

app_db `annotation.image_base` を**オンザフライ**（期間パーティション）で読み、
**キーセットページング**（カーソル `(inspect_timestamp, image_id)`）する。OFFSET は使わない。
集計は行わない（推移・集計は ver2 `daily_metrics`）。app_db は変更しない（索引追加もしない）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from src.models.external.image_base import ImageBase

Cursor = tuple[datetime, int]


@dataclass(frozen=True)
class DetailRow:
    """明細1行（フルタプルは extra_info から抽出）。"""

    image_id: int
    inspect_timestamp: datetime
    unit: str | None
    camera_model: str | None
    judgment_result: int | None
    color_no: str | None
    size: str | None
    chain: str | None
    tape: str | None


@dataclass(frozen=True)
class DetailPage:
    """明細ページ（rows と次カーソル）。"""

    rows: list[DetailRow]
    next_cursor: Cursor | None


class InspectionDetailRepository:
    """app_db `image_base` のキーセット明細読み出し（読み取り専用）。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def read_details(
        self,
        date_from: datetime,
        date_to: datetime,
        *,
        color_no: str | None = None,
        size: str | None = None,
        chain: str | None = None,
        tape: str | None = None,
        unit_ids: Sequence[str] | None = None,
        cursor: Cursor | None = None,
        limit: int = 50,
    ) -> DetailPage:
        """期間・フルタプル・号機で明細をキーセット読み出しする。

        Args:
            date_from: 期間開始（含む）。
            date_to: 期間終了（含まない）。
            color_no/size/chain/tape: フルタプル絞り込み（任意）。
            unit_ids: 号機の絞り込み（任意・複数可）。
            cursor: 前ページ末尾の `(inspect_timestamp, image_id)`。
            limit: 取得件数上限。
        """
        extra = ImageBase.extra_info
        stmt = select(ImageBase).where(
            ImageBase.inspect_timestamp >= date_from,
            ImageBase.inspect_timestamp < date_to,
        )
        if color_no is not None:
            stmt = stmt.where(extra["colorNo"].astext == color_no)
        if size is not None:
            stmt = stmt.where(extra["size"].astext == size)
        if chain is not None:
            stmt = stmt.where(extra["chain"].astext == chain)
        if tape is not None:
            stmt = stmt.where(extra["tape"].astext == tape)
        if unit_ids:
            stmt = stmt.where(ImageBase.unit.in_(unit_ids))
        if cursor is not None:
            stmt = stmt.where(tuple_(ImageBase.inspect_timestamp, ImageBase.image_id) > cursor)

        # 次ページ有無を正確に判定するため limit+1 件を取得する。
        stmt = stmt.order_by(ImageBase.inspect_timestamp, ImageBase.image_id).limit(limit + 1)

        images = list(self._session.scalars(stmt))
        has_more = len(images) > limit
        images = images[:limit]
        rows = [self._to_row(image) for image in images]
        next_cursor: Cursor | None = None
        if has_more and images:
            last = images[-1]
            next_cursor = (last.inspect_timestamp, last.image_id)
        return DetailPage(rows=rows, next_cursor=next_cursor)

    @staticmethod
    def _to_row(image: ImageBase) -> DetailRow:
        extra = image.extra_info or {}
        return DetailRow(
            image_id=image.image_id,
            inspect_timestamp=image.inspect_timestamp,
            unit=image.unit,
            camera_model=image.camera_model,
            judgment_result=image.judgment_result,
            color_no=extra.get("colorNo"),
            size=extra.get("size"),
            chain=extra.get("chain"),
            tape=extra.get("tape"),
        )
