"""アプリ内スケジューラの定期ジョブ（F6）。

`register_jobs` がスケジューラへ定期ジョブを登録する。各ジョブは `*_ENABLED`
フラグで無効化でき、ジョブ本体（Service 呼び出し）は各機能 spec が差し替える。
本基盤時点ではジョブ本体は雛形（未実装ログのみ）。
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger

from src import config

logger = logging.getLogger(__name__)


def _parse_hhmm(value: str) -> tuple[int, int]:
    """ "HH:MM" を (hour, minute) に解釈する。"""
    hour, minute = value.split(":")
    return int(hour), int(minute)


def _breach_eval_job() -> None:
    """逸脱判定ジョブ（本体は閾値管理 spec が実装）。現時点は雛形。"""
    logger.info("逸脱判定ジョブは未実装です（各機能 spec で本体を追加する）")


def register_jobs(scheduler: BaseScheduler) -> None:
    """アプリ内スケジューラに定期ジョブを登録する。

    各ジョブは `*_ENABLED` フラグで無効化できる。ジョブ本体は各機能 spec が
    差し替える。日次ジョブは JST（スケジューラの timezone）で発火する。

    Args:
        scheduler: ジョブを登録する APScheduler のスケジューラ。
    """
    if config.settings.BREACH_EVAL_ENABLED:
        hour, minute = _parse_hhmm(config.settings.BREACH_EVAL_TIME)
        scheduler.add_job(
            _breach_eval_job,
            CronTrigger(hour=hour, minute=minute),
            id="breach_eval",
            replace_existing=True,
        )
