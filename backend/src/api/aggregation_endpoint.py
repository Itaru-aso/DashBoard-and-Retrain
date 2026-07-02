"""集計トリガー API（A-R2/A-R4）。

`POST /api/aggregation/run` … `date`（単日）または `from,to`（期間バックフィル）で
手動集計を起動する（テスト・運用補助）。Basic 認証を適用する。

2エンジン（`get_inspection_db` 読み取り／`get_db` 書き込み）を DI で受け取り、
`AggregationService` に渡す（越境結合なし）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.security import require_auth
from src.database import get_db, get_inspection_db
from src.repositories.daily_metrics_repository import DailyMetricsRepository
from src.schemas.aggregation import AggregationRunRequest, AggregationRunResponse
from src.services.aggregation_service import AggregationService

router = APIRouter(
    prefix="/api/aggregation",
    tags=["aggregation"],
    dependencies=[Depends(require_auth)],
)


@router.post("/run", response_model=AggregationRunResponse)
def run_aggregation(
    payload: AggregationRunRequest,
    db: Annotated[Session, Depends(get_db)],
    inspection: Annotated[Session, Depends(get_inspection_db)],
) -> AggregationRunResponse:
    """単日（date）または期間（from,to）で集計を起動する。"""
    service = AggregationService(inspection, DailyMetricsRepository(db))

    if payload.day is not None:
        service.aggregate_day(payload.day)
        return AggregationRunResponse(
            status="ok", mode="day", date_from=payload.day, date_to=payload.day
        )

    # model_validator により、ここでは from/to の両方が揃っている。
    assert payload.date_from is not None and payload.date_to is not None
    service.backfill(payload.date_from, payload.date_to)
    return AggregationRunResponse(
        status="ok", mode="range", date_from=payload.date_from, date_to=payload.date_to
    )
