"""training_service（retraining M-R2〜M-R7）の integration テスト（subprocess・kill をモック）。

pytest-asyncio を使わず、各テストは `asyncio.run` でシナリオを回す。DB は commit する
専用 session_factory を用い、テスト後に該当テーブルを truncate して隔離する。
"""

from __future__ import annotations

import asyncio
import json
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
    cmd = cfg.build_command("501", "5", "YY")
    assert not any(c.startswith("common.imagenet_train_path=") for c in cmd)


@pytest.mark.integration
def test_build_command_omits_data_root_overrides_when_unset(tmp_path: object) -> None:
    cfg = _cfg(tmp_path)
    cmd = cfg.build_command("501", "5", "YY")
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
    cmd = cfg.build_command("501", "5", "YY")
    assert "common.pretraining_dir=/retrain_app_CW/0_pretraining" in cmd
    assert "common.dataset_path=/retrain_app_CW/4_dataset" in cmd
    assert "common.backup_dir=/retrain_app_CW/backup" in cmd
    assert "common.pool_base=/retrain_app_CW/3_pool" in cmd
    # task13 で training/ 側の download_dir/staging_dir キーは廃止済み（override自体も送らない）。
    assert not any(c.startswith("common.download_dir=") for c in cmd)
    # task16 で monochro.py が raw_image_root を読まなくなったため override自体も送らない。
    assert not any(c.startswith("monochro.raw_image_root=") for c in cmd)
    assert not any(c.startswith("common.staging_dir=") for c in cmd)


@pytest.mark.integration
def test_build_command_overrides_imagenet_when_set(tmp_path: object) -> None:
    from src.services.training_service import TrainingConfig

    cfg = TrainingConfig(
        training_dir=str(tmp_path),
        model_dir=os.path.join(str(tmp_path), "6_model"),
        python_executable="python",
        imagenet_train_path="/imagenet/train",
    )
    cmd = cfg.build_command("501", "5", "YY")
    assert "common.imagenet_train_path=/imagenet/train" in cmd


@pytest.mark.integration
def test_build_command_omits_dataset_id_overrides_when_not_found() -> None:
    """dataset_idが解決できない場合はoverride自体を送らない（空値=Noneでconfig.yaml側の
    既定（空文字）を上書きしてしまうのを避ける）。"""
    from src.services.training_service import TrainingConfig

    cfg = TrainingConfig(training_dir="/x", model_dir="/x/6_model", python_executable="python")
    cmd = cfg.build_command("501", "5", "YY")
    assert not any(c.startswith("common.dataset_id_monochro=") for c in cmd)
    assert not any(c.startswith("common.dataset_id_color=") for c in cmd)
    assert not any(c.startswith("common.dataset_id_monochro_margin=") for c in cmd)


@pytest.mark.integration
def test_build_command_wires_export_root_and_dataset_ids(tmp_path: object) -> None:
    """検証基準5: export_root/margin_export_rootが設定されている場合の一連の配線を確認する。"""
    from src.services.training_service import TrainingConfig

    export_root = os.path.join(str(tmp_path), "export_root")
    margin_root = os.path.join(str(tmp_path), "export_root_margin")
    _write_dataset_metadata(export_root, "ds-mono-1", "monochro_5_YY")
    _write_dataset_metadata(export_root, "ds-color-1", "color_5_YY")
    _write_dataset_metadata(margin_root, "ds-margin-1", "monochro_5_YY")

    cfg = TrainingConfig(
        training_dir=str(tmp_path),
        model_dir=os.path.join(str(tmp_path), "6_model"),
        python_executable="python",
        export_root=export_root,
        margin_export_root=margin_root,
    )
    cmd = cfg.build_command("501", "5", "YY")
    assert f"common.export_root={export_root}" in cmd
    assert f"common.margin_export_root={margin_root}" in cmd
    assert "common.dataset_id_monochro=ds-mono-1" in cmd
    assert "common.dataset_id_color=ds-color-1" in cmd
    assert "common.dataset_id_monochro_margin=ds-margin-1" in cmd


@pytest.mark.integration
def test_build_command_omits_export_root_overrides_when_unset(tmp_path: object) -> None:
    cfg = _cfg(tmp_path)
    cmd = cfg.build_command("501", "5", "YY")
    assert not any(c.startswith("common.export_root=") for c in cmd)
    assert not any(c.startswith("common.margin_export_root=") for c in cmd)


def _write_dataset_metadata(export_root: object, dataset_id: str, name: str) -> None:
    # metadata.json の "id" はフォルダ名（dataset_id）とは別物（実データでも一致しない）。
    # resolve_dataset_id はフォルダ名を返す実装であることをテストで固定するため、意図的に
    # 異なる値にしておく（"id" を返すよう実装が変わってもテストが緑のままにならないように）。
    ds_dir = os.path.join(str(export_root), dataset_id)
    os.makedirs(ds_dir, exist_ok=True)
    with open(os.path.join(ds_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"id": f"{dataset_id}-metadata-uuid", "name": name, "category": []}, f)


@pytest.mark.integration
def test_resolve_dataset_id_finds_matching_name(tmp_path: object) -> None:
    from src.services.training_service import TrainingConfig

    export_root = os.path.join(str(tmp_path), "export_root")
    _write_dataset_metadata(export_root, "ds-mono-1", "monochro_5_YY")
    _write_dataset_metadata(export_root, "ds-color-1", "color_5_YY")

    cfg = TrainingConfig(
        training_dir=str(tmp_path),
        model_dir=os.path.join(str(tmp_path), "6_model"),
        export_root=export_root,
    )

    assert cfg.resolve_dataset_id("monochro", "5", "YY") == "ds-mono-1"
    assert cfg.resolve_dataset_id("color", "5", "YY") == "ds-color-1"


@pytest.mark.integration
def test_resolve_dataset_id_returns_empty_when_not_found(tmp_path: object) -> None:
    from src.services.training_service import TrainingConfig

    export_root = os.path.join(str(tmp_path), "export_root")
    _write_dataset_metadata(export_root, "ds-mono-1", "monochro_5_YY")

    cfg = TrainingConfig(
        training_dir=str(tmp_path),
        model_dir=os.path.join(str(tmp_path), "6_model"),
        export_root=export_root,
    )

    assert cfg.resolve_dataset_id("monochro", "9", "ZZ") == ""


@pytest.mark.integration
def test_resolve_margin_dataset_id_falls_back_to_empty_when_missing(tmp_path: object) -> None:
    """マージン側が見つからない場合は空文字にフォールバックし、非致命的に処理が継続する
    （dataset-export-root-migration.md 決定16）。"""
    from src.services.training_service import TrainingConfig

    cfg = TrainingConfig(
        training_dir=str(tmp_path),
        model_dir=os.path.join(str(tmp_path), "6_model"),
        margin_export_root=os.path.join(str(tmp_path), "no_such_dir"),
    )

    assert cfg.resolve_margin_dataset_id("5", "YY") == ""


@pytest.mark.integration
def test_resolve_margin_dataset_id_finds_matching_name(tmp_path: object) -> None:
    from src.services.training_service import TrainingConfig

    margin_root = os.path.join(str(tmp_path), "export_root_margin")
    _write_dataset_metadata(margin_root, "ds-margin-1", "monochro_5_YY")

    cfg = TrainingConfig(
        training_dir=str(tmp_path),
        model_dir=os.path.join(str(tmp_path), "6_model"),
        margin_export_root=margin_root,
    )

    assert cfg.resolve_margin_dataset_id("5", "YY") == "ds-margin-1"


@pytest.mark.integration
def test_final_onnx_path_builds_tuple_scoped_path() -> None:
    """検証基準11: (color_no,size,chain,tape,mode)から最終ONNXパスを正しく組み立てる。"""
    from src.services.training_service import TrainingConfig

    cfg = TrainingConfig(training_dir="/x", model_dir="/model_root")
    assert cfg.final_onnx_path("501", "5", "YY", "CZT8", "monochro") == os.path.join(
        "/model_root", "501", "5_YY_CZT8", "monochro", "501_5_YY_CZT8_monochro_model.onnx"
    )
    assert cfg.final_onnx_path("501", "5", "YY", "CZT8", "color") == os.path.join(
        "/model_root", "501", "5_YY_CZT8", "color", "501_5_YY_CZT8_color_model.onnx"
    )


@pytest.mark.integration
def test_final_onnx_path_keeps_empty_tape_as_is() -> None:
    """tapeが空文字の場合は空文字のまま連結する（決定22。プレースホルダは使わない）。"""
    from src.services.training_service import TrainingConfig

    cfg = TrainingConfig(training_dir="/x", model_dir="/model_root")
    assert cfg.final_onnx_path("501", "5", "YY", "", "monochro") == os.path.join(
        "/model_root", "501", "5_YY_", "monochro", "501_5_YY__monochro_model.onnx"
    )


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
def test_completion_promotes_onnx_to_final_tuple_path_and_overwrites_on_rerun(
    monkeypatch, tmp_path, session_factory
) -> None:
    """検証基準12: 完了処理がステージングパスから最終パス（フルタプル別）へ移動し、
    mark_completed に最終パスを渡すこと。同一タプルで2回連続完了させた場合、
    2回目の最終ファイルが1回目を正しく上書きすることを確認する。"""
    from src.models.retraining_job import JobStatus
    from src.repositories.retraining_repository import RetrainingRepository
    from src.services.training_service import TrainingService

    cfg = _cfg(tmp_path)
    _stub_process_group(monkeypatch)

    def _get_paths(jid: int) -> tuple[str | None, str | None]:
        db = session_factory()
        try:
            job = RetrainingRepository(db).get(jid)
            assert job is not None
            return job.onnx_monochro_path, job.onnx_color_path
        finally:
            db.close()

    def _write_onnx(content: bytes) -> None:
        for mode in ("monochro", "color"):
            p = cfg.onnx_path("501", mode)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(content)

    expected_mono_final = cfg.final_onnx_path("501", "05", "CZT8", "", "monochro")
    expected_color_final = cfg.final_onnx_path("501", "05", "CZT8", "", "color")

    async def scenario() -> tuple[bytes, bytes]:
        svc = TrainingService(session_factory, cfg)
        await svc.start()

        _install_fake_subprocess(
            monkeypatch,
            lambda cmd, kw: FakeProcess(
                ["パイプライン完了"], on_wait=lambda: _write_onnx(b"onnx-v1")
            ),
        )
        jid1 = _create_job(session_factory, "501")
        svc.enqueue(jid1)
        await _drain(svc, jid1)
        assert _status(session_factory, jid1) == JobStatus.COMPLETED.value
        mono1, color1 = _get_paths(jid1)
        assert mono1 == expected_mono_final
        assert color1 == expected_color_final
        # ステージング(training/固定パス)は移動済みで存在しない（同タプル最新のみ保持の前提として、
        # 移動先=最終パスにのみ実体があること）。
        assert not os.path.isfile(cfg.onnx_path("501", "monochro"))
        with open(expected_mono_final, "rb") as f:
            first_content = f.read()

        _install_fake_subprocess(
            monkeypatch,
            lambda cmd, kw: FakeProcess(
                ["パイプライン完了"], on_wait=lambda: _write_onnx(b"onnx-v2")
            ),
        )
        jid2 = _create_job(session_factory, "501")
        svc.enqueue(jid2)
        await _drain(svc, jid2)
        assert _status(session_factory, jid2) == JobStatus.COMPLETED.value
        mono2, _color2 = _get_paths(jid2)
        assert mono2 == expected_mono_final  # 同タプル → 同じ最終パス

        await svc.stop()
        with open(expected_mono_final, "rb") as f:
            second_content = f.read()
        return first_content, second_content

    first_content, second_content = asyncio.run(scenario())
    assert first_content == b"onnx-v1"
    assert second_content == b"onnx-v2"  # 2回目が1回目を正しく上書き


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
    # 検証基準5: export_root未設定（=解決不能）時はdataset_id override自体を送らないこと
    # （DBから取得したsize="05"/chain="CZT8"はresolve_dataset_idに渡るがcfg.export_root=""のため
    # 解決結果は空文字になり、override自体が省略される）。
    assert "common.dataset_id_monochro=" not in cmd
    assert "common.dataset_id_color=" not in cmd
    assert "common.dataset_id_monochro_margin=" not in cmd
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
