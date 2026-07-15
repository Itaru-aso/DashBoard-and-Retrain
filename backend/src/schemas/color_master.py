"""色マスター API の入出力スキーマ（color C-R5）。

出力・一覧フィルタ・取り込み結果・色見本更新（status は自動管理・手動変更不可）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ColorStatus = Literal["未実施", "量産検証", "実生産"]


class ColorFilter(BaseModel):
    """一覧フィルタ（すべて任意）。"""

    status: ColorStatus | None = None
    color_no: str | None = None
    size: str | None = None
    chain: str | None = None
    tape: str | None = None


class ColorSampleUpdate(BaseModel):
    """色見本（RGB/Lab）の更新。status は含めない（自動管理）。"""

    rgb_r: int | None = Field(default=None, ge=0, le=255)
    rgb_g: int | None = Field(default=None, ge=0, le=255)
    rgb_b: int | None = Field(default=None, ge=0, le=255)
    lab_l: float | None = None
    lab_a: float | None = None
    lab_b: float | None = None


class ImportResult(BaseModel):
    """取り込み結果レポート。"""

    created: int
    updated: int
    skipped: int
    errors: list[str]


class ColorSummary(BaseModel):
    """状態別の件数サマリー（一覧の全件取得を避けるための軽量集計）。"""

    total: int
    by_status: dict[str, int]


class ColorOut(BaseModel):
    """色マスター出力。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    color_no: str
    size: str
    chain: str
    tape: str
    rgb_r: int | None
    rgb_g: int | None
    rgb_b: int | None
    lab_l: Decimal | None
    lab_a: Decimal | None
    lab_b: Decimal | None
    status: ColorStatus
    verification_at: datetime | None
    production_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ColorListResponse(BaseModel):
    """色一覧（ページング付き）。"""

    items: list[ColorOut]
    limit: int
    offset: int
