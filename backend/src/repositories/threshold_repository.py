"""閾値 Repository（ver2 DB・R1.1, R3, R5）。

CRUD と有効閾値の検索（`find_active`）を提供する。有効判定は半開区間
`valid_from <= at < valid_to`（`valid_to` NULL は無期限）。排他制約により結果は高々1件。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.models.threshold import Threshold
from src.schemas.threshold import ThresholdCreate, ThresholdUpdate


class ThresholdRepository:
    """threshold（ver2 DB）への CRUD と有効閾値検索。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, data: ThresholdCreate) -> Threshold:
        """閾値を作成する（flush まで。commit は呼び出し側）。"""
        row = Threshold(
            metric=data.metric,
            scope=data.scope,
            color_no=data.color_no,
            size=data.size,
            chain=data.chain,
            tape=data.tape,
            value_pct=data.value_pct,
            valid_from=data.valid_from,
            valid_to=data.valid_to,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return row

    def get(self, threshold_id: int) -> Threshold | None:
        """id で取得する。"""
        return self._session.get(Threshold, threshold_id)

    def list(
        self,
        metric: str | None = None,
        scope: str | None = None,
    ) -> list[Threshold]:
        """メトリクス・スコープで絞り込んで一覧する（小規模のため全件）。"""
        stmt = select(Threshold)
        if metric is not None:
            stmt = stmt.where(Threshold.metric == metric)
        if scope is not None:
            stmt = stmt.where(Threshold.scope == scope)
        stmt = stmt.order_by(Threshold.metric, Threshold.scope, Threshold.valid_from)
        return list(self._session.scalars(stmt))

    def update(self, threshold_id: int, data: ThresholdUpdate) -> Threshold | None:
        """指定項目のみ更新する（updated_at を更新）。"""
        row = self._session.get(Threshold, threshold_id)
        if row is None:
            return None
        if data.value_pct is not None:
            row.value_pct = Decimal(str(data.value_pct))
        if data.valid_from is not None:
            row.valid_from = data.valid_from
        if data.valid_to is not None:
            row.valid_to = data.valid_to
        row.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        self._session.refresh(row)
        return row

    def find_active(
        self,
        metric: str,
        scope: str,
        color: Sequence[str] | None,
        at: datetime,
    ) -> Threshold | None:
        """半開区間で有効な閾値を返す（高々1件）。

        Args:
            metric: メトリクス。
            scope: `per_color` または `global`。
            color: `per_color` のとき (color_no, size, chain, tape)。global では無視。
            at: 判定時点。
        """
        stmt = select(Threshold).where(
            Threshold.metric == metric,
            Threshold.scope == scope,
            Threshold.valid_from <= at,
            or_(Threshold.valid_to.is_(None), Threshold.valid_to > at),
        )
        if scope == "per_color":
            if color is None:
                raise ValueError("per_color の find_active には color が必要です")
            color_no, size, chain, tape = color
            stmt = stmt.where(
                Threshold.color_no == color_no,
                Threshold.size == size,
                Threshold.chain == chain,
                Threshold.tape == tape,
            )
        return self._session.scalars(stmt).one_or_none()
