"""色マスター Pydantic スキーマ（color C-R5）の unit テスト。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


@pytest.mark.unit
def test_filter_valid_and_invalid_status() -> None:
    from src.schemas.color_master import ColorFilter

    assert ColorFilter(status="量産検証").status == "量産検証"
    with pytest.raises(ValidationError):
        ColorFilter(status="廃止")


@pytest.mark.unit
def test_sample_update_valid() -> None:
    from src.schemas.color_master import ColorSampleUpdate

    upd = ColorSampleUpdate(rgb_r=10, rgb_g=20, rgb_b=30, lab_l=50.0)
    assert upd.rgb_r == 10


@pytest.mark.unit
def test_sample_update_rgb_out_of_range() -> None:
    from src.schemas.color_master import ColorSampleUpdate

    with pytest.raises(ValidationError):
        ColorSampleUpdate(rgb_r=300)


@pytest.mark.unit
def test_import_result_construct() -> None:
    from src.schemas.color_master import ImportResult

    result = ImportResult(created=2, updated=1, skipped=0, errors=["行3: color_no 欠落"])
    assert result.created == 2
    assert result.errors == ["行3: color_no 欠落"]
