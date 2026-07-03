"""ORM モデル `RetrainingJob` / `DeployedModel`（retraining task2）の integration テスト。

round-trip・status CHECK・FK・`is_terminal` を検証する。
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.mark.integration
def test_retraining_job_round_trip_and_defaults(db_session: Session) -> None:
    from src.models.retraining_job import JobStatus, RetrainingJob

    job = RetrainingJob(color_no="001", size="05", chain="CZT8", tape="")
    db_session.add(job)
    db_session.flush()
    db_session.refresh(job)

    fetched = db_session.get(RetrainingJob, job.id)
    assert fetched is not None
    assert fetched.color_no == "001"
    assert fetched.status == JobStatus.QUEUED.value  # 既定
    assert fetched.queued_at is not None
    assert fetched.started_at is None
    assert fetched.created_at is not None


@pytest.mark.integration
def test_retraining_job_is_terminal() -> None:
    from src.models.retraining_job import RetrainingJob

    running = RetrainingJob(color_no="001", size="05", chain="CZT8", tape="", status="RUNNING")
    completed = RetrainingJob(color_no="001", size="05", chain="CZT8", tape="", status="COMPLETED")
    assert running.is_terminal is False
    assert completed.is_terminal is True


@pytest.mark.integration
def test_retraining_job_status_check_rejected(db_session: Session) -> None:
    from src.models.retraining_job import RetrainingJob

    db_session.add(
        RetrainingJob(color_no="001", size="05", chain="CZT8", tape="", status="INVALID")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.integration
def test_deployed_model_round_trip_and_fk(db_session: Session) -> None:
    from src.models.deployed_model import DeployedModel, DeployStatus
    from src.models.retraining_job import RetrainingJob

    job = RetrainingJob(color_no="001", size="05", chain="CZT8", tape="", status="COMPLETED")
    db_session.add(job)
    db_session.flush()

    deployed = DeployedModel(color_no="001", size="05", chain="CZT8", tape="", job_id=job.id)
    db_session.add(deployed)
    db_session.flush()
    db_session.refresh(deployed)

    fetched = db_session.get(DeployedModel, deployed.id)
    assert fetched is not None
    assert fetched.job_id == job.id
    assert fetched.deploy_status == DeployStatus.SUCCESS.value  # 既定


@pytest.mark.integration
def test_deployed_model_fk_rejected(db_session: Session) -> None:
    from src.models.deployed_model import DeployedModel

    db_session.add(DeployedModel(color_no="001", size="05", chain="CZT8", tape="", job_id=999999))
    with pytest.raises(IntegrityError):
        db_session.flush()
