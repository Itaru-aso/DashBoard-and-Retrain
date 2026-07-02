"""逸脱評価 Service（task R1, R2）。

直近 `window` 日（JST）について、`daily_metrics`（号機合算）を共有 `metrics.py` で率算出し、
`ThresholdService.resolve_effective` の有効閾値と比較して `値 > 閾値` の単位に保守タスクを
upsert する。**閾値なしは判定しない**・**KPI NULL はスキップ＋WARN**・**冪等**・**自動クローズ無し**。

daily_metrics も閾値も task もすべて ver2 DB だが、突合は Service 層で行う（越境結合なし）。
率は分数（例 0.2）で、閾値は % 値（例 5.0）のため、比較・保存時に % へ換算する。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from src.config import settings
from src.repositories.daily_metrics_repository import DailyMetricsRepository
from src.repositories.task_repository import TaskRepository
from src.services.metrics import MetricCounts, compute_rates
from src.services.threshold_service import ThresholdService

logger = logging.getLogger(__name__)

_METRICS = ("ng_rate", "false_alarm_rate", "miss_rate")


class BreachEvaluationService:
    """閾値駆動の日次逸脱評価（冪等・自動クローズ無し）。"""

    def __init__(self, session: Session) -> None:
        self._daily = DailyMetricsRepository(session)
        self._threshold = ThresholdService(session)
        self._tasks = TaskRepository(session)

    def evaluate(self, window_days: int | None = None, *, end_date: date | None = None) -> None:
        """直近 window 日を評価し、逸脱単位にタスクを upsert する。"""
        days = window_days if window_days is not None else settings.BREACH_EVAL_WINDOW_DAYS
        end = end_date if end_date is not None else date.today()
        date_from = end - timedelta(days=days - 1)

        # daily_metrics を期間で読み、(JST日 × フルタプル) に号機合算する。
        groups: dict[tuple[date, str, str, str, str], list[int]] = {}
        for row in self._daily.read(date_from, end):
            key = (row.jst_date, row.color_no, row.size, row.chain, row.tape)
            acc = groups.setdefault(key, [0, 0, 0, 0, 0])
            acc[0] += row.monochro_count
            acc[1] += row.ng_count
            acc[2] += row.fp_num
            acc[3] += row.miss_num
            acc[4] += row.annotated_count

        for (day, color_no, size, chain, tape), counts in groups.items():
            rates = compute_rates(
                MetricCounts(
                    monochro_count=counts[0],
                    ng_count=counts[1],
                    fp_num=counts[2],
                    miss_num=counts[3],
                    annotated_count=counts[4],
                )
            )
            if rates is None:  # monochro=0 は評価対象外
                continue

            color = (color_no, size, chain, tape)
            at = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            for metric in _METRICS:
                threshold = self._threshold.resolve_effective(metric, color, at)
                if threshold is None:
                    continue  # 閾値なしは判定しない

                value = getattr(rates, metric)
                if value is None:  # KPI ラベル0件 → スキップ＋WARN
                    logger.warning(
                        "KPI が NULL のため逸脱判定をスキップ: metric=%s color=%s day=%s",
                        metric,
                        color,
                        day,
                    )
                    continue

                value_pct = value * 100
                if value_pct > float(threshold.value_pct):
                    self._tasks.upsert(
                        color_no=color_no,
                        size=size,
                        chain=chain,
                        tape=tape,
                        task_type=metric,
                        detected_value=Decimal(str(round(value_pct, 2))),
                        threshold_value=threshold.value_pct,
                        evaluation_date=day,
                    )
