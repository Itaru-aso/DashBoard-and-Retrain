"""deployment_service（retraining M-R8）の integration テスト（FTP をフェイク注入）。

配信集約（SUCCESS/PARTIAL/FAILED）・色番ベースのリモート名・model_port・deployed upsert・
非 COMPLETED / ONNX 欠落の異常系を検証する。DB は commit する専用 session_factory を用いる。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def session_factory(ver2_engine: Engine) -> Iterator[Callable[[], Session]]:
    """commit する ver2 Session を返すファクトリ（テスト後に retraining 系を truncate）。"""
    factory = sessionmaker(bind=ver2_engine)
    try:
        yield factory
    finally:
        with ver2_engine.begin() as conn:
            conn.execute(text("TRUNCATE deployed_model, retraining_job RESTART IDENTITY CASCADE"))


class FakeEdgePc:
    """有効エッジPC の代役（find_enabled が返す最小属性）。"""

    def __init__(
        self,
        name: str,
        host: str = "host",
        username: str = "u",
        password: str = "p",
        model_port: int = 21,
    ) -> None:
        self.name = name
        self.host = host
        self.username = username
        self.password = password
        self.model_port = model_port


class FakeEdgePcRepo:
    """`find_enabled()` で固定リストを返す repo の代役。"""

    def __init__(self, pcs: list[FakeEdgePc]) -> None:
        self._pcs = pcs

    def find_enabled(self) -> list[FakeEdgePc]:
        return self._pcs


def _completed_job(session_factory, tmp_path, color: str = "501", tape: str = ""):
    from src.repositories.retraining_repository import RetrainingRepository

    db = session_factory()
    try:
        repo = RetrainingRepository(db)
        job = repo.create_job(color, "05", "CZT8", tape)
        db.commit()
        mono = str(tmp_path / f"{color}_monochro.onnx")
        col = str(tmp_path / f"{color}_color.onnx")
        for p in (mono, col):
            with open(p, "wb") as f:
                f.write(b"onnx")
        repo.mark_completed(job.id, mono, col)
        db.commit()
        return job.id
    finally:
        db.close()


def _service(session_factory, pcs, sender):
    from src.services.deployment_service import DeploymentService

    return DeploymentService(
        session_factory=session_factory,
        edge_pc_repo_factory=lambda db: FakeEdgePcRepo(pcs),
        ftp_sender=sender,
    )


def _deployed(session_factory, color: str, size: str, chain: str, tape: str):
    from src.repositories.retraining_repository import RetrainingRepository

    db = session_factory()
    try:
        return RetrainingRepository(db).get_deployed(color, size, chain, tape)
    finally:
        db.close()


@pytest.mark.integration
def test_deploy_all_success(session_factory, tmp_path) -> None:
    from src.models.deployed_model import DeployStatus

    job_id = _completed_job(session_factory, tmp_path)
    calls: list[dict] = []

    def sender(**kw):
        calls.append(kw)

    svc = _service(session_factory, [FakeEdgePc("pc1"), FakeEdgePc("pc2")], sender)
    result = svc.deploy_job(job_id)

    assert result["status"] == DeployStatus.SUCCESS.value
    assert result["edge_pc_count"] == 2
    # 2台 × 2モード = 4 送信・リモート名は色番ベース・ポートは model_port。
    assert len(calls) == 4
    assert {c["remote_name"] for c in calls} == {
        "501_monochro_model.onnx",
        "501_color_model.onnx",
    }
    assert {c["port"] for c in calls} == {21}

    dep = _deployed(session_factory, "501", "05", "CZT8", "")
    assert dep is not None and dep.deploy_status == DeployStatus.SUCCESS.value


@pytest.mark.integration
def test_deploy_partial_when_one_host_fails(session_factory, tmp_path) -> None:
    from src.models.deployed_model import DeployStatus

    job_id = _completed_job(session_factory, tmp_path)

    def sender(**kw):
        if kw["host"] == "bad":
            raise OSError("connection refused")

    pcs = [FakeEdgePc("ok", host="good"), FakeEdgePc("ng", host="bad")]
    result = _service(session_factory, pcs, sender).deploy_job(job_id)

    assert result["status"] == DeployStatus.PARTIAL.value
    assert result["detail"]["ng"]["ok"] is False
    assert result["detail"]["ok"]["ok"] is True


@pytest.mark.integration
def test_deploy_failed_when_all_fail(session_factory, tmp_path) -> None:
    from src.models.deployed_model import DeployStatus

    job_id = _completed_job(session_factory, tmp_path)

    def sender(**kw):
        raise OSError("down")

    svc = _service(session_factory, [FakeEdgePc("a"), FakeEdgePc("b")], sender)
    assert svc.deploy_job(job_id)["status"] == DeployStatus.FAILED.value


@pytest.mark.integration
def test_deploy_failed_when_no_edge_pc(session_factory, tmp_path) -> None:
    from src.models.deployed_model import DeployStatus

    job_id = _completed_job(session_factory, tmp_path)
    svc = _service(session_factory, [], lambda **kw: None)
    assert svc.deploy_job(job_id)["status"] == DeployStatus.FAILED.value


@pytest.mark.integration
def test_deploy_rejects_non_completed(session_factory, tmp_path) -> None:
    from src.repositories.retraining_repository import RetrainingRepository

    db = session_factory()
    job = RetrainingRepository(db).create_job("501", "05", "CZT8", "")  # QUEUED
    db.commit()
    job_id = job.id
    db.close()

    svc = _service(session_factory, [FakeEdgePc("a")], lambda **kw: None)
    with pytest.raises(ValueError):
        svc.deploy_job(job_id)


@pytest.mark.integration
def test_default_ftp_sender_falls_back_on_none(monkeypatch, tmp_path) -> None:
    """port/username/password が None でも 21/空文字にフォールバックして接続する。"""
    import ftplib

    from src.services.deployment_service import _default_ftp_sender

    captured: dict = {}

    class _FakeFTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def connect(self, host, port):
            captured["port"] = port

        def login(self, user, password):
            captured["login"] = (user, password)

        def storbinary(self, cmd, f):
            captured["stor"] = cmd

    monkeypatch.setattr(ftplib, "FTP", _FakeFTP)
    local = tmp_path / "m.onnx"
    local.write_bytes(b"onnx")

    _default_ftp_sender(
        host="h",
        port=None,
        username=None,
        password=None,
        local_path=str(local),
        remote_dir=".",
        remote_name="501_color_model.onnx",
        timeout=5,
    )
    assert captured["port"] == 21
    assert captured["login"] == ("", "")
    assert captured["stor"] == "STOR 501_color_model.onnx"


@pytest.mark.integration
def test_deploy_missing_onnx_raises(session_factory, tmp_path) -> None:
    from src.repositories.retraining_repository import RetrainingRepository

    db = session_factory()
    repo = RetrainingRepository(db)
    job = repo.create_job("501", "05", "CZT8", "")
    db.commit()
    # 実在しないパスで COMPLETED にする。
    repo.mark_completed(job.id, str(tmp_path / "nope_m.onnx"), str(tmp_path / "nope_c.onnx"))
    db.commit()
    job_id = job.id
    db.close()

    svc = _service(session_factory, [FakeEdgePc("a")], lambda **kw: None)
    with pytest.raises(FileNotFoundError):
        svc.deploy_job(job_id)
