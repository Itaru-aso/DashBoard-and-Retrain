"""daily_metrics の Repository（ver2 DB・A-R1/A-R6）。

- `upsert_day`: 対象日を **delete → insert**（同一トランザクション・冪等）。消えたタプルも残さない。
- `read`: 期間・フルタプル・号機で件数行を読む（ダッシュボード）。
- `read_unit_aggregated`: **号機合算**（unit を畳んで件数合算。逸脱判定・色昇格が全号機で評価）。

率は返さない（件数のみ）。率は呼び出し側で `services/metrics.py` を通して算出する。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.models.daily_metrics import DailyMetrics


@dataclass(frozen=True)
class DailyMetricRow:
    """upsert 対象の1行（jst_date は `upsert_day` の引数で与える）。"""

    color_no: str
    size: str
    chain: str
    tape: str
    unit: str
    monochro_count: int
    ng_count: int
    fp_num: int
    miss_num: int
    annotated_count: int


@dataclass(frozen=True)
class AggregatedDailyCounts:
    """号機合算後の1日ぶんの件数（フルタプルは固定）。"""

    jst_date: date
    color_no: str
    size: str
    chain: str
    tape: str
    monochro_count: int
    ng_count: int
    fp_num: int
    miss_num: int
    annotated_count: int


class DailyMetricsRepository:
    """daily_metrics（ver2 DB）への upsert / 読み出し。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_day(self, jst_date: date, rows: Sequence[DailyMetricRow]) -> None:
        """対象日の集計を delete → insert で置き換える（冪等）。

        Args:
            jst_date: 対象の JST 日。
            rows: 当日ぶんの（フルタプル×号機の）件数行。
        """
        # 先に当日分を削除（この時点で保留中の insert は無い）→ 続けて insert。
        self._session.execute(delete(DailyMetrics).where(DailyMetrics.jst_date == jst_date))
        self._session.add_all(
            [
                DailyMetrics(
                    jst_date=jst_date,
                    color_no=row.color_no,
                    size=row.size,
                    chain=row.chain,
                    tape=row.tape,
                    unit=row.unit,
                    monochro_count=row.monochro_count,
                    ng_count=row.ng_count,
                    fp_num=row.fp_num,
                    miss_num=row.miss_num,
                    annotated_count=row.annotated_count,
                )
                for row in rows
            ]
        )
        self._session.flush()

    def read(
        self,
        date_from: date,
        date_to: date,
        color_no: str | None = None,
        size: str | None = None,
        chain: str | None = None,
        tape: str | None = None,
        unit_ids: Sequence[str] | None = None,
    ) -> list[DailyMetrics]:
        """期間・フルタプル・号機で件数行を読む（率は算出しない）。"""
        stmt = select(DailyMetrics).where(
            DailyMetrics.jst_date >= date_from,
            DailyMetrics.jst_date <= date_to,
        )
        if color_no is not None:
            stmt = stmt.where(DailyMetrics.color_no == color_no)
        if size is not None:
            stmt = stmt.where(DailyMetrics.size == size)
        if chain is not None:
            stmt = stmt.where(DailyMetrics.chain == chain)
        if tape is not None:
            stmt = stmt.where(DailyMetrics.tape == tape)
        if unit_ids:
            stmt = stmt.where(DailyMetrics.unit.in_(unit_ids))
        stmt = stmt.order_by(DailyMetrics.jst_date, DailyMetrics.unit)
        return list(self._session.scalars(stmt))

    def read_unit_aggregated(
        self,
        date_from: date,
        date_to: date,
        color_no: str,
        size: str,
        chain: str,
        tape: str,
    ) -> list[AggregatedDailyCounts]:
        """フルタプル固定・期間で、号機を畳んで日ごとに件数合算する。"""
        stmt = (
            select(
                DailyMetrics.jst_date,
                func.sum(DailyMetrics.monochro_count),
                func.sum(DailyMetrics.ng_count),
                func.sum(DailyMetrics.fp_num),
                func.sum(DailyMetrics.miss_num),
                func.sum(DailyMetrics.annotated_count),
            )
            .where(
                DailyMetrics.jst_date >= date_from,
                DailyMetrics.jst_date <= date_to,
                DailyMetrics.color_no == color_no,
                DailyMetrics.size == size,
                DailyMetrics.chain == chain,
                DailyMetrics.tape == tape,
            )
            .group_by(DailyMetrics.jst_date)
            .order_by(DailyMetrics.jst_date)
        )
        return [
            AggregatedDailyCounts(
                jst_date=row[0],
                color_no=color_no,
                size=size,
                chain=chain,
                tape=tape,
                monochro_count=int(row[1]),
                ng_count=int(row[2]),
                fp_num=int(row[3]),
                miss_num=int(row[4]),
                annotated_count=int(row[5]),
            )
            for row in self._session.execute(stmt).all()
        ]
