"""再学習ジョブ・現行配信モデルのリポジトリ（ver2 DB・retraining M-R7, M-R8.3）。

責務:
- `retraining_job` の作成・状態遷移（DB を正として永続）・履歴取得・復旧用一覧。
- `deployed_model`（色フルタプル単位の現行配信モデル）の upsert・取得。
状態遷移の判断（FIFO・同時1本など）は `training_service` が持ち、本リポジトリは DB 操作に徹する。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.deployed_model import DeployedModel, DeployStatus
from src.models.retraining_job import JobStatus, RetrainingJob


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RetrainingRepository:
    """再学習ジョブ・現行配信モデルの永続化（ver2 エンジン）。"""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ---- retraining_job ----

    def create_job(
        self,
        color_no: str,
        size: str,
        chain: str,
        tape: str = "",
        created_by: str | None = None,
    ) -> RetrainingJob:
        """ジョブを QUEUED で作成する。"""
        job = RetrainingJob(
            color_no=color_no,
            size=size,
            chain=chain,
            tape=tape or "",
            status=JobStatus.QUEUED.value,
            queued_at=_now(),
            created_by=created_by,
        )
        self._db.add(job)
        self._db.flush()  # id 採番
        return job

    def get(self, job_id: int) -> RetrainingJob | None:
        """id で取得する。"""
        return self._db.get(RetrainingJob, job_id)

    def list_jobs(
        self, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> list[RetrainingJob]:
        """履歴一覧（新しい順）。任意で status 絞り込み。"""
        stmt = select(RetrainingJob)
        if status is not None:
            stmt = stmt.where(RetrainingJob.status == status)
        stmt = stmt.order_by(RetrainingJob.queued_at.desc()).limit(limit).offset(offset)
        return list(self._db.scalars(stmt).all())

    def list_active(self) -> list[RetrainingJob]:
        """未終了（QUEUED / RUNNING）を古い順に返す（起動時の復旧・FIFO 再構築用）。"""
        stmt = (
            select(RetrainingJob)
            .where(RetrainingJob.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]))
            .order_by(RetrainingJob.queued_at.asc())
        )
        return list(self._db.scalars(stmt).all())

    def mark_running(self, job_id: int) -> None:
        """RUNNING に遷移し started_at を記録する。"""
        job = self._require(job_id)
        job.status = JobStatus.RUNNING.value
        job.started_at = _now()
        job.updated_at = _now()
        self._db.flush()

    def mark_completed(self, job_id: int, onnx_monochro_path: str, onnx_color_path: str) -> None:
        """COMPLETED に遷移し成果物パスを記録する。"""
        job = self._require(job_id)
        job.status = JobStatus.COMPLETED.value
        job.finished_at = _now()
        job.onnx_monochro_path = onnx_monochro_path
        job.onnx_color_path = onnx_color_path
        job.error_message = None
        job.updated_at = _now()
        self._db.flush()

    def mark_failed(self, job_id: int, error_message: str) -> None:
        """FAILED に遷移しエラーを記録する。"""
        job = self._require(job_id)
        job.status = JobStatus.FAILED.value
        job.finished_at = _now()
        job.error_message = error_message[:4000] if error_message else None
        job.updated_at = _now()
        self._db.flush()

    def mark_cancelled(self, job_id: int, reason: str | None = None) -> None:
        """CANCELLED に遷移する（任意で理由を記録）。"""
        job = self._require(job_id)
        job.status = JobStatus.CANCELLED.value
        job.finished_at = _now()
        if reason:
            job.error_message = reason[:4000]
        job.updated_at = _now()
        self._db.flush()

    def _require(self, job_id: int) -> RetrainingJob:
        job = self._db.get(RetrainingJob, job_id)
        if job is None:
            raise ValueError(f"RetrainingJob not found: id={job_id}")
        return job

    # ---- deployed_model ----

    def get_deployed(
        self, color_no: str, size: str, chain: str, tape: str = ""
    ) -> DeployedModel | None:
        """色（フルタプル）の現行配信モデルを取得する。"""
        stmt = select(DeployedModel).where(
            DeployedModel.color_no == color_no,
            DeployedModel.size == size,
            DeployedModel.chain == chain,
            DeployedModel.tape == (tape or ""),
        )
        return self._db.scalars(stmt).one_or_none()

    def list_deployed(self) -> list[DeployedModel]:
        """現行配信モデルを配信日時の新しい順で返す。"""
        stmt = select(DeployedModel).order_by(DeployedModel.deployed_at.desc())
        return list(self._db.scalars(stmt).all())

    def upsert_deployed(
        self,
        color_no: str,
        size: str,
        chain: str,
        tape: str,
        job_id: int,
        onnx_monochro_path: str | None,
        onnx_color_path: str | None,
        deploy_status: str = DeployStatus.SUCCESS.value,
        deploy_detail: dict | None = None,
    ) -> DeployedModel:
        """色（フルタプル）の現行配信モデルを upsert する（再配信で上書き）。"""
        rec = self.get_deployed(color_no, size, chain, tape)
        detail_json = json.dumps(deploy_detail, ensure_ascii=False) if deploy_detail else None
        if rec is None:
            rec = DeployedModel(
                color_no=color_no,
                size=size,
                chain=chain,
                tape=tape or "",
                job_id=job_id,
                onnx_monochro_path=onnx_monochro_path,
                onnx_color_path=onnx_color_path,
                deploy_status=deploy_status,
                deploy_detail=detail_json,
                deployed_at=_now(),
            )
            self._db.add(rec)
        else:
            rec.job_id = job_id
            rec.onnx_monochro_path = onnx_monochro_path
            rec.onnx_color_path = onnx_color_path
            rec.deploy_status = deploy_status
            rec.deploy_detail = detail_json
            rec.deployed_at = _now()
            rec.updated_at = _now()
        self._db.flush()
        return rec
