"""再学習ワークフローのテスト用フィクスチャとモック方針。

配置先: backend/tests/conftest.py（既存 conftest がある場合は本内容を統合する）

モック方針（要点）:
- **DB**: ver2 のモデルは sqlite(in-memory) に `Base.metadata.create_all` して使う（高速・隔離）。
  本番は PostgreSQL だが、本機能のモデルは sqlite で十分検証できる（FK は PRAGMA で有効化）。
  プロジェクトの既存 conftest が postgres トランザクション ROLLBACK 方式なら、そちらの `db_session` を使ってよい。
- **subprocess（学習）**: `asyncio.create_subprocess_exec` を `FakeProcess` に差し替える。
  標準出力行・完了マーカー・ONNX 生成（成功時はファイルを実際に作る）・終了を制御する。実 GPU/学習は一切起動しない。
- **プロセス kill**: `os.getpgid` / `os.killpg` をスタブ化（実シグナルを送らない）。
- **FTP（配信）**: `DeploymentService(ftp_sender=...)` に記録用フェイク関数を注入。実 FTP 接続はしない。
- **エッジPC**: `edge_pc_repo_factory` にフェイク repo（`find_enabled()`）を注入。
- **API**: `app.dependency_overrides` で `get_db`/`verify_basic_auth`/`get_training_service`/
  `get_color_master_repo`/`get_deployment_service` を差し替える。
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# ver2 用 Base（models が参照しているものと同一を import すること）
from database import Base
# モデルを import してメタデータに登録
from models.retraining_job import RetrainingJob  # noqa: F401
from models.deployed_model import DeployedModel  # noqa: F401


@pytest.fixture()
def engine():
    eng = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_con, _):
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, future=True)


@pytest.fixture()
def db_session(session_factory) -> Session:
    db = session_factory()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


# ---- subprocess フェイク ----

class FakeStdout:
    """bytes 行を非同期に yield する stdout 代役。"""

    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        if not self._lines:
            raise StopAsyncIteration
        await asyncio.sleep(0)
        return self._lines.pop(0)


class FakeProcess:
    """asyncio subprocess の代役。stdout・wait・pid を制御する。

    on_wait: wait() の中で呼ぶコールバック（成功時に ONNX を作る等）。
    gate: asyncio.Event。指定すると wait() がそれまでブロックする（RUNNING 維持→キャンセル試験用）。
    """

    def __init__(self, lines: list[str], returncode: int = 0,
                 on_wait=None, pid: int = 4242, gate: "asyncio.Event | None" = None):
        self.stdout = FakeStdout([(l + "\n").encode() for l in lines])
        self._rc = returncode
        self.returncode = None
        self._on_wait = on_wait
        self.pid = pid
        self._gate = gate

    async def wait(self) -> int:
        if self._gate is not None:
            await self._gate.wait()
        if self._on_wait is not None:
            self._on_wait()
        self.returncode = self._rc
        return self._rc


def install_fake_subprocess(monkeypatch, factory):
    """`asyncio.create_subprocess_exec` を factory(cmd, **kw)->FakeProcess に差し替える。"""
    async def _fake_exec(*cmd, **kwargs):
        return factory(list(cmd), kwargs)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)


def stub_process_group(monkeypatch):
    """os.getpgid / os.killpg を無害化（実シグナルを送らない）。"""
    import os
    monkeypatch.setattr(os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: None)


# ---- エッジPC / FTP フェイク ----

class FakeEdgePc:
    def __init__(self, name, host="10.0.0.1", username="u", password="p", model_port=21):
        self.name = name
        self.host = host
        self.username = username
        self.password = password
        self.model_port = model_port


class FakeEdgePcRepo:
    def __init__(self, pcs):
        self._pcs = pcs

    def find_enabled(self):
        return list(self._pcs)
