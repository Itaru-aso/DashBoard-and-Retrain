"""training_service（retraining M-R2〜M-R7）の integration テスト（subprocess・kill をモック）。

pytest-asyncio を使わず、各テストは `asyncio.run` でシナリオを回す。DB は commit する
専用 session_factory を用い、テスト後に該当テーブルを truncate して隔離する。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator

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


class _FakeStdout:
    """実際の asyncio.StreamReader に裏付けさせる（readline の上限挙動も本物同様に再現）。"""

    def __init__(self, lines: list[str]) -> None:
        self._reader = asyncio.StreamReader()
        data = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
        self._reader.feed_data(data)
        self._reader.feed_eof()

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._reader.__aiter__()

    async def read(self, n: int = -1) -> bytes:
        return await self._reader.read(n)


class FakeProcess:
    """asyncio subprocess の代役。stdout を素通しし、wait() で on_wait を実行する。"""

    def __init__(
        self,
        lines: list[str],
        returncode: int = 0,
        on_wait: Callable[[], None] | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.stdout = _FakeStdout(lines)
        self._returncode = returncode
        self.returncode: int | None = None
        self.pid = 4321
        self._on_wait = on_wait
        self._gate = gate

    async def wait(self) -> int:
        if self._gate is not None:
            await self._gate.wait()
        if self._on_wait is not None:
            self._on_wait()
        self.returncode = self._returncode
        return self._returncode


def _install_fake_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    factory: Callable[[list[str], dict], FakeProcess],
) -> None:
    async def _fake_exec(*cmd: str, **kw: object) -> FakeProcess:
        return factory(list(cmd), kw)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)


def _stub_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """POSIX 専用のプロセスグループ API を Windows でも呼べるよう stub する。"""
    monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: None, raising=False)


def _cfg(tmp_path: object):
    from src.services.training_service import TrainingConfig

    return TrainingConfig(
        training_dir=str(tmp_path),
        model_dir=os.path.join(str(tmp_path), "6_model"),
        python_executable="python",
    )


@pytest.mark.integration
def test_build_command_omits_imagenet_override_when_unset(tmp_path: object) -> None:
    cfg = _cfg(tmp_path)
    cmd = cfg.build_command("501")
    assert not any(c.startswith("common.imagenet_train_path=") for c in cmd)


@pytest.mark.integration
def test_build_command_omits_data_root_overrides_when_unset(tmp_path: object) -> None:
    cfg = _cfg(tmp_path)
    cmd = cfg.build_command("501")
    assert not any(c.startswith("common.pool_base=") for c in cmd)


@pytest.mark.integration
def test_build_command_overrides_data_paths_when_data_root_set(tmp_path: object) -> None:
    from src.services.training_service import TrainingConfig

    cfg = TrainingConfig(
        training_dir=str(tmp_path),
        model_dir=os.path.join(str(tmp_path), "6_model"),
        python_executable="python",
        data_root="/retrain_app_CW",
    )
    cmd = cfg.build_command("501")
    assert "common.pretraining_dir=/retrain_app_CW/0_pretraining" in cmd
    assert "common.dataset_path=/retrain_app_CW/4_dataset" in cmd
    assert "common.backup_dir=/retrain_app_CW/backup" in cmd
    assert "common.download_dir=/retrain_app_CW/1_download" in cmd
    assert "common.pool_base=/retrain_app_CW/3_pool" in cmd
    assert "common.staging_dir=/retrain_app_CW/2_staging" in cmd
    assert "monochro.raw_image_root=/retrain_app_CW/1_download" in cmd


@pytest.mark.integration
def test_build_command_overrides_imagenet_when_set(tmp_path: object) -> None:
    from src.services.training_service import TrainingConfig

    cfg = TrainingConfig(
        training_dir=str(tmp_path),
        model_dir=os.path.join(str(tmp_path), "6_model"),
        python_executable="python",
        imagenet_train_path="/imagenet/train",
    )
    cmd = cfg.build_command("501")
    assert "common.imagenet_train_path=/imagenet/train" in cmd


def _make_onnx(cfg: object, color: str) -> None:
    for mode in ("monochro", "color"):
        p = cfg.onnx_path(color, mode)  # type: ignore[attr-defined]
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"onnx")


async def _drain(service: object, job_id: int) -> list[str]:
    q = service.subscribe(job_id)  # type: ignore[attr-defined]
    lines: list[str] = []
    while True:
        line = await asyncio.wait_for(q.get(), timeout=5)
        if line is None:
            break
        lines.append(line)
    service.unsubscribe(job_id, q)  # type: ignore[attr-defined]
    return lines


def _status(session_factory: Callable[[], Session], job_id: int) -> str:
    from src.repositories.retraining_repository import RetrainingRepository

    db = session_factory()
    try:
        return RetrainingRepository(db).get(job_id).status
    finally:
        db.close()


def _create_job(session_factory: Callable[[], Session], color: str) -> int:
    from src.repositories.retraining_repository import RetrainingRepository

    db = session_factory()
    try:
        job = RetrainingRepository(db).create_job(color, "05", "CZT8", "")
        db.commit()
        return job.id
    finally:
        db.close()


@pytest.mark.integration
def test_job_completes_when_onnx_and_marker(monkeypatch, tmp_path, session_factory) -> None:
    from src.models.retraining_job import JobStatus
    from src.services.training_service import TrainingService

    cfg = _cfg(tmp_path)
    _stub_process_group(monkeypatch)
    _install_fake_subprocess(
        monkeypatch,
        lambda cmd, kw: FakeProcess(
            ["学習開始", "Validation Loss: 0.1", "パイプライン完了"],
            on_wait=lambda: _make_onnx(cfg, "501"),
        ),
    )

    async def scenario() -> list[str]:
        svc = TrainingService(session_factory, cfg)
        await svc.start()
        jid = _create_job(session_factory, "501")
        svc.enqueue(jid)
        lines = await _drain(svc, jid)
        await svc.stop()
        assert _status(session_factory, jid) == JobStatus.COMPLETED.value
        return lines

    lines = asyncio.run(scenario())
    assert any("パイプライン完了" in ln for ln in lines)  # 素通し
    assert any(ln.startswith("[STATUS] COMPLETED") for ln in lines)


@pytest.mark.integration
def test_job_completes_with_long_progress_line_without_newline(
    monkeypatch, tmp_path, session_factory
) -> None:
    """tqdm 進捗のように `\\r` のみで 64KiB を超える1行（`\\n` 無し）が来ても FAILED にならない。

    `readline()`（`readuntil`）ベースだと StreamReader の上限（既定 64KiB）で
    `ValueError('Separator is not found, and chunk exceed the limit')` になり、
    実際に学習は完了していても内部エラーとして FAILED 記録されていた。
    """
    from src.models.retraining_job import JobStatus
    from src.services.training_service import TrainingService

    cfg = _cfg(tmp_path)
    _stub_process_group(monkeypatch)
    # tqdm の \r 進捗更新を模した、\n を含まない 64KiB 超の1行。
    progress = "\r".join(f"Current loss: 0.1  : {i}/100000" for i in range(3000))
    assert len(progress.encode("utf-8")) > 65536
    _install_fake_subprocess(
        monkeypatch,
        lambda cmd, kw: FakeProcess(
            ["学習開始", progress, "パイプライン完了"],
            on_wait=lambda: _make_onnx(cfg, "501"),
        ),
    )

    async def scenario() -> None:
        svc = TrainingService(session_factory, cfg)
        await svc.start()
        jid = _create_job(session_factory, "501")
        svc.enqueue(jid)
        await _drain(svc, jid)
        await svc.stop()
        assert _status(session_factory, jid) == JobStatus.COMPLETED.value

    asyncio.run(scenario())


@pytest.mark.integration
def test_job_fails_when_onnx_missing(monkeypatch, tmp_path, session_factory) -> None:
    from src.models.retraining_job import JobStatus
    from src.services.training_service import TrainingService

    cfg = _cfg(tmp_path)
    _stub_process_group(monkeypatch)
    _install_fake_subprocess(
        monkeypatch, lambda cmd, kw: FakeProcess(["学習開始", "パイプライン完了"])
    )

    async def scenario() -> None:
        svc = TrainingService(session_factory, cfg)
        await svc.start()
        jid = _create_job(session_factory, "777")
        svc.enqueue(jid)
        await _drain(svc, jid)
        await svc.stop()
        assert _status(session_factory, jid) == JobStatus.FAILED.value

    asyncio.run(scenario())


@pytest.mark.integration
def test_job_fails_when_marker_missing(monkeypatch, tmp_path, session_factory) -> None:
    from src.models.retraining_job import JobStatus
    from src.services.training_service import TrainingService

    cfg = _cfg(tmp_path)
    _stub_process_group(monkeypatch)
    # ONNX は出来るが完了マーカー無し → FAILED（終了コードに依存しない）。
    _install_fake_subprocess(
        monkeypatch,
        lambda cmd, kw: FakeProcess(
            ["学習途中で異常終了"], returncode=0, on_wait=lambda: _make_onnx(cfg, "888")
        ),
    )

    async def scenario() -> None:
        svc = TrainingService(session_factory, cfg)
        await svc.start()
        jid = _create_job(session_factory, "888")
        svc.enqueue(jid)
        await _drain(svc, jid)
        await svc.stop()
        assert _status(session_factory, jid) == JobStatus.FAILED.value

    asyncio.run(scenario())


@pytest.mark.integration
def test_command_contains_expected_overrides(monkeypatch, tmp_path, session_factory) -> None:
    from src.services.training_service import TrainingService

    cfg = _cfg(tmp_path)
    _stub_process_group(monkeypatch)
    captured: dict = {}

    def factory(cmd, kw):
        captured["cmd"] = cmd
        captured["cwd"] = kw.get("cwd")
        captured["start_new_session"] = kw.get("start_new_session")
        return FakeProcess(["パイプライン完了"], on_wait=lambda: _make_onnx(cfg, "501"))

    _install_fake_subprocess(monkeypatch, factory)

    async def scenario() -> None:
        svc = TrainingService(session_factory, cfg)
        await svc.start()
        jid = _create_job(session_factory, "501")
        svc.enqueue(jid)
        await _drain(svc, jid)
        await svc.stop()

    asyncio.run(scenario())

    cmd = " ".join(captured["cmd"])
    assert "common.target_color=501" in cmd
    assert "common.pipeline_mode=train" in cmd
    assert "common.skip_download=true" in cmd
    assert "common.skip_upload=true" in cmd
    assert "mlflow.enabled=false" in cmd
    assert captured["cwd"] == cfg.training_dir
    assert captured["start_new_session"] is True  # プロセスグループ化


@pytest.mark.integration
def test_fifo_runs_sequentially(monkeypatch, tmp_path, session_factory) -> None:
    from src.services.training_service import TrainingService

    cfg = _cfg(tmp_path)
    _stub_process_group(monkeypatch)
    order: list[str] = []

    def factory(cmd, kw):
        color = next(c.split("=")[1] for c in cmd if c.startswith("common.target_color="))
        order.append(color)
        return FakeProcess(["パイプライン完了"], on_wait=lambda: _make_onnx(cfg, color))

    _install_fake_subprocess(monkeypatch, factory)

    async def scenario() -> None:
        svc = TrainingService(session_factory, cfg)
        await svc.start()
        a = _create_job(session_factory, "111")
        b = _create_job(session_factory, "222")
        svc.enqueue(a)
        svc.enqueue(b)
        await _drain(svc, a)
        await _drain(svc, b)
        await svc.stop()

    asyncio.run(scenario())
    assert order == ["111", "222"]  # FIFO・同時1本


@pytest.mark.integration
def test_cancel_queued_job_is_skipped(monkeypatch, tmp_path, session_factory) -> None:
    from src.models.retraining_job import JobStatus
    from src.services.training_service import TrainingService

    cfg = _cfg(tmp_path)
    _stub_process_group(monkeypatch)
    ran: list[str] = []

    async def scenario() -> int:
        gate = asyncio.Event()

        def factory(cmd, kw):
            color = next(c.split("=")[1] for c in cmd if c.startswith("common.target_color="))
            ran.append(color)
            g = gate if color == "first" else None
            return FakeProcess(["パイプライン完了"], on_wait=lambda: _make_onnx(cfg, color), gate=g)

        _install_fake_subprocess(monkeypatch, factory)
        svc = TrainingService(session_factory, cfg)
        await svc.start()
        j1 = _create_job(session_factory, "first")
        j2 = _create_job(session_factory, "second")
        svc.enqueue(j1)
        svc.enqueue(j2)

        await asyncio.sleep(0.05)  # j1 を RUNNING にする
        accepted = await svc.cancel(j2)  # j2 はまだ QUEUED
        assert accepted is True
        gate.set()  # j1 を完了させる
        await _drain(svc, j1)
        await asyncio.sleep(0.05)  # ワーカが j2 を取り出してスキップ
        await svc.stop()
        return j2

    j2 = asyncio.run(scenario())
    assert _status(session_factory, j2) == JobStatus.CANCELLED.value
    assert "second" not in ran  # キャンセル済みは起動されない


@pytest.mark.integration
def test_cancel_running_job_ends_cancelled(monkeypatch, tmp_path, session_factory) -> None:
    """RUNNING 中のキャンセルは CANCELLED で確定し、後段の成功判定で FAILED に上書きされない。"""
    from src.models.retraining_job import JobStatus
    from src.services.training_service import TrainingService

    cfg = _cfg(tmp_path)

    async def scenario() -> int:
        gate = asyncio.Event()
        # kill 時にプロセス終了を模してゲートを開く（ONNX は生成しない＝キャンセル）。
        monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)
        monkeypatch.setattr(os, "killpg", lambda pgid, sig: gate.set(), raising=False)
        _install_fake_subprocess(monkeypatch, lambda cmd, kw: FakeProcess(["学習中..."], gate=gate))
        svc = TrainingService(session_factory, cfg)
        await svc.start()
        jid = _create_job(session_factory, "501")
        q = svc.subscribe(jid)
        svc.enqueue(jid)

        # RUNNING に到達するまで待つ。
        for _ in range(100):
            if svc.current_job_id == jid:
                break
            await asyncio.sleep(0.02)
        assert svc.current_job_id == jid

        accepted = await svc.cancel(jid)
        assert accepted is True

        # 進捗ストリームが閉じる（None）まで読み切る。
        while True:
            line = await asyncio.wait_for(q.get(), timeout=5)
            if line is None:
                break
        svc.unsubscribe(jid, q)
        await svc.stop()
        return jid

    jid = asyncio.run(scenario())
    assert _status(session_factory, jid) == JobStatus.CANCELLED.value
