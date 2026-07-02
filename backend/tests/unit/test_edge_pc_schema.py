"""エッジPC Pydantic スキーマ（edge E-R1）の unit テスト。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


@pytest.mark.unit
def test_create_valid() -> None:
    from src.schemas.edge_pc import EdgePcCreate

    obj = EdgePcCreate(name="検査PC_1", host="169.254.93.171", model_port=2123)
    assert obj.name == "検査PC_1"
    assert obj.enabled is True  # 既定


@pytest.mark.unit
def test_create_requires_name_and_host() -> None:
    from src.schemas.edge_pc import EdgePcCreate

    with pytest.raises(ValidationError):
        EdgePcCreate(host="169.254.93.171")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        EdgePcCreate(name="検査PC_1")  # type: ignore[call-arg]


@pytest.mark.unit
def test_update_all_optional() -> None:
    from src.schemas.edge_pc import EdgePcUpdate

    upd = EdgePcUpdate(enabled=False)
    assert upd.enabled is False
    assert upd.host is None
