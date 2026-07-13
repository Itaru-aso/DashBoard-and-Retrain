"""検査結果ダッシュボード API（dashboard R1–R7）。

推移/集計/号機/重ね描きは ver2 `daily_metrics`＋閾値（`get_db`）、明細は app_db
（`get_inspection_db`・読み取り専用・キーセット）。すべて GET・Basic 認証ゲート。
app_db 到達不能時も致命的に落ちない（明細は 503 を返す）。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.api.security import require_auth
from src.database import get_db, get_inspection_db
from src.repositories.inspection_detail_repository import InspectionDetailRepository
from src.schemas.dashboard import (
    CursorOut,
    DashboardFilter,
    MachineOut,
    OverlayPointOut,
    RecordOut,
    RecordsOut,
    SummaryOut,
    TrendPointOut,
)
from src.services.dashboard_service import DashboardService

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_auth)],
)


def _validate_period(date_from: date, date_to: date) -> None:
    """期間の妥当性（終了<開始で 422）を DashboardFilter で検証する。"""
    try:
        DashboardFilter(date_from=date_from, date_to=date_to)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail="期間が不正です（終了日は開始日以降にしてください）"
        ) from exc


@router.get("/trends", response_model=list[TrendPointOut])
def get_trends(
    db: Annotated[Session, Depends(get_db)],
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    color_no: str | None = None,
    size: str | None = None,
    chain: str | None = None,
    tape: str | None = None,
    machine_ids: Annotated[list[str] | None, Query()] = None,
) -> list[TrendPointOut]:
    """日次のメトリクス系列を返す（号機指定なしは全号機合算）。"""
    _validate_period(date_from, date_to)
    points = DashboardService(db).get_trends(
        date_from, date_to, color_no, size, chain, tape, machine_ids
    )
    return [
        TrendPointOut(
            jst_date=p.jst_date,
            throughput=p.throughput,
            ng_rate=p.ng_rate,
            false_alarm_rate=p.false_alarm_rate,
            miss_rate=p.miss_rate,
        )
        for p in points
    ]


@router.get("/summary", response_model=SummaryOut | None)
def get_summary(
    db: Annotated[Session, Depends(get_db)],
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    color_no: str | None = None,
    size: str | None = None,
    chain: str | None = None,
    tape: str | None = None,
    machine_ids: Annotated[list[str] | None, Query()] = None,
) -> SummaryOut | None:
    """期間集計のメトリクスを返す（データなし＝null）。"""
    _validate_period(date_from, date_to)
    summary = DashboardService(db).get_summary(
        date_from, date_to, color_no, size, chain, tape, machine_ids
    )
    if summary is None:
        return None
    return SummaryOut(
        throughput=summary.throughput,
        ng_rate=summary.ng_rate,
        false_alarm_rate=summary.false_alarm_rate,
        miss_rate=summary.miss_rate,
    )


@router.get("/records", response_model=RecordsOut)
def get_records(
    inspection: Annotated[Session, Depends(get_inspection_db)],
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    color_no: str | None = None,
    size: str | None = None,
    chain: str | None = None,
    tape: str | None = None,
    machine_ids: Annotated[list[str] | None, Query()] = None,
    cursor_timestamp: datetime | None = None,
    cursor_image_id: uuid.UUID | None = None,
    limit: int = 50,
) -> RecordsOut:
    """明細をキーセットで返す（app_db 断は 503）。"""
    _validate_period(date_from, date_to)
    cursor = (
        (cursor_timestamp, cursor_image_id)
        if cursor_timestamp is not None and cursor_image_id is not None
        else None
    )
    # date 期間を [from 0:00, to+1日 0:00) の半開区間へ変換して当日ぶんまで含める。
    from_dt = datetime(date_from.year, date_from.month, date_from.day)
    to_dt = datetime(date_to.year, date_to.month, date_to.day) + timedelta(days=1)
    try:
        page = InspectionDetailRepository(inspection).read_details(
            from_dt,
            to_dt,
            color_no=color_no,
            size=size,
            chain=chain,
            tape=tape,
            unit_ids=machine_ids,
            cursor=cursor,
            limit=limit,
        )
    except OperationalError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="業者検査 DB に接続できません",
        ) from exc

    next_cursor = (
        CursorOut(inspect_timestamp=page.next_cursor[0], image_id=page.next_cursor[1])
        if page.next_cursor is not None
        else None
    )
    return RecordsOut(
        records=[
            RecordOut(
                image_id=r.image_id,
                inspect_timestamp=r.inspect_timestamp,
                unit=r.unit,
                camera_model=r.camera_model,
                judgment_result=r.judgment_result,
                color_no=r.color_no,
                size=r.size,
                chain=r.chain,
                tape=r.tape,
            )
            for r in page.rows
        ],
        next_cursor=next_cursor,
    )


@router.get("/threshold-overlay", response_model=list[OverlayPointOut])
def get_threshold_overlay(
    db: Annotated[Session, Depends(get_db)],
    metric: str,
    color_no: str,
    size: str,
    chain: str,
    tape: str,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> list[OverlayPointOut]:
    """日次の有効閾値系列を返す（色レベル・号機非依存）。"""
    _validate_period(date_from, date_to)
    points = DashboardService(db).get_threshold_overlay(
        metric, color_no, size, chain, tape, date_from, date_to
    )
    return [OverlayPointOut(jst_date=p.jst_date, value_pct=p.value_pct) for p in points]


@router.get("/machines", response_model=list[MachineOut])
def get_machines(db: Annotated[Session, Depends(get_db)]) -> list[MachineOut]:
    """号機一覧（フィルタ選択肢）を返す。"""
    return [MachineOut(unit=u) for u in DashboardService(db).get_machines()]
