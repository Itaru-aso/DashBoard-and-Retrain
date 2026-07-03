"""再学習 API の入出力スキーマ（retraining M-R1, M-R7, M-R8）。

起票（フルタプル＋created_by）・一覧/詳細・キャンセル・現行配信・配信結果。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobCreateRequest(BaseModel):
    """再学習ジョブ起票（対象色フルタプル・作業者手動）。"""

    color_no: str
    size: str
    chain: str
    tape: str = ""
    created_by: str | None = None


class JobResponse(BaseModel):
    """再学習ジョブ（履歴・状態）出力。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    color_no: str
    size: str
    chain: str
    tape: str
    status: str
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    onnx_monochro_path: str | None
    onnx_color_path: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    """ジョブ履歴一覧（ページング付き）。"""

    items: list[JobResponse]
    limit: int
    offset: int


class CancelResponse(BaseModel):
    """キャンセル結果（終端ジョブは accepted=false で冪等）。"""

    job_id: int
    accepted: bool


class DeployedModelResponse(BaseModel):
    """色（フルタプル）ごとの現行配信モデル出力。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    color_no: str
    size: str
    chain: str
    tape: str
    job_id: int
    onnx_monochro_path: str | None
    onnx_color_path: str | None
    deploy_status: str
    deploy_detail: str | None
    deployed_at: datetime
    updated_at: datetime


class DeployResponse(BaseModel):
    """配信結果（集約・deployment_service.deploy_job の戻り）。"""

    job_id: int
    status: str
    detail: str
    edge_pc_count: int
