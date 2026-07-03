"""再学習 Pydantic スキーマ（retraining M-R1）の unit テスト。

起票・一覧/詳細・キャンセル・現行配信・配信結果の検証（正常／異常）。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


@pytest.mark.unit
def test_job_create_valid_and_tape_default() -> None:
    from src.schemas.retraining import JobCreateRequest

    req = JobCreateRequest(color_no="001", size="05", chain="CZT8")
    assert req.color_no == "001"
    assert req.tape == ""  # 既定（空文字もキーの一部）
    assert req.created_by is None


@pytest.mark.unit
def test_job_create_requires_color_no() -> None:
    from src.schemas.retraining import JobCreateRequest

    with pytest.raises(ValidationError):
        JobCreateRequest(size="05", chain="CZT8")  # type: ignore[call-arg]


@pytest.mark.unit
def test_job_response_from_attributes() -> None:
    from src.schemas.retraining import JobResponse

    class _Row:
        id = 7
        color_no = "001"
        size = "05"
        chain = "CZT8"
        tape = ""
        status = "QUEUED"
        queued_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
        started_at = None
        finished_at = None
        error_message = None
        onnx_monochro_path = None
        onnx_color_path = None
        created_by = "aso"
        created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
        updated_at = datetime(2026, 7, 1, tzinfo=timezone.utc)

    out = JobResponse.model_validate(_Row())
    assert out.id == 7
    assert out.status == "QUEUED"


@pytest.mark.unit
def test_job_list_response() -> None:
    from src.schemas.retraining import JobListResponse

    resp = JobListResponse(items=[], limit=50, offset=0)
    assert resp.limit == 50
    assert resp.items == []


@pytest.mark.unit
def test_cancel_response() -> None:
    from src.schemas.retraining import CancelResponse

    resp = CancelResponse(job_id=3, accepted=False)
    assert resp.job_id == 3
    assert resp.accepted is False


@pytest.mark.unit
def test_deployed_model_response_from_attributes() -> None:
    from src.schemas.retraining import DeployedModelResponse

    class _Row:
        id = 1
        color_no = "001"
        size = "05"
        chain = "CZT8"
        tape = ""
        job_id = 7
        onnx_monochro_path = None
        onnx_color_path = None
        deploy_status = "SUCCESS"
        deploy_detail = None
        deployed_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
        updated_at = datetime(2026, 7, 1, tzinfo=timezone.utc)

    out = DeployedModelResponse.model_validate(_Row())
    assert out.job_id == 7
    assert out.deploy_status == "SUCCESS"


@pytest.mark.unit
def test_deploy_response() -> None:
    from src.schemas.retraining import DeployResponse

    resp = DeployResponse(job_id=7, status="PARTIAL", detail="{}", edge_pc_count=3)
    assert resp.status == "PARTIAL"
    assert resp.edge_pc_count == 3
