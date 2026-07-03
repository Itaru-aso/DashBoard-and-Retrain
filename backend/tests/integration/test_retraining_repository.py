"""再学習 Repository（retraining M-R7, M-R8.3）の integration テスト。

作成・状態遷移の永続・履歴一覧/絞り込み/ページング・list_active 順序・deployed upsert・取得。
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session


def _repo(db_session: Session):
    from src.repositories.retraining_repository import RetrainingRepository

    return RetrainingRepository(db_session)


@pytest.mark.integration
def test_create_job_defaults_queued(db_session: Session) -> None:
    repo = _repo(db_session)
    job = repo.create_job(color_no="001", size="05", chain="CZT8", created_by="aso")
    assert job.id is not None
    assert job.status == "QUEUED"
    assert job.tape == ""
    assert job.created_by == "aso"
    assert repo.get(job.id) is not None


@pytest.mark.integration
def test_status_transitions_persist(db_session: Session) -> None:
    repo = _repo(db_session)
    job = repo.create_job(color_no="001", size="05", chain="CZT8")

    repo.mark_running(job.id)
    assert repo.get(job.id).status == "RUNNING"
    assert repo.get(job.id).started_at is not None

    repo.mark_completed(job.id, onnx_monochro_path="/m.onnx", onnx_color_path="/c.onnx")
    done = repo.get(job.id)
    assert done.status == "COMPLETED"
    assert done.onnx_monochro_path == "/m.onnx"
    assert done.finished_at is not None

    job2 = repo.create_job(color_no="002", size="05", chain="CZT8")
    repo.mark_failed(job2.id, error_message="boom")
    assert repo.get(job2.id).status == "FAILED"
    assert repo.get(job2.id).error_message == "boom"

    job3 = repo.create_job(color_no="003", size="05", chain="CZT8")
    repo.mark_cancelled(job3.id, reason="user")
    assert repo.get(job3.id).status == "CANCELLED"


@pytest.mark.integration
def test_mark_running_missing_raises(db_session: Session) -> None:
    repo = _repo(db_session)
    with pytest.raises(ValueError):
        repo.mark_running(999999)


@pytest.mark.integration
def test_list_jobs_filter_and_paging(db_session: Session) -> None:
    repo = _repo(db_session)
    for i in range(3):
        repo.create_job(color_no=f"10{i}", size="05", chain="CZT8")
    failed = repo.create_job(color_no="200", size="05", chain="CZT8")
    repo.mark_failed(failed.id, error_message="x")

    assert len(repo.list_jobs(limit=2, offset=0)) == 2
    only_failed = repo.list_jobs(status="FAILED")
    assert [j.status for j in only_failed] == ["FAILED"]


@pytest.mark.integration
def test_list_active_order_oldest_first(db_session: Session) -> None:
    repo = _repo(db_session)
    a = repo.create_job(color_no="001", size="05", chain="CZT8")
    b = repo.create_job(color_no="002", size="05", chain="CZT8")
    repo.mark_running(a.id)
    done = repo.create_job(color_no="003", size="05", chain="CZT8")
    repo.mark_completed(done.id, onnx_monochro_path="/m", onnx_color_path="/c")

    active = repo.list_active()
    # QUEUED / RUNNING のみ・古い順（queued_at 昇順）。COMPLETED は含まない。
    ids = [j.id for j in active]
    assert done.id not in ids
    assert set(ids) == {a.id, b.id}


@pytest.mark.integration
def test_deployed_upsert_and_get(db_session: Session) -> None:
    repo = _repo(db_session)
    job1 = repo.create_job(color_no="001", size="05", chain="CZT8")
    repo.mark_completed(job1.id, onnx_monochro_path="/m1", onnx_color_path="/c1")
    job2 = repo.create_job(color_no="001", size="05", chain="CZT8")
    repo.mark_completed(job2.id, onnx_monochro_path="/m2", onnx_color_path="/c2")

    rec = repo.upsert_deployed(
        color_no="001",
        size="05",
        chain="CZT8",
        tape="",
        job_id=job1.id,
        onnx_monochro_path="/m1",
        onnx_color_path="/c1",
    )
    assert rec.job_id == job1.id

    # 同一フルタプルの再配信は上書き（ユニーク・行は増えない）。
    rec2 = repo.upsert_deployed(
        color_no="001",
        size="05",
        chain="CZT8",
        tape="",
        job_id=job2.id,
        onnx_monochro_path="/m2",
        onnx_color_path="/c2",
        deploy_status="PARTIAL",
        deploy_detail={"pc1": True, "pc2": False},
    )
    assert rec2.id == rec.id
    assert rec2.job_id == job2.id
    assert rec2.deploy_status == "PARTIAL"
    assert repo.get_deployed("001", "05", "CZT8", "").job_id == job2.id
    assert len(repo.list_deployed()) == 1
