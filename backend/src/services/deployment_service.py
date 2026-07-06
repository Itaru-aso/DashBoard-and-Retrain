"""ONNX モデルの配信と現行配信モデル記録（ver2・retraining M-R8）。

学習と分離（`training_service` から COMPLETED 時に呼ぶ＝v1 自動／将来は手動 API から）。
- COMPLETED ジョブの ONNX（monochro/color）を、有効なエッジPC（`エッジPC管理`）へ **FTP 配信**する。
  FTP は学習側に依存せず **ver2 自前の ftplib** 送信（境界を分離）。配信先ポートは `model_port`。
- 検査PC 互換のため、リモート名は **`{color_no}_{mode}_model.onnx`**（色番ベース）を FTP ルート直下に置く。
- `deployed_model`（**フルタプル単位**＝案A）に upsert。全台成功=SUCCESS／一部失敗=PARTIAL／全失敗=FAILED。
  FTP 失敗でもジョブ成功は覆さない（再配信可能な記録として残す）。

注: ftplib はブロッキングのため、非同期文脈からは `asyncio.to_thread` 経由で呼ぶ（make_auto_deploy_hook）。
"""

from __future__ import annotations

import ftplib
import os
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Protocol

from sqlalchemy.orm import Session

from src.models.deployed_model import DeployStatus
from src.models.retraining_job import JobStatus
from src.repositories.retraining_repository import RetrainingRepository


class _EnabledEdgePc(Protocol):
    # EdgePc モデルと構造的に一致させる（配信先解決の参照点）。
    name: str
    host: str
    username: str | None
    password: str | None
    model_port: int | None


class _EdgePcRepo(Protocol):
    def find_enabled(self) -> Sequence[_EnabledEdgePc]: ...


@dataclass
class DeploymentConfig:
    """配信設定。"""

    remote_dir: str = "."  # FTP ルート直下（学習側 upload_onnx_model と整合）
    ftp_timeout: int = 30


def _default_ftp_sender(
    host: str,
    port: int | None,
    username: str | None,
    password: str | None,
    local_path: str,
    remote_dir: str,
    remote_name: str,
    timeout: int,
) -> None:
    """ftplib による単一ファイル送信（ver2 自前）。失敗時は例外を送出する。

    エッジPC の port/username/password は任意（None 可）。edge_pc_service._probe と同じく
    port 未設定は 21、username/password 未設定は空文字にフォールバックする。
    """
    with ftplib.FTP(timeout=timeout) as ftp:
        ftp.connect(host, port or 21)
        ftp.login(username or "", password or "")
        if remote_dir and remote_dir not in (".", "./"):
            ftp.cwd(remote_dir)
        with open(local_path, "rb") as f:
            ftp.storbinary(f"STOR {remote_name}", f)


class DeploymentService:
    """ONNX 配信 ＋ 現行配信モデル記録。"""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        edge_pc_repo_factory: Callable[[Session], _EdgePcRepo],
        config: DeploymentConfig | None = None,
        ftp_sender: Callable[..., None] = _default_ftp_sender,
    ) -> None:
        self._session_factory = session_factory
        self._edge_pc_repo_factory = edge_pc_repo_factory
        self._cfg = config or DeploymentConfig()
        self._send = ftp_sender

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

    @staticmethod
    def _remote_name(color_no: str, mode: str) -> str:
        # 検査PC 取り込み互換: 色番ベースのファイル名（フルタプルは ver2 の記録側で保持）。
        return f"{color_no}_{mode}_model.onnx"

    def deploy_job(self, job_id: int) -> dict:
        """ジョブの ONNX を有効エッジPC全台へ配信し、現行配信モデルを upsert する（同期）。

        Returns:
            配信結果サマリ（job_id・status・per-host 詳細・edge_pc_count）。
        """
        with self._session_scope() as db:
            repo = RetrainingRepository(db)
            job = repo.get(job_id)
            if job is None:
                raise ValueError(f"RetrainingJob not found: id={job_id}")
            if job.status != JobStatus.COMPLETED.value:
                raise ValueError(f"配信対象は COMPLETED のみ: id={job_id} status={job.status}")

            # 配信する成果物（存在するものだけ）。
            artifacts: list[tuple[str, str]] = []  # (mode, local_path)
            if job.onnx_monochro_path and os.path.isfile(job.onnx_monochro_path):
                artifacts.append(("monochro", job.onnx_monochro_path))
            if job.onnx_color_path and os.path.isfile(job.onnx_color_path):
                artifacts.append(("color", job.onnx_color_path))
            if not artifacts:
                raise FileNotFoundError(f"配信対象 ONNX が見つかりません: id={job_id}")

            edge_pcs = self._edge_pc_repo_factory(db).find_enabled()

            detail: dict[str, dict] = {}
            host_results: list[bool] = []
            for pc in edge_pcs:
                ok = True
                errors: list[str] = []
                for mode, local_path in artifacts:
                    remote_name = self._remote_name(job.color_no, mode)
                    try:
                        self._send(
                            host=pc.host,
                            port=pc.model_port,
                            username=pc.username,
                            password=pc.password,
                            local_path=local_path,
                            remote_dir=self._cfg.remote_dir,
                            remote_name=remote_name,
                            timeout=self._cfg.ftp_timeout,
                        )
                    except Exception as exc:  # noqa: BLE001  1台/1ファイルの失敗は記録し継続
                        ok = False
                        errors.append(f"{mode}: {exc!r}")
                detail[pc.name] = {"ok": ok, "errors": errors}
                host_results.append(ok)

            status = self._aggregate_status(host_results)

            repo.upsert_deployed(
                color_no=job.color_no,
                size=job.size,
                chain=job.chain,
                tape=job.tape,
                job_id=job.id,
                onnx_monochro_path=job.onnx_monochro_path,
                onnx_color_path=job.onnx_color_path,
                deploy_status=status,
                deploy_detail=detail,
            )
            return {
                "job_id": job_id,
                "status": status,
                "detail": detail,
                "edge_pc_count": len(edge_pcs),
            }

    @staticmethod
    def _aggregate_status(host_results: list[bool]) -> str:
        if not host_results:
            # 有効エッジPC が無い＝配信先なし。記録上は FAILED（再配信可）として残す。
            return DeployStatus.FAILED.value
        if all(host_results):
            return DeployStatus.SUCCESS.value
        if any(host_results):
            return DeployStatus.PARTIAL.value
        return DeployStatus.FAILED.value


# シングルトン保持（main.py の lifespan で初期化・手動配信 API で参照）。
_service: DeploymentService | None = None


def init_deployment_service(
    session_factory: Callable[[], Session],
    edge_pc_repo_factory: Callable[[Session], _EdgePcRepo],
    config: DeploymentConfig | None = None,
    ftp_sender: Callable[..., None] = _default_ftp_sender,
) -> DeploymentService:
    """シングルトンを初期化して返す（lifespan で呼ぶ）。"""
    global _service
    _service = DeploymentService(session_factory, edge_pc_repo_factory, config, ftp_sender)
    return _service


def get_deployment_service() -> DeploymentService:
    """初期化済みシングルトンを返す（未初期化なら RuntimeError）。"""
    if _service is None:
        raise RuntimeError("DeploymentService が未初期化です（lifespan で init してください）")
    return _service


def make_auto_deploy_hook(
    deployment_service: DeploymentService,
) -> Callable[[int], object]:
    """`training_service` の on_completed に渡す自動配信フック（v1）。

    非同期文脈（ワーカ）から呼ばれるため、ブロッキングな FTP 配信を `asyncio.to_thread` に逃がす。
    """
    import asyncio

    def _hook(job_id: int) -> object:
        return asyncio.to_thread(deployment_service.deploy_job, job_id)

    return _hook
