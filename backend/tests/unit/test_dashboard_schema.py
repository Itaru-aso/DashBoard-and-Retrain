"""ダッシュボード Pydantic スキーマ（dashboard R1, R6）の unit テスト。

フィルタ: 期間必須・色任意・号機任意/複数。期間未指定 / 終了<開始 → 422。
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError


@pytest.mark.unit
def test_filter_valid_with_period_only() -> None:
    from src.schemas.dashboard import DashboardFilter

    f = DashboardFilter(date_from=date(2026, 7, 1), date_to=date(2026, 7, 31))
    assert f.color_no is None
    assert f.machine_ids is None


@pytest.mark.unit
def test_filter_accepts_color_and_machines() -> None:
    from src.schemas.dashboard import DashboardFilter

    f = DashboardFilter(
        date_from=date(2026, 7, 1),
        date_to=date(2026, 7, 31),
        color_no="501",
        size="05",
        chain="CZT8",
        tape="",
        machine_ids=["1", "2"],
    )
    assert f.machine_ids == ["1", "2"]
    assert f.color_no == "501"


@pytest.mark.unit
def test_filter_missing_period_rejected() -> None:
    from src.schemas.dashboard import DashboardFilter

    with pytest.raises(ValidationError):
        DashboardFilter(date_from=date(2026, 7, 1))  # type: ignore[call-arg]


@pytest.mark.unit
def test_filter_end_before_start_rejected() -> None:
    from src.schemas.dashboard import DashboardFilter

    with pytest.raises(ValidationError):
        DashboardFilter(date_from=date(2026, 7, 31), date_to=date(2026, 7, 1))
