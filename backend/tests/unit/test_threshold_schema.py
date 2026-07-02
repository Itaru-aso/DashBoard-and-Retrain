"""閾値 Pydantic スキーマ `src.schemas.threshold`（R1.3–R1.5, R6）の unit テスト。

- metric enum / 値域 0–100 / valid_to > valid_from / スコープ整合（per_color は色4項目必須・
  global は色項目なし）の正常／異常。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 2, 1, tzinfo=timezone.utc)


def _per_color(**over: object) -> dict[str, object]:
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
    return base


@pytest.mark.unit
def test_create_valid_per_color() -> None:
    from src.schemas.threshold import ThresholdCreate

    obj = ThresholdCreate(**_per_color())
    assert obj.metric == "ng_rate"
    assert obj.tape == ""


@pytest.mark.unit
def test_create_valid_global() -> None:
    from src.schemas.threshold import ThresholdCreate

    obj = ThresholdCreate(metric="miss_rate", scope="global", value_pct=10.0, valid_from=T0)
    assert obj.scope == "global"
    assert obj.color_no is None


@pytest.mark.unit
def test_invalid_metric_rejected() -> None:
    from src.schemas.threshold import ThresholdCreate

    with pytest.raises(ValidationError):
        ThresholdCreate(**_per_color(metric="bad_metric"))


@pytest.mark.unit
@pytest.mark.parametrize("value", [-1.0, 100.01, 150.0])
def test_value_out_of_range_rejected(value: float) -> None:
    from src.schemas.threshold import ThresholdCreate

    with pytest.raises(ValidationError):
        ThresholdCreate(**_per_color(value_pct=value))


@pytest.mark.unit
def test_period_reversal_rejected() -> None:
    from src.schemas.threshold import ThresholdCreate

    with pytest.raises(ValidationError):
        ThresholdCreate(**_per_color(valid_from=T1, valid_to=T0))


@pytest.mark.unit
def test_per_color_missing_color_rejected() -> None:
    from src.schemas.threshold import ThresholdCreate

    with pytest.raises(ValidationError):
        ThresholdCreate(**_per_color(color_no=None))


@pytest.mark.unit
def test_global_with_color_rejected() -> None:
    from src.schemas.threshold import ThresholdCreate

    with pytest.raises(ValidationError):
        ThresholdCreate(
            metric="ng_rate", scope="global", color_no="501", value_pct=5.0, valid_from=T0
        )
