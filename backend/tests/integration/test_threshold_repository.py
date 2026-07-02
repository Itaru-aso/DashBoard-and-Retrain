"""閾値 Repository（R1.1, R3.1–R3.5, R5）の integration テスト。

- CRUD（create / get / list(filter) / update）。
- find_active の半開区間境界（valid_from==at は有効・valid_to==at は無効）。
- フルタプル一致のみヒット（size 違いは不一致）。結果は高々1件。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 2, 1, tzinfo=timezone.utc)
COLOR = ("501", "05", "CZT8", "")


def _create(repo: object, **over: object) -> object:
    from src.schemas.threshold import ThresholdCreate

    base: dict[str, object] = {
        "metric": "ng_rate",
        "scope": "per_color",
        "color_no": "501",
        "size": "05",
        "chain": "CZT8",
        "tape": "",
        "value_pct": 5.0,
        "valid_from": T0,
        "valid_to": T1,
    }
    base.update(over)
    return repo.create(ThresholdCreate(**base))  # type: ignore[attr-defined]


@pytest.mark.integration
def test_create_and_get(db_session: Session) -> None:
    from src.repositories.threshold_repository import ThresholdRepository

    repo = ThresholdRepository(db_session)
    created = _create(repo)
    fetched = repo.get(created.id)
    assert fetched is not None
    assert fetched.metric == "ng_rate"
    assert float(fetched.value_pct) == 5.0


@pytest.mark.integration
def test_list_filters_by_metric_and_scope(db_session: Session) -> None:
    from src.repositories.threshold_repository import ThresholdRepository
    from src.schemas.threshold import ThresholdCreate

    repo = ThresholdRepository(db_session)
    _create(repo)  # ng_rate / per_color
    repo.create(ThresholdCreate(metric="miss_rate", scope="global", value_pct=9.0, valid_from=T0))

    assert len(repo.list()) == 2
    assert len(repo.list(metric="ng_rate")) == 1
    assert len(repo.list(scope="global")) == 1


@pytest.mark.integration
def test_update_changes_value(db_session: Session) -> None:
    from src.repositories.threshold_repository import ThresholdRepository
    from src.schemas.threshold import ThresholdUpdate

    repo = ThresholdRepository(db_session)
    created = _create(repo)
    updated = repo.update(created.id, ThresholdUpdate(value_pct=7.5))
    assert updated is not None
    assert float(updated.value_pct) == 7.5


@pytest.mark.integration
def test_find_active_half_open_boundaries(db_session: Session) -> None:
    from src.repositories.threshold_repository import ThresholdRepository

    repo = ThresholdRepository(db_session)
    _create(repo)  # valid_from=T0, valid_to=T1

    assert repo.find_active("ng_rate", "per_color", COLOR, T0) is not None  # 開始含む
    assert repo.find_active("ng_rate", "per_color", COLOR, T1) is None  # 終了含まない
    after = datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert repo.find_active("ng_rate", "per_color", COLOR, after) is None


@pytest.mark.integration
def test_find_active_requires_full_tuple_match(db_session: Session) -> None:
    from src.repositories.threshold_repository import ThresholdRepository

    repo = ThresholdRepository(db_session)
    _create(repo)  # size=05

    mid = datetime(2026, 1, 15, tzinfo=timezone.utc)
    assert repo.find_active("ng_rate", "per_color", COLOR, mid) is not None
    # size 違いはヒットしない
    assert repo.find_active("ng_rate", "per_color", ("501", "99", "CZT8", ""), mid) is None
