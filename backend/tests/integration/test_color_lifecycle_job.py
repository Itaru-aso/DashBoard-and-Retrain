"""色ライフサイクル 日次ジョブ（color C-R3, C-R4）の integration テスト。"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import Engine


@pytest.mark.integration
def test_run_color_lifecycle_invokes_service(
    ver2_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import database
    from src.jobs import color_lifecycle_job

    database.SessionLocal.configure(bind=ver2_engine)
    called: dict[str, bool] = {}

    def _fake(self: object, *args: object, **kwargs: object) -> None:
        called["invoked"] = True

    monkeypatch.setattr(
        "src.services.color_lifecycle_service.ColorLifecycleService.evaluate",
        _fake,
    )
    color_lifecycle_job.run_color_lifecycle()
    assert called.get("invoked") is True


@pytest.mark.integration
def test_run_color_lifecycle_rolls_back(
    ver2_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import database
    from src.jobs import color_lifecycle_job

    database.SessionLocal.configure(bind=ver2_engine)

    def _boom(self: object, *args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "src.services.color_lifecycle_service.ColorLifecycleService.evaluate",
        _boom,
    )
    with pytest.raises(RuntimeError):
        color_lifecycle_job.run_color_lifecycle()


@pytest.mark.integration
def test_color_lifecycle_job_registered() -> None:
    from src.scheduler import create_scheduler

    scheduler = create_scheduler()
    scheduler.start(paused=True)
    try:
        assert scheduler.get_job("color_lifecycle") is not None
    finally:
        scheduler.shutdown(wait=False)
