"""retraining_job / deployed_model リポジトリの統合テスト（ver2 DB）。

配置先: backend/tests/integration/test_retraining_repository.py
"""
from __future__ import annotations

from models.deployed_model import DeployStatus
from models.retraining_job import JobStatus
from repositories.retraining_repository import RetrainingRepository


def test_create_job_is_queued(db_session):
    repo = RetrainingRepository(db_session)
    job = repo.create_job("501", "05", "CZT8", "GHI789841", created_by="op1")
    db_session.commit()
    assert job.id is not None
    assert job.status == JobStatus.QUEUED.value
    assert job.queued_at is not None
    assert job.tape == "GHI789841"
    assert job.created_by == "op1"


def test_tape_defaults_to_empty(db_session):
    repo = RetrainingRepository(db_session)
    job = repo.create_job("501", "05", "CZT8")
    db_session.commit()
    assert job.tape == ""


def test_status_transitions(db_session):
    repo = RetrainingRepository(db_session)
    job = repo.create_job("501", "05", "CZT8", "")
    db_session.commit()

    repo.mark_running(job.id)
    db_session.commit()
    assert job.status == JobStatus.RUNNING.value and job.started_at is not None

    repo.mark_completed(job.id, "/m/501/monochro/501_monochro_model.onnx",
                        "/m/501/color/501_color_model.onnx")
    db_session.commit()
    assert job.status == JobStatus.COMPLETED.value
    assert job.finished_at is not None
    assert job.onnx_color_path.endswith("501_color_model.onnx")
    assert job.is_terminal


def test_mark_failed_and_cancelled(db_session):
    repo = RetrainingRepository(db_session)
    j1 = repo.create_job("a", "1", "c"); j2 = repo.create_job("b", "1", "c")
    db_session.commit()
    repo.mark_failed(j1.id, "ONNX 未生成")
    repo.mark_cancelled(j2.id, "ユーザによるキャンセル")
    db_session.commit()
    assert j1.status == JobStatus.FAILED.value and j1.error_message == "ONNX 未生成"
    assert j2.status == JobStatus.CANCELLED.value


def test_list_jobs_order_filter_paging(db_session):
    repo = RetrainingRepository(db_session)
    ids = [repo.create_job(str(i), "1", "c").id for i in range(5)]
    db_session.commit()
    repo.mark_failed(ids[0], "x"); db_session.commit()

    newest_first = repo.list_jobs(limit=10, offset=0)
    assert [j.id for j in newest_first][0] == ids[-1]            # 新しい順

    only_failed = repo.list_jobs(status=JobStatus.FAILED.value)
    assert [j.id for j in only_failed] == [ids[0]]

    page = repo.list_jobs(limit=2, offset=2)
    assert len(page) == 2


def test_list_active_oldest_first(db_session):
    repo = RetrainingRepository(db_session)
    a = repo.create_job("a", "1", "c"); b = repo.create_job("b", "1", "c")
    c = repo.create_job("c", "1", "c")
    db_session.commit()
    repo.mark_running(a.id); repo.mark_completed(c.id, "m", "co"); db_session.commit()
    active = repo.list_active()           # QUEUED + RUNNING のみ・古い順
    assert [j.id for j in active] == [a.id, b.id]


def test_upsert_deployed_insert_then_overwrite(db_session):
    repo = RetrainingRepository(db_session)
    job = repo.create_job("501", "05", "CZT8", ""); db_session.commit()
    repo.mark_completed(job.id, "m1", "c1"); db_session.commit()

    d1 = repo.upsert_deployed("501", "05", "CZT8", "", job.id, "m1", "c1",
                              deploy_status=DeployStatus.SUCCESS.value,
                              deploy_detail={"pc1": {"ok": True, "errors": []}})
    db_session.commit()
    first_at = d1.deployed_at

    job2 = repo.create_job("501", "05", "CZT8", ""); db_session.commit()
    repo.mark_completed(job2.id, "m2", "c2"); db_session.commit()
    d2 = repo.upsert_deployed("501", "05", "CZT8", "", job2.id, "m2", "c2",
                              deploy_status=DeployStatus.PARTIAL.value)
    db_session.commit()

    # 同一フルタプルは1件・上書き
    assert d2.id == d1.id
    assert d2.job_id == job2.id
    assert d2.onnx_monochro_path == "m2"
    assert d2.deploy_status == DeployStatus.PARTIAL.value
    assert len(repo.list_deployed()) == 1
    assert d2.deployed_at >= first_at


def test_get_deployed_by_tuple(db_session):
    repo = RetrainingRepository(db_session)
    job = repo.create_job("501", "05", "CZT8", "T"); db_session.commit()
    repo.mark_completed(job.id, "m", "c"); db_session.commit()
    repo.upsert_deployed("501", "05", "CZT8", "T", job.id, "m", "c"); db_session.commit()
    assert repo.get_deployed("501", "05", "CZT8", "T") is not None
    assert repo.get_deployed("501", "05", "CZT8", "") is None    # tape 違いは別物
