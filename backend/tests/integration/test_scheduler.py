"""アプリ内スケジューラ基盤 `src.scheduler` / `src.jobs`（F6）のテスト。

- スケジューラを生成し start / shutdown できる（単一所有・BackgroundScheduler）。
- `src/jobs` の登録関数がジョブを登録する。
- `*_ENABLED` フラグ（BREACH_EVAL_ENABLED）でジョブを無効化できる。
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_scheduler_starts_and_stops() -> None:
    """create_scheduler で生成したスケジューラを起動・停止できる。"""
    from src.scheduler import create_scheduler

    scheduler = create_scheduler()
    assert not scheduler.running
    scheduler.start()
    try:
        assert scheduler.running
    finally:
        scheduler.shutdown(wait=False)
    assert not scheduler.running


@pytest.mark.integration
def test_job_registered_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """BREACH_EVAL_ENABLED=true のとき逸脱判定ジョブが登録される。"""
    from src import config
    from src.scheduler import create_scheduler

    monkeypatch.setattr(config.settings, "BREACH_EVAL_ENABLED", True)
    monkeypatch.setattr(config.settings, "BREACH_EVAL_TIME", "03:30")

    scheduler = create_scheduler()
    scheduler.start(paused=True)  # pending ジョブを jobstore へ反映（発火はしない）
    try:
        job = scheduler.get_job("breach_eval")
        assert job is not None
        job.func()  # 雛形ジョブが例外なく呼べる
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.integration
def test_job_absent_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """BREACH_EVAL_ENABLED=false のとき逸脱判定ジョブは登録されない。"""
    from src import config
    from src.scheduler import create_scheduler

    monkeypatch.setattr(config.settings, "BREACH_EVAL_ENABLED", False)

    scheduler = create_scheduler()
    scheduler.start(paused=True)
    try:
        assert scheduler.get_job("breach_eval") is None
    finally:
        scheduler.shutdown(wait=False)
