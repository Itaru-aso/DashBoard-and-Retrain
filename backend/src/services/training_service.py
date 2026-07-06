"""モデル再学習のオーケストレーション（ver2・retraining M-R2〜M-R7）。

学習アルゴリズムは扱わない（`training/pipline.py` を subprocess 起動するだけ）。
- in-process の asyncio キュー＋**単一ワーカ**で **FIFO・同時1本**に実行（`uvicorn --workers 1` 前提）。
- 起動: `python pipline.py common.target_color=<color_no> common.pipeline_mode=train
  common.skip_download=true common.skip_upload=true color.mlflow.enabled=false
  monochro.mlflow.enabled=false` を `training/` を CWD に。画像は別機能が `1_download`
  に事前配置。配信は deployment_service。
- 進捗: subprocess の標準出力を**1行ずつ素通し**で WebSocket 購読者へ配信（揮発）。
- 成功判定: **終了コードに依存しない**。両 mode の ONNX 生成有無＋標準出力の `パイプライン完了` マーカー。
- キャンセル: QUEUED はキューから除外。RUNNING は**プロセスグループごと kill**（spawn 子も含めて停止）。
- 状態は DB を正として都度永続（`RetrainingRepository`）。

注: プロセスグループ kill（`os.killpg`/`os.getpgid`/`signal.SIGKILL`）は POSIX 専用。本番は Linux/Docker
（`nvidia/cuda` ベース）で稼働する。開発機（Windows）では mypy 用に型無視し、テストでは stub する。
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from sqlalchemy.orm import Session

from src.models.retraining_job import JobStatus
from src.repositories.retraining_repository import RetrainingRepository

logger = logging.getLogger(__name__)

COMPLETION_MARKER = "パイプライン完了"
_RECENT_LINES = 200  # WS 後追い接続者向けの直近ログ保持数（揮発）


@dataclass
class TrainingConfig:
    """学習側起動の設定（`config.py` / env から注入）。"""

    training_dir: str  # `training/` の絶対パス（CWD）
    model_dir: str  # ONNX 出力ルート（例 training_dir/6_model）
    python_executable: str = "python"  # 学習環境の python（cu128 入りイメージ）
    entry: str = "pipline.py"
    # 既定で付与する dotlist override（収集スコープ外・配信分離・mlflow 無効）
    base_overrides: tuple[str, ...] = (
        "common.pipeline_mode=train",
        "common.skip_download=true",
        "common.skip_upload=true",
        "color.mlflow.enabled=false",
        "monochro.mlflow.enabled=false",
    )

    def onnx_path(self, color_no: str, mode: str) -> str:
        """成果物 ONNX パス: model_dir/<color>/<mode>/<color>_<mode>_model.onnx（mode=monochro/color）。"""
        return os.path.join(self.model_dir, color_no, mode, f"{color_no}_{mode}_model.onnx")

    def build_command(self, color_no: str) -> list[str]:
        """起動コマンドを組み立てる（色番は文字列で渡す）。"""
        return [
            self.python_executable,
            self.entry,
            f"common.target_color={color_no}",
            *self.base_overrides,
        ]


class _ProgressHub:
    """ジョブごとの進捗配信（揮発）。購読者ごとに asyncio.Queue を配り、行を素通しでブロードキャストする。"""

    def __init__(self) -> None:
        self._subs: dict[int, set[asyncio.Queue[str | None]]] = {}
        self._recent: dict[int, deque[str]] = {}

    def subscribe(self, job_id: int) -> asyncio.Queue[str | None]:
        """購読キューを配る（後追い接続者へは直近ログを先に流す）。"""
        q: asyncio.Queue[str | None] = asyncio.Queue()
        for line in self._recent.get(job_id, ()):
            q.put_nowait(line)
        self._subs.setdefault(job_id, set()).add(q)
        return q

    def unsubscribe(self, job_id: int, q: asyncio.Queue[str | None]) -> None:
        """購読解除する。"""
        subs = self._subs.get(job_id)
        if subs and q in subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(job_id, None)

    def publish(self, job_id: int, line: str) -> None:
        """1行を購読者へ配信し、直近バッファへ積む。"""
        buf = self._recent.setdefault(job_id, deque(maxlen=_RECENT_LINES))
        buf.append(line)
        for q in self._subs.get(job_id, set()):
            q.put_nowait(line)

    def close(self, job_id: int) -> None:
        """ストリーム終了を購読者へ通知（None センチネル）し、直近バッファを破棄する。"""
        for q in self._subs.get(job_id, set()):
            q.put_nowait(None)
        self._recent.pop(job_id, None)


class TrainingService:
    """再学習ジョブのキュー・実行・キャンセルを司るシングルトン。"""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        config: TrainingConfig,
        on_completed: Callable[[int], object] | None = None,
    ) -> None:
        """初期化する。

        Args:
            session_factory: ver2 同期 Session を返すファクトリ（close 可能なもの）。
            config: 学習側起動の設定。
            on_completed: COMPLETED 時に呼ぶフック（deployment_service の自動配信を注入・任意・非同期可）。
        """
        self._session_factory = session_factory
        self._cfg = config
        self._on_completed = on_completed

        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._hub = _ProgressHub()

        self._current_job_id: int | None = None
        self._current_proc: asyncio.subprocess.Process | None = None
        self._cancelled: set[int] = set()  # QUEUED 中にキャンセル要求された job_id
        self._lock = asyncio.Lock()

    # ---- ライフサイクル（main.py の lifespan から呼ぶ） ----

    async def start(self) -> None:
        """ワーカ起動。再起動時の復旧（消えた RUNNING を FAILED・QUEUED を再投入）も行う。"""
        await asyncio.to_thread(self._recover_on_start)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_worker(), name="retraining-worker")

    async def stop(self) -> None:
        """ワーカ停止。実行中プロセスはプロセスグループごと停止する。"""
        if self._current_proc is not None:
            await self._kill_current()
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    def _recover_on_start(self) -> None:
        # 復旧は best-effort。DB 到達不能でも起動をクラッシュさせない（ワーカは起動する）。
        try:
            with self._session_scope() as db:
                repo = RetrainingRepository(db)
                for job in repo.list_active():
                    if job.status == JobStatus.RUNNING.value:
                        # プロセスはプロセス再起動で失われている。
                        repo.mark_failed(job.id, "プロセス再起動により中断されました")
                    else:  # QUEUED → 再投入
                        self._queue.put_nowait(job.id)
        except Exception:  # noqa: BLE001  起動時 DB エラーは握りつぶす（復旧は次回に委ねる）
            logger.warning("再学習ジョブの起動時復旧に失敗しました（続行）", exc_info=True)

    # ---- 公開 API（API 層から呼ぶ） ----

    def enqueue(self, job_id: int) -> None:
        """作成済み（QUEUED）ジョブをキューに投入する。"""
        self._queue.put_nowait(job_id)

    async def cancel(self, job_id: int) -> bool:
        """ジョブをキャンセルする（RUNNING はプロセスグループ kill・QUEUED は実行前に除外）。

        Returns:
            受理したら True。
        """
        async with self._lock:
            if self._current_job_id == job_id and self._current_proc is not None:
                await self._kill_current()
                await asyncio.to_thread(self._db_mark_cancelled, job_id, "ユーザによるキャンセル")
                return True
            # まだ実行されていない（QUEUED）→ フラグを立て、ワーカ取り出し時にスキップ。
            self._cancelled.add(job_id)
            await asyncio.to_thread(self._db_mark_cancelled, job_id, "ユーザによるキャンセル")
            return True

    def subscribe(self, job_id: int) -> asyncio.Queue[str | None]:
        """進捗購読（WebSocket 用）。行テキストを受け取り、None で終了。"""
        return self._hub.subscribe(job_id)

    def unsubscribe(self, job_id: int, q: asyncio.Queue[str | None]) -> None:
        """進捗購読を解除する。"""
        self._hub.unsubscribe(job_id, q)

    @property
    def current_job_id(self) -> int | None:
        """現在 RUNNING のジョブ id（無ければ None）。"""
        return self._current_job_id

    # ---- ワーカ ----

    async def _run_worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                if job_id in self._cancelled:
                    self._cancelled.discard(job_id)
                    continue  # QUEUED 中にキャンセル済み（DB は cancel() で更新済み）
                await self._run_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001  ワーカは落とさない
                await asyncio.to_thread(self._db_mark_failed, job_id, f"内部エラー: {exc!r}")
                self._hub.publish(job_id, f"[ERROR] {exc!r}")
                self._hub.close(job_id)
            finally:
                self._queue.task_done()

    async def _run_job(self, job_id: int) -> None:
        tup = await asyncio.to_thread(self._db_get_tuple, job_id)
        if tup is None:
            return
        color_no, _size, _chain, _tape = tup

        await asyncio.to_thread(self._db_mark_running, job_id)
        self._hub.publish(job_id, f"[STATUS] RUNNING color={color_no}")

        cmd = self._cfg.build_command(color_no)
        self._hub.publish(job_id, f"[CMD] (cwd={self._cfg.training_dir}) {' '.join(cmd)}")

        saw_completion = False
        async with self._lock:
            self._current_job_id = job_id
            self._current_proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self._cfg.training_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,  # 新プロセスグループ（spawn 子ごと kill 可能に）
            )
        proc = self._current_proc
        assert proc is not None and proc.stdout is not None

        try:
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if COMPLETION_MARKER in line:
                    saw_completion = True
                self._hub.publish(job_id, line)  # 素通し
            await proc.wait()
        finally:
            async with self._lock:
                self._current_job_id = None
                self._current_proc = None

        # キャンセル済みなら CANCELLED で確定（kill 経由で cancel() が DB 更新済み）。
        if job_id in self._cancelled:
            self._cancelled.discard(job_id)
            self._hub.publish(job_id, "[STATUS] CANCELLED")
            self._hub.close(job_id)
            return

        # 成功判定: 両 mode の ONNX 生成 ＋ 完了マーカー（終了コードは見ない）。
        mono_path = self._cfg.onnx_path(color_no, "monochro")
        color_path = self._cfg.onnx_path(color_no, "color")
        onnx_ok = os.path.isfile(mono_path) and os.path.isfile(color_path)

        if onnx_ok and saw_completion:
            await asyncio.to_thread(self._db_mark_completed, job_id, mono_path, color_path)
            self._hub.publish(job_id, "[STATUS] COMPLETED")
            self._hub.close(job_id)
            await self._fire_on_completed(job_id)
        else:
            reason = self._failure_reason(onnx_ok, saw_completion, mono_path, color_path)
            await asyncio.to_thread(self._db_mark_failed, job_id, reason)
            self._hub.publish(job_id, f"[STATUS] FAILED {reason}")
            self._hub.close(job_id)

    @staticmethod
    def _failure_reason(onnx_ok: bool, saw_completion: bool, mono: str, color: str) -> str:
        if not onnx_ok:
            return f"ONNX 未生成（monochro={os.path.isfile(mono)}, color={os.path.isfile(color)}）"
        if not saw_completion:
            return f"完了マーカー（{COMPLETION_MARKER}）未検出"
        return "不明な失敗"

    async def _fire_on_completed(self, job_id: int) -> None:
        if self._on_completed is None:
            return
        try:
            result = self._on_completed(job_id)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001  配信失敗はジョブ成功を覆さない
            self._hub.publish(job_id, f"[DEPLOY] 配信処理でエラー: {exc!r}")

    async def _kill_current(self) -> None:
        """実行中プロセスをプロセスグループごと停止（SIGTERM→猶予→SIGKILL）。"""
        proc = self._current_proc
        if proc is None or proc.returncode is not None:
            return
        try:
            pgid = os.getpgid(proc.pid)  # type: ignore[attr-defined]
            os.killpg(pgid, signal.SIGTERM)  # type: ignore[attr-defined]
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            try:
                os.killpg(  # type: ignore[attr-defined]
                    os.getpgid(proc.pid),  # type: ignore[attr-defined]
                    signal.SIGKILL,  # type: ignore[attr-defined]
                )
            except ProcessLookupError:
                pass

    # ---- DB ヘルパ（同期 Session を to_thread で呼ぶ） ----

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        db = self._session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _db_get_tuple(self, job_id: int) -> tuple[str, str, str, str] | None:
        with self._session_scope() as db:
            job = RetrainingRepository(db).get(job_id)
            if job is None:
                return None
            return (job.color_no, job.size, job.chain, job.tape)

    def _db_mark_running(self, job_id: int) -> None:
        with self._session_scope() as db:
            RetrainingRepository(db).mark_running(job_id)

    def _db_mark_completed(self, job_id: int, mono: str, color: str) -> None:
        with self._session_scope() as db:
            RetrainingRepository(db).mark_completed(job_id, mono, color)

    def _db_mark_failed(self, job_id: int, reason: str) -> None:
        with self._session_scope() as db:
            RetrainingRepository(db).mark_failed(job_id, reason)

    def _db_mark_cancelled(self, job_id: int, reason: str) -> None:
        with self._session_scope() as db:
            RetrainingRepository(db).mark_cancelled(job_id, reason)


# シングルトン保持（main.py の lifespan で初期化・参照）。
_service: TrainingService | None = None


def init_training_service(
    session_factory: Callable[[], Session],
    config: TrainingConfig,
    on_completed: Callable[[int], object] | None = None,
) -> TrainingService:
    """シングルトンを初期化して返す（lifespan で呼ぶ）。"""
    global _service
    _service = TrainingService(session_factory, config, on_completed=on_completed)
    return _service


def get_training_service() -> TrainingService:
    """初期化済みシングルトンを返す（未初期化なら RuntimeError）。"""
    if _service is None:
        raise RuntimeError("TrainingService が未初期化です（lifespan で init してください）")
    return _service
