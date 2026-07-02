"""色ライフサイクル 日次ジョブ（color C-R3, C-R4）。

アプリ内スケジューラから毎日呼ばれ、色の自動遷移（未実施 → 量産検証 → 実生産）を
評価する（一方向・冪等）。集計 → 逸脱判定 → **昇格** の順（集計後に走る）。

バックグラウンド実行のため ver2 セッションを自前で開く（単一ワーカ所有）。
"""

from __future__ import annotations

import logging

from src.database import SessionLocal
from src.services.color_lifecycle_service import ColorLifecycleService

logger = logging.getLogger(__name__)


def run_color_lifecycle() -> None:
    """色のライフサイクル遷移を評価する（正常時 commit・例外時 rollback＋再送出）。"""
    db = SessionLocal()
    try:
        ColorLifecycleService(db).evaluate()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("色ライフサイクルジョブが失敗しました")
        raise
    finally:
        db.close()
