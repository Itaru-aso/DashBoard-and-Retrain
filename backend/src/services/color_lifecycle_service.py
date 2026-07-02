"""色ライフサイクル自動遷移 Service（color C-R2, C-R3, C-R4）。

日次で一方向・冪等に遷移する:
- 未実施 → 量産検証: `daily_metrics` に当該フルタプルの集計行が有れば（検査実績あり）遷移。
- 量産検証 → 実生産: `daily_metrics` を号機合算で読み、対象期間の各 JST 日の率を `metrics.py` で
  算出し、**いずれかの日**が `虚報率 ≤ 1.5%` かつ `見逃し率 ≤ 0.05%` を同時達成したら昇格。
  ラベル（正解）のある日のみ判定（annotated_count>0）。固定基準（閾値管理 非依存）。

daily_metrics（ver2）と color_master（ver2）の突合は Service 層で行う（越境結合なし）。
率は分数（例 0.01）で比較する（1.5% = 0.015、0.05% = 0.0005）。
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from src.config import settings
from src.repositories.color_master_repository import ColorMasterRepository
from src.repositories.daily_metrics_repository import DailyMetricsRepository
from src.services.metrics import MetricCounts, compute_rates

_FALSE_ALARM_MAX = 0.015  # 虚報率 ≤ 1.5%
_MISS_MAX = 0.0005  # 見逃し率 ≤ 0.05%


class ColorLifecycleService:
    """色の自動遷移（未実施 → 量産検証 → 実生産・一方向・冪等）。"""

    def __init__(self, session: Session) -> None:
        self._colors = ColorMasterRepository(session)
        self._daily = DailyMetricsRepository(session)

    def evaluate(self, window_days: int | None = None, *, end_date: date | None = None) -> None:
        """直近 window 日で自動遷移を評価する。"""
        days = window_days if window_days is not None else settings.AGG_WINDOW_DAYS
        end = end_date if end_date is not None else date.today()
        date_from = end - timedelta(days=days - 1)

        self._promote_to_verification(date_from, end)
        self._promote_to_production(date_from, end)

    def _promote_to_verification(self, date_from: date, date_to: date) -> None:
        """未実施 → 量産検証（検査実績があれば）。"""
        for color in list(self._colors.find_by_status("未実施")):
            rows = self._daily.read(
                date_from, date_to, color.color_no, color.size, color.chain, color.tape
            )
            if rows:
                self._colors.set_status(color.id, "量産検証")

    def _promote_to_production(self, date_from: date, date_to: date) -> None:
        """量産検証 → 実生産（ある日が両基準を同時達成すれば昇格）。"""
        for color in list(self._colors.find_by_status("量産検証")):
            aggregated = self._daily.read_unit_aggregated(
                date_from, date_to, color.color_no, color.size, color.chain, color.tape
            )
            for day in aggregated:
                rates = compute_rates(
                    MetricCounts(
                        monochro_count=day.monochro_count,
                        ng_count=day.ng_count,
                        fp_num=day.fp_num,
                        miss_num=day.miss_num,
                        annotated_count=day.annotated_count,
                    )
                )
                if rates is None or rates.false_alarm_rate is None or rates.miss_rate is None:
                    continue  # monochro=0 / ラベル0件の日は判定対象外
                if rates.false_alarm_rate <= _FALSE_ALARM_MAX and rates.miss_rate <= _MISS_MAX:
                    self._colors.set_status(color.id, "実生産")
                    break
