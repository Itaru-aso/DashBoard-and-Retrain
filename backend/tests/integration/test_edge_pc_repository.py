"""エッジPC Repository（edge E-R1, E-R3, E-R4）の integration テスト。"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def _create(repo: object, name: str = "検査PC_1", enabled: bool = True):
    from src.schemas.edge_pc import EdgePcCreate

    return repo.create(  # type: ignore[attr-defined]
        EdgePcCreate(name=name, host="169.254.93.171", model_port=2123, enabled=enabled)
    )


@pytest.mark.integration
def test_create_get_update_delete(db_session: Session) -> None:
    from src.repositories.edge_pc_repository import EdgePcRepository
    from src.schemas.edge_pc import EdgePcUpdate

    repo = EdgePcRepository(db_session)
    edge = _create(repo)
    assert repo.get(edge.id) is not None

    updated = repo.update(edge.id, EdgePcUpdate(host="10.0.0.1"))
    assert updated.host == "10.0.0.1"

    assert repo.delete(edge.id) is True
    assert repo.get(edge.id) is None


@pytest.mark.integration
def test_name_unique(db_session: Session) -> None:
    from src.repositories.edge_pc_repository import EdgePcRepository

    repo = EdgePcRepository(db_session)
    _create(repo, name="dup")
    with pytest.raises(IntegrityError):
        _create(repo, name="dup")


@pytest.mark.integration
def test_find_enabled_returns_only_enabled(db_session: Session) -> None:
    from src.repositories.edge_pc_repository import EdgePcRepository

    repo = EdgePcRepository(db_session)
    _create(repo, name="on", enabled=True)
    _create(repo, name="off", enabled=False)

    enabled = repo.find_enabled()
    assert {e.name for e in enabled} == {"on"}
    assert len(repo.list()) == 2
