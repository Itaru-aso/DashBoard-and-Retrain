"""逸脱判定 日次ジョブ（task R1.4）の integration テスト。

run_breach_eval がセッションを開いて評価サービスを呼ぶ／例外時 rollback＋再送出。
登録・無効化フラグは foundation の scheduler テストで担保。
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import Engine


@pytest.mark.integration
def test_run_breach_eval_invokes_service(
    ver2_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import database
    from src.jobs import breach_eval_job

    database.SessionLocal.configure(bind=ver2_engine)
    called: dict[str, bool] = {}

    def _fake_evaluate(self: object, *args: object, **kwargs: object) -> None:
        called["invoked"] = True

    monkeypatch.setattr(
        "src.services.breach_evaluation_service.BreachEvaluationService.evaluate",
        _fake_evaluate,
    )
    breach_eval_job.run_breach_eval()
    assert called.get("invoked") is True


@pytest.mark.integration
def test_run_breach_eval_raises_and_rolls_back(
    ver2_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import database
    from src.jobs import breach_eval_job

    database.SessionLocal.configure(bind=ver2_engine)

    def _boom(self: object, *args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "src.services.breach_evaluation_service.BreachEvaluationService.evaluate",
        _boom,
    )
    with pytest.raises(RuntimeError):
        breach_eval_job.run_breach_eval()
