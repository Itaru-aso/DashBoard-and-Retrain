"""閾値 Service（R2, R3, R4）の integration テスト。

- resolve_effective: 色別優先 / global fallback / None。
- create: 期間重複は Conflict 例外。
- supersede: 現行を close＋新規作成で履歴保持。
- disable: 無効化後は解決対象外。
- update: 未有効化レコードの in-place 訂正。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 2, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 3, 1, tzinfo=timezone.utc)
MID = datetime(2026, 1, 15, tzinfo=timezone.utc)
COLOR = ("501", "05", "CZT8", "")


def _svc(db_session: Session) -> object:
    from src.services.threshold_service import ThresholdService

    return ThresholdService(db_session)


def _create(svc: object, **over: object) -> object:
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
        "valid_to": None,
    }
    base.update(over)
    return svc.create(ThresholdCreate(**base))  # type: ignore[attr-defined]


@pytest.mark.integration
def test_resolve_prefers_per_color(db_session: Session) -> None:
    svc = _svc(db_session)
    _create(svc, value_pct=5.0)  # per_color
    _create(svc, scope="global", color_no=None, size=None, chain=None, tape=None, value_pct=9.0)

    resolved = svc.resolve_effective("ng_rate", COLOR, MID)  # type: ignore[attr-defined]
    assert resolved is not None
    assert resolved.scope == "per_color"
    assert float(resolved.value_pct) == 5.0


@pytest.mark.integration
def test_resolve_falls_back_to_global(db_session: Session) -> None:
    svc = _svc(db_session)
    _create(svc, scope="global", color_no=None, size=None, chain=None, tape=None, value_pct=9.0)

    resolved = svc.resolve_effective("ng_rate", COLOR, MID)  # type: ignore[attr-defined]
    assert resolved is not None
    assert resolved.scope == "global"


@pytest.mark.integration
def test_resolve_none_when_no_threshold(db_session: Session) -> None:
    svc = _svc(db_session)
    assert svc.resolve_effective("ng_rate", COLOR, MID) is None  # type: ignore[attr-defined]


@pytest.mark.integration
def test_create_conflict_on_overlap(db_session: Session) -> None:
    from src.services.threshold_service import ThresholdConflictError

    svc = _svc(db_session)
    _create(svc, valid_from=T0, valid_to=T2)
    with pytest.raises(ThresholdConflictError):
        _create(svc, valid_from=T1, valid_to=None)


@pytest.mark.integration
def test_supersede_keeps_history(db_session: Session) -> None:
    svc = _svc(db_session)
    current = _create(svc, value_pct=5.0, valid_from=T0, valid_to=None)

    svc.supersede(current.id, new_value_pct=8.0, at=T1)  # type: ignore[attr-defined]

    # 過去（T0.5）は旧値、現在（T1 以降）は新値
    old = svc.resolve_effective("ng_rate", COLOR, MID)  # type: ignore[attr-defined]
    new = svc.resolve_effective("ng_rate", COLOR, T2)  # type: ignore[attr-defined]
    assert old is not None and float(old.value_pct) == 5.0
    assert new is not None and float(new.value_pct) == 8.0


@pytest.mark.integration
def test_disable_excludes_from_resolution(db_session: Session) -> None:
    svc = _svc(db_session)
    current = _create(svc, valid_from=T0, valid_to=None)

    svc.disable(current.id, at=T1)  # type: ignore[attr-defined]

    assert svc.resolve_effective("ng_rate", COLOR, MID) is not None  # 無効化前は有効
    assert svc.resolve_effective("ng_rate", COLOR, T2) is None  # 以降は解決されない


@pytest.mark.integration
def test_update_inplace_for_future_record(db_session: Session) -> None:
    from src.schemas.threshold import ThresholdUpdate

    svc = _svc(db_session)
    future = _create(svc, valid_from=T2, valid_to=None)  # まだ有効化前

    updated = svc.update(future.id, ThresholdUpdate(value_pct=3.0))  # type: ignore[attr-defined]
    assert updated is not None
    assert float(updated.value_pct) == 3.0
