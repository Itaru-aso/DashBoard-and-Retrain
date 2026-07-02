"""アプリ内スケジューラ基盤（F6）。

`BackgroundScheduler`（APScheduler）を単一プロセス・単一ワーカで所有する
（`uvicorn --workers 1` 前提）。`main.py` の lifespan で start / shutdown する。
ジョブ登録は `src.jobs.register_jobs` に委譲する。日次ジョブは JST で発火する。
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from src.jobs import register_jobs

JST = ZoneInfo("Asia/Tokyo")


def create_scheduler() -> BackgroundScheduler:
    """アプリ内スケジューラを生成し、定期ジョブを登録して返す（未起動）。

    Returns:
        ジョブ登録済みの未起動 `BackgroundScheduler`。呼び出し側が start / shutdown する。
    """
    scheduler = BackgroundScheduler(timezone=JST)
    register_jobs(scheduler)
    return scheduler
