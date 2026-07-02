"""色ライフサイクル自動遷移 Service（color C-R2, C-R3, C-R4）の integration テスト。"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

D1 = date(2026, 7, 1)
TUPLE = dict(color_no="001", size="05", chain="CZT8", tape="")


def _metric(day_repo: object, **over: object) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricRow

    base: dict[str, object] = {
        **TUPLE,
        "unit": "1",
        "monochro_count": 1000,
        "ng_count": 0,
        "fp_num": 10,
        "miss_num": 0,
        "annotated_count": 500,
    }
    base.update(over)
    day_repo.upsert_day(D1, [DailyMetricRow(**base)])  # type: ignore[attr-defined]


@pytest.mark.integration
def test_mijisshi_to_verification(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.services.color_lifecycle_service import ColorLifecycleService

    colors = ColorMasterRepository(db_session)
    color = colors.create(**TUPLE)
    # 検査実績あり・ただし実生産基準は未達（fp 2% > 1.5%）＝量産検証で止まる
    _metric(DailyMetricsRepository(db_session), fp_num=20)

    ColorLifecycleService(db_session).evaluate(window_days=1, end_date=D1)

    refreshed = colors.get(color.id)
    assert refreshed.status == "量産検証"
    assert refreshed.verification_at is not None


@pytest.mark.integration
def test_no_metrics_stays_mijisshi(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository
    from src.services.color_lifecycle_service import ColorLifecycleService

    colors = ColorMasterRepository(db_session)
    color = colors.create(**TUPLE)  # 検査実績なし
    ColorLifecycleService(db_session).evaluate(window_days=1, end_date=D1)
    assert colors.get(color.id).status == "未実施"


@pytest.mark.integration
def test_verification_to_production_when_both_criteria_met(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.services.color_lifecycle_service import ColorLifecycleService

    colors = ColorMasterRepository(db_session)
    color = colors.create(**TUPLE)
    colors.set_status(color.id, "量産検証")
    _metric(DailyMetricsRepository(db_session), fp_num=10, miss_num=0)  # 1.0% / 0%

    ColorLifecycleService(db_session).evaluate(window_days=1, end_date=D1)

    refreshed = colors.get(color.id)
    assert refreshed.status == "実生産"
    assert refreshed.production_at is not None


@pytest.mark.integration
def test_no_promote_when_one_criterion_fails(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.services.color_lifecycle_service import ColorLifecycleService

    colors = ColorMasterRepository(db_session)
    color = colors.create(**TUPLE)
    colors.set_status(color.id, "量産検証")
    _metric(DailyMetricsRepository(db_session), fp_num=20, miss_num=0)  # 2.0% > 1.5%

    ColorLifecycleService(db_session).evaluate(window_days=1, end_date=D1)
    assert colors.get(color.id).status == "量産検証"


@pytest.mark.integration
def test_label_zero_day_excluded(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.services.color_lifecycle_service import ColorLifecycleService

    colors = ColorMasterRepository(db_session)
    color = colors.create(**TUPLE)
    colors.set_status(color.id, "量産検証")
    _metric(DailyMetricsRepository(db_session), fp_num=0, miss_num=0, annotated_count=0)

    ColorLifecycleService(db_session).evaluate(window_days=1, end_date=D1)
    assert colors.get(color.id).status == "量産検証"  # ラベル0件は判定対象外


@pytest.mark.integration
def test_one_way_idempotent(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.services.color_lifecycle_service import ColorLifecycleService

    colors = ColorMasterRepository(db_session)
    color = colors.create(**TUPLE)
    colors.set_status(color.id, "量産検証")
    _metric(DailyMetricsRepository(db_session))
    svc = ColorLifecycleService(db_session)
    svc.evaluate(window_days=1, end_date=D1)
    svc.evaluate(window_days=1, end_date=D1)  # 再評価（後戻り・重複遷移なし）
    assert colors.get(color.id).status == "実生産"
