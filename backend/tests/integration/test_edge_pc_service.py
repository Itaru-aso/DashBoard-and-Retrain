"""エッジPC Service（edge E-R1, E-R5）の integration テスト（ftplib モック）。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session


def _svc(db: Session) -> object:
    from src.services.edge_pc_service import EdgePcService

    return EdgePcService(db)


def _create(svc: object):
    from src.schemas.edge_pc import EdgePcCreate

    return svc.create(  # type: ignore[attr-defined]
        EdgePcCreate(name="検査PC_1", host="169.254.93.171", model_port=2123)
    )


class _FakeFTP:
    def connect(self, *args: object, **kwargs: object) -> None:
        pass

    def login(self, *args: object, **kwargs: object) -> None:
        pass

    def quit(self) -> None:
        pass


@pytest.mark.integration
def test_service_crud(db_session: Session) -> None:
    svc = _svc(db_session)
    edge = _create(svc)
    assert svc.get(edge.id) is not None  # type: ignore[attr-defined]
    assert len(svc.list()) == 1  # type: ignore[attr-defined]
    assert svc.delete(edge.id) is True  # type: ignore[attr-defined]


@pytest.mark.integration
def test_check_ftp_success(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(db_session)
    edge = _create(svc)
    monkeypatch.setattr("src.services.edge_pc_service.FTP", lambda: _FakeFTP())

    result = svc.check_ftp(edge.id)  # type: ignore[attr-defined]
    assert result.last_ftp_ok is True
    assert result.last_ftp_checked_at is not None


@pytest.mark.integration
def test_check_ftp_failure(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(db_session)
    edge = _create(svc)

    def _broken() -> _FakeFTP:
        raise OSError("connection refused")

    monkeypatch.setattr("src.services.edge_pc_service.FTP", _broken)

    result = svc.check_ftp(edge.id)  # type: ignore[attr-defined]
    assert result.last_ftp_ok is False
