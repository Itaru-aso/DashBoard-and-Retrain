"""逸脱判定 日次ジョブ（task R1.4）。

アプリ内スケジューラから毎日（`BREACH_EVAL_TIME`）に呼ばれ、直近
`BREACH_EVAL_WINDOW_DAYS` 日を再評価してタスクを upsert する（冪等・自動クローズ無し）。
集計 → 逸脱判定 → 昇格 の順（集計ジョブが当日分を更新した後に走る）。

バックグラウンド実行のため ver2 セッションを自前で開く（単一ワーカ所有）。
"""

from __future__ import annotations

import logging

from src.database import SessionLocal
from src.services.breach_evaluation_service import BreachEvaluationService

logger = logging.getLogger(__name__)


def run_breach_eval() -> None:
    """直近ウィンドウを逸脱評価する（正常時 commit・例外時 rollback＋再送出）。"""
    db = SessionLocal()
    try:
        BreachEvaluationService(db).evaluate()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("逸脱判定ジョブが失敗しました")
        raise
    finally:
        db.close()
