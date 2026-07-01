"""training_service の統合テスト（subprocess・kill をモック）。

配置先: backend/tests/integration/test_training_service.py
要: pytest-asyncio（asyncio_mode=auto 推奨）。
"""
from __future__ import annotations

import asyncio
import os

import pytest

from conftest import FakeProcess, install_fake_subprocess, stub_process_group
from models.retraining_job import JobStatus
from repositories.retraining_repository import RetrainingRepository
from services.training_service import TrainingConfig, TrainingService


def _cfg(tmp_path) -> TrainingConfig:
    return TrainingConfig(training_dir=str(tmp_path), model_dir=str(tmp_path / "6_model"),
                          python_executable="python")


def _make_onnx(cfg: TrainingConfig, color: str) -> None:
    for mode in ("monochro", "color"):
        p = cfg.onnx_path(color, mode)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"onnx")


async def _drain(service: TrainingService, job_id: int) -> list[str]:
    """進捗を None まで読み切って行リストを返す。"""
    q = service.subscribe(job_id)
    lines: list[str] = []
    while True:
        line = await asyncio.wait_for(q.get(), timeout=5)
        if line is None:
            break
        lines.append(line)
    service.unsubscribe(job_id, q)
    return lines


def _status(session_factory, job_id) -> str:
    db = session_factory()
    try:
        return RetrainingRepository(db).get(job_id).status
    finally:
        db.close()


@pytest.mark.asyncio
async def test_job_completes_when_onnx_and_marker(monkeypatch, tmp_path, session_factory):
    cfg = _cfg(tmp_path)
    stub_process_group(monkeypatch)
    # 成功: 完了マーカーを出し、wait() 内で両 ONNX を生成
    install_fake_subprocess(monkeypatch, lambda cmd, kw: FakeProcess(
        ["学習開始", "Validation Loss: 0.1", "Exported ONNX: ...", "パイプライン完了"],
        on_wait=lambda: _make_onnx(cfg, "501"),
    ))
    svc = TrainingService(session_factory, cfg)
    await svc.start()

    db = session_factory(); job = RetrainingRepository(db).create_job("501", "05", "CZT8", "")
    db.commit(); job_id = job.id; db.close()

    lines = await _drain(svc, job_id)
    await svc.stop()

    assert _status(session_factory, job_id) == JobStatus.COMPLETED.value
    assert any("パイプライン完了" in l for l in lines)         # 素通しされている
    assert any(l.startswith("[STATUS] COMPLETED") for l in lines)


@pytest.mark.asyncio
async def test_job_fails_when_onnx_missing(monkeypatch, tmp_path, session_factory):
    cfg = _cfg(tmp_path)
    stub_process_group(monkeypatch)
    # マーカーは出るが ONNX を作らない → FAILED
    install_fake_subprocess(monkeypatch, lambda cmd, kw: FakeProcess(
        ["学習開始", "パイプライン完了"],
    ))
    svc = TrainingService(session_factory, cfg)
    await svc.start()
    db = session_factory(); jid = RetrainingRepository(db).create_job("777", "05", "CZT8", "").id
    db.commit(); db.close()
    await _drain(svc, jid)
    await svc.stop()
    assert _status(session_factory, jid) == JobStatus.FAILED.value


@pytest.mark.asyncio
async def test_job_fails_when_marker_missing(monkeypatch, tmp_path, session_factory):
    cfg = _cfg(tmp_path)
    stub_process_group(monkeypatch)
    # ONNX は出来るが完了マーカー無し → FAILED（終了コードに依存しない）
    install_fake_subprocess(monkeypatch, lambda cmd, kw: FakeProcess(
        ["学習途中で異常終了"], returncode=0, on_wait=lambda: _make_onnx(cfg, "888"),
    ))
    svc = TrainingService(session_factory, cfg)
    await svc.start()
    db = session_factory(); jid = RetrainingRepository(db).create_job("888", "05", "CZT8", "").id
    db.commit(); db.close()
    await _drain(svc, jid)
    await svc.stop()
    assert _status(session_factory, jid) == JobStatus.FAILED.value


@pytest.mark.asyncio
async def test_command_contains_expected_overrides(monkeypatch, tmp_path, session_factory):
    cfg = _cfg(tmp_path)
    stub_process_group(monkeypatch)
    captured: dict = {}

    def factory(cmd, kw):
        captured["cmd"] = cmd
        captured["cwd"] = kw.get("cwd")
        captured["start_new_session"] = kw.get("start_new_session")
        return FakeProcess(["パイプライン完了"], on_wait=lambda: _make_onnx(cfg, "501"))

    install_fake_subprocess(monkeypatch, factory)
    svc = TrainingService(session_factory, cfg)
    await svc.start()
    db = session_factory(); jid = RetrainingRepository(db).create_job("501", "05", "CZT8", "").id
    db.commit(); db.close()
    await _drain(svc, jid)
    await svc.stop()

    cmd = " ".join(captured["cmd"])
    assert "common.target_color=501" in cmd
    assert "common.pipeline_mode=train" in cmd
    assert "common.skip_download=true" in cmd
    assert "common.skip_upload=true" in cmd
    assert "mlflow.enabled=false" in cmd
    assert captured["cwd"] == cfg.training_dir
    assert captured["start_new_session"] is True       # プロセスグループ化


@pytest.mark.asyncio
async def test_fifo_runs_sequentially(monkeypatch, tmp_path, session_factory):
    cfg = _cfg(tmp_path)
    stub_process_group(monkeypatch)
    order: list[str] = []

    def factory(cmd, kw):
        color = next(c.split("=")[1] for c in cmd if c.startswith("common.target_color="))
        order.append(color)
        return FakeProcess(["パイプライン完了"], on_wait=lambda: _make_onnx(cfg, color))

    install_fake_subprocess(monkeypatch, factory)
    svc = TrainingService(session_factory, cfg)
    await svc.start()
    db = session_factory(); repo = RetrainingRepository(db)
    a = repo.create_job("111", "1", "c").id; b = repo.create_job("222", "1", "c").id
    db.commit(); db.close()
    await _drain(svc, a)
    await _drain(svc, b)
    await svc.stop()
    assert order == ["111", "222"]                     # FIFO・同時1本


@pytest.mark.asyncio
async def test_cancel_queued_job_is_skipped(monkeypatch, tmp_path, session_factory):
    cfg = _cfg(tmp_path)
    stub_process_group(monkeypatch)
    gate = asyncio.Event()
    ran: list[str] = []

    def factory(cmd, kw):
        color = next(c.split("=")[1] for c in cmd if c.startswith("common.target_color="))
        ran.append(color)
        # 最初のジョブは gate が開くまで RUNNING を維持し、2本目の QUEUED 中キャンセルを可能にする
        g = gate if color == "first" else None
        return FakeProcess(["パイプライン完了"], on_wait=lambda: _make_onnx(cfg, color), gate=g)

    install_fake_subprocess(monkeypatch, factory)
    svc = TrainingService(session_factory, cfg)
    await svc.start()
    db = session_factory(); repo = RetrainingRepository(db)
    j1 = repo.create_job("first", "1", "c").id
    j2 = repo.create_job("second", "1", "c").id
    db.commit(); db.close()

    await asyncio.sleep(0.05)                  # j1 を RUNNING にする
    accepted = await svc.cancel(j2)            # j2 はまだ QUEUED
    assert accepted is True
    gate.set()                                 # j1 を完了させる
    await _drain(svc, j1)
    await asyncio.sleep(0.05)
    await svc.stop()

    assert _status(session_factory, j2) == JobStatus.CANCELLED.value
    assert "second" not in ran                 # キャンセル済みは起動されない
