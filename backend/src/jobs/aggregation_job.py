"""日次集計ジョブ（A-R2/A-R3）。

アプリ内スケジューラから毎日 JST 早朝（`AGG_RUN_TIME`）に呼ばれ、直近
`AGG_WINDOW_DAYS` 日を再集計する（後追いアノテーション反映・冪等）。集計 → 逸脱判定 →
昇格の順で動かす前提（集計が当日分を更新してから判定・昇格が読む）。

スケジューラのバックグラウンド実行にはリクエストの DB セッションが無いため、
本ジョブが2エンジンのセッション（業者検査 DB 読み取り／ver2 書き込み）を自分で開く。
"""

from __future__ import annotations

import logging

from src.database import InspectionSessionLocal, SessionLocal
from src.repositories.daily_metrics_repository import DailyMetricsRepository
from src.services.aggregation_service import AggregationService

logger = logging.getLogger(__name__)


def run_aggregation() -> None:
    """直近ウィンドウを再集計する（ver2 は正常時 commit・例外時 rollback）。"""
    inspection = InspectionSessionLocal()
    db = SessionLocal()
    try:
        service = AggregationService(inspection, DailyMetricsRepository(db))
        service.aggregate_window()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("日次集計ジョブが失敗しました")
        raise
    finally:
        inspection.close()
        db.close()
