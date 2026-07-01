"""deployment_service の単体テスト（FTP をフェイク注入）。

配置先: backend/tests/integration/test_deployment_service.py
"""
from __future__ import annotations

import os

import pytest

from conftest import FakeEdgePc, FakeEdgePcRepo
from models.deployed_model import DeployStatus
from repositories.retraining_repository import RetrainingRepository
from services.deployment_service import DeploymentService


def _completed_job(db, tmp_path, color="501", tape=""):
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
    return job


def _service(session_factory, pcs, sender):
    return DeploymentService(
        session_factory=session_factory,
        edge_pc_repo_factory=lambda db: FakeEdgePcRepo(pcs),
        ftp_sender=sender,
    )


def test_deploy_all_success(session_factory, tmp_path):
    db = session_factory(); job = _completed_job(db, tmp_path); db.close()
    calls = []
    def sender(**kw): calls.append(kw)
    svc = _service(session_factory, [FakeEdgePc("pc1"), FakeEdgePc("pc2")], sender)

    result = svc.deploy_job(job.id)

    assert result["status"] == DeployStatus.SUCCESS.value
    assert result["edge_pc_count"] == 2
    # 2台 × 2モード = 4 送信、リモート名は色番ベース
    assert len(calls) == 4
    names = {c["remote_name"] for c in calls}
    assert names == {"501_monochro_model.onnx", "501_color_model.onnx"}
    ports = {c["port"] for c in calls}
    assert ports == {21}                       # model_port

    db = session_factory()
    dep = RetrainingRepository(db).get_deployed("501", "05", "CZT8", "")
    db.close()
    assert dep is not None and dep.deploy_status == DeployStatus.SUCCESS.value


def test_deploy_partial_when_one_host_fails(session_factory, tmp_path):
    db = session_factory(); job = _completed_job(db, tmp_path); db.close()
    def sender(**kw):
        if kw["host"] == "bad":
            raise OSError("connection refused")
    pcs = [FakeEdgePc("ok", host="good"), FakeEdgePc("ng", host="bad")]
    svc = _service(session_factory, pcs, sender)

    result = svc.deploy_job(job.id)
    assert result["status"] == DeployStatus.PARTIAL.value
    assert result["detail"]["ng"]["ok"] is False
    assert result["detail"]["ok"]["ok"] is True


def test_deploy_failed_when_all_fail(session_factory, tmp_path):
    db = session_factory(); job = _completed_job(db, tmp_path); db.close()
    def sender(**kw): raise OSError("down")
    svc = _service(session_factory, [FakeEdgePc("a"), FakeEdgePc("b")], sender)
    assert svc.deploy_job(job.id)["status"] == DeployStatus.FAILED.value


def test_deploy_failed_when_no_edge_pc(session_factory, tmp_path):
    db = session_factory(); job = _completed_job(db, tmp_path); db.close()
    svc = _service(session_factory, [], lambda **kw: None)
    assert svc.deploy_job(job.id)["status"] == DeployStatus.FAILED.value


def test_deploy_rejects_non_completed(session_factory, tmp_path):
    db = session_factory()
    job = RetrainingRepository(db).create_job("501", "05", "CZT8", "")  # QUEUED
    db.commit(); db.close()
    svc = _service(session_factory, [FakeEdgePc("a")], lambda **kw: None)
    with pytest.raises(ValueError):
        svc.deploy_job(job.id)


def test_deploy_missing_onnx_raises(session_factory, tmp_path):
    db = session_factory()
    repo = RetrainingRepository(db)
    job = repo.create_job("501", "05", "CZT8", "")
    db.commit()
    repo.mark_completed(job.id, str(tmp_path / "nope_m.onnx"), str(tmp_path / "nope_c.onnx"))
    db.commit(); db.close()
    svc = _service(session_factory, [FakeEdgePc("a")], lambda **kw: None)
    with pytest.raises(FileNotFoundError):
        svc.deploy_job(job.id)
