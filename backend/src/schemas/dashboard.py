"""ダッシュボード API の入出力スキーマ（dashboard R1, R6）。

フィルタは期間必須・色任意・号機任意/複数。期間未指定・終了<開始 → 422。
出力は系列・集計・明細・重ね描き・号機一覧。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, model_validator


class DashboardFilter(BaseModel):
    """推移・集計・明細の共通フィルタ。"""

    date_from: date
    date_to: date
    color_no: str | None = None
    size: str | None = None
    chain: str | None = None
    tape: str | None = None
    machine_ids: list[str] | None = None

    @model_validator(mode="after")
    def _validate_period(self) -> "DashboardFilter":
        if self.date_to < self.date_from:
            raise ValueError("終了日は開始日以降にしてください")
        return self


class TrendPointOut(BaseModel):
    """日次のメトリクス系列点。"""

    jst_date: date
    throughput: int
    ng_rate: float
    false_alarm_rate: float | None
    miss_rate: float | None


class SummaryOut(BaseModel):
    """期間集計のメトリクス。"""

    throughput: int
    ng_rate: float
    false_alarm_rate: float | None
    miss_rate: float | None


class RecordOut(BaseModel):
    """明細1件。"""

    image_id: uuid.UUID
    inspect_timestamp: datetime
    unit: str | None
    camera_model: str | None
    judgment_result: int | None
    color_no: str | None
    size: str | None
    chain: str | None
    tape: str | None


class CursorOut(BaseModel):
    """明細キーセットのカーソル。"""

    inspect_timestamp: datetime
    image_id: uuid.UUID


class RecordsOut(BaseModel):
    """明細ページ（次カーソル付き）。"""

    records: list[RecordOut]
    next_cursor: CursorOut | None


class OverlayPointOut(BaseModel):
    """日次の有効閾値系列点。"""

    jst_date: date
    value_pct: float


class MachineOut(BaseModel):
    """号機。"""

    unit: str
