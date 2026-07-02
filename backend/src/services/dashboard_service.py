"""ダッシュボード Service（dashboard R2, R3, R5）。

- get_trends: ver2 `daily_metrics` を期間・フルタプル・号機で読み、共有 `metrics.py` で
  率算出（KPI は annotated=0 で NULL・monochro=0 の日は除外）。号機指定なしは全号機合算。
- get_threshold_overlay: 範囲内の各日について `ThresholdService.resolve_effective` を解決し、
  日次の有効閾値系列（階段・欠損）を返す。フルタプル未指定時は重ね描きしない。

`daily_metrics` と閾値はともに ver2 だが、**Service 層で日次系列に突合**（越境結合なし）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.repositories.daily_metrics_repository import DailyMetricsRepository
from src.services.metrics import MetricCounts, compute_rates
from src.services.threshold_service import ThresholdService


@dataclass(frozen=True)
class TrendPoint:
    """日次のメトリクス系列点（KPI は NULL あり）。"""

    jst_date: date
    throughput: int
    ng_rate: float
    false_alarm_rate: float | None
    miss_rate: float | None


@dataclass(frozen=True)
class Summary:
    """期間集計のメトリクス。"""

    throughput: int
    ng_rate: float
    false_alarm_rate: float | None
    miss_rate: float | None


@dataclass(frozen=True)
class OverlayPoint:
    """日次の有効閾値系列点。"""

    jst_date: date
    value_pct: float


class DashboardService:
    """daily_metrics と閾値を Service 層で突合するダッシュボード用 Service。"""

    def __init__(self, session: Session) -> None:
        self._daily_repo = DailyMetricsRepository(session)
        self._threshold_svc = ThresholdService(session)

    def get_trends(
        self,
        date_from: date,
        date_to: date,
        color_no: str | None = None,
        size: str | None = None,
        chain: str | None = None,
        tape: str | None = None,
        unit_ids: list[str] | None = None,
    ) -> list[TrendPoint]:
        """日次のメトリクス系列を返す（monochro=0 の日は除外）。"""
        rows = self._daily_repo.read(date_from, date_to, color_no, size, chain, tape, unit_ids)
        # 日ごとに件数を合算（号機・フルタプル未指定時は該当行を集約）。
        by_day: dict[date, list[int]] = {}
        for row in rows:
            acc = by_day.setdefault(row.jst_date, [0, 0, 0, 0, 0])
            acc[0] += row.monochro_count
            acc[1] += row.ng_count
            acc[2] += row.fp_num
            acc[3] += row.miss_num
            acc[4] += row.annotated_count

        points: list[TrendPoint] = []
        for day in sorted(by_day):
            monochro, ng, fp, miss, annotated = by_day[day]
            rates = compute_rates(
                MetricCounts(
                    monochro_count=monochro,
                    ng_count=ng,
                    fp_num=fp,
                    miss_num=miss,
                    annotated_count=annotated,
                )
            )
            if rates is None:  # monochro=0 は除外
                continue
            points.append(
                TrendPoint(
                    jst_date=day,
                    throughput=rates.throughput,
                    ng_rate=rates.ng_rate,
                    false_alarm_rate=rates.false_alarm_rate,
                    miss_rate=rates.miss_rate,
                )
            )
        return points

    def get_summary(
        self,
        date_from: date,
        date_to: date,
        color_no: str | None = None,
        size: str | None = None,
        chain: str | None = None,
        tape: str | None = None,
        unit_ids: list[str] | None = None,
    ) -> Summary | None:
        """期間・フィルタで件数を合算し率を算出する（monochro=0 は None）。"""
        rows = self._daily_repo.read(date_from, date_to, color_no, size, chain, tape, unit_ids)
        monochro = ng = fp = miss = annotated = 0
        for row in rows:
            monochro += row.monochro_count
            ng += row.ng_count
            fp += row.fp_num
            miss += row.miss_num
            annotated += row.annotated_count
        rates = compute_rates(
            MetricCounts(
                monochro_count=monochro,
                ng_count=ng,
                fp_num=fp,
                miss_num=miss,
                annotated_count=annotated,
            )
        )
        if rates is None:
            return None
        return Summary(
            throughput=rates.throughput,
            ng_rate=rates.ng_rate,
            false_alarm_rate=rates.false_alarm_rate,
            miss_rate=rates.miss_rate,
        )

    def get_machines(self) -> list[str]:
        """号機一覧（daily_metrics.unit）を返す。"""
        return self._daily_repo.list_units()

    def get_threshold_overlay(
        self,
        metric: str,
        color_no: str | None,
        size: str | None,
        chain: str | None,
        tape: str | None,
        date_from: date,
        date_to: date,
    ) -> list[OverlayPoint]:
        """日次の有効閾値系列を返す。フルタプル未指定なら空（重ね描きしない）。"""
        if color_no is None or size is None or chain is None or tape is None:
            return []

        color = (color_no, size, chain, tape)
        points: list[OverlayPoint] = []
        day = date_from
        while day <= date_to:
            at = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            threshold = self._threshold_svc.resolve_effective(metric, color, at)
            if threshold is not None:
                points.append(OverlayPoint(jst_date=day, value_pct=float(threshold.value_pct)))
            day += timedelta(days=1)
        return points
