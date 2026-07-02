"""色マスター Repository（color C-R1, C-R2, C-R5）の integration テスト。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

TUPLE = dict(color_no="001", size="05", chain="CZT8", tape="")
SAMPLE = dict(rgb_r=10, rgb_g=20, rgb_b=30, lab_l=50.0, lab_a=1.0, lab_b=-2.0)


@pytest.mark.integration
def test_create_is_mijisshi(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository

    repo = ColorMasterRepository(db_session)
    color = repo.create(**TUPLE, **SAMPLE)
    assert color.status == "未実施"
    assert color.rgb_r == 10


@pytest.mark.integration
def test_upsert_by_tuple_updates_sample_keeps_status(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository

    repo = ColorMasterRepository(db_session)
    color = repo.create(**TUPLE, **SAMPLE)
    repo.set_status(color.id, "量産検証")

    updated = repo.upsert_by_tuple(**TUPLE, **{**SAMPLE, "rgb_r": 99})
    assert updated.id == color.id
    assert updated.rgb_r == 99  # 色見本更新
    assert updated.status == "量産検証"  # status 保持
    assert len(repo.list()) == 1  # ユニーク（重複作成なし）


@pytest.mark.integration
def test_upsert_by_tuple_creates_when_absent(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository

    repo = ColorMasterRepository(db_session)
    created = repo.upsert_by_tuple(**TUPLE, **SAMPLE)
    assert created.status == "未実施"


@pytest.mark.integration
def test_set_status_forward_and_invalid(db_session: Session) -> None:
    from src.repositories.color_master_repository import (
        ColorMasterRepository,
        ColorTransitionError,
    )

    repo = ColorMasterRepository(db_session)
    color = repo.create(**TUPLE, **SAMPLE)
    repo.set_status(color.id, "量産検証")
    assert color.verification_at is not None
    repo.set_status(color.id, "実生産")
    assert color.production_at is not None
    with pytest.raises(ColorTransitionError):
        repo.set_status(color.id, "未実施")  # 後戻り不可


@pytest.mark.integration
def test_list_and_find_by_status(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository

    repo = ColorMasterRepository(db_session)
    c1 = repo.create(**TUPLE, **SAMPLE)
    repo.create(**{**TUPLE, "color_no": "002"}, **SAMPLE)
    repo.set_status(c1.id, "量産検証")

    assert len(repo.list()) == 2
    assert len(repo.list(status="未実施")) == 1
    assert len(repo.find_by_status("量産検証")) == 1
