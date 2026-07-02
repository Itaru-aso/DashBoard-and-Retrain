"""閾値管理 API の入出力スキーマ（R1.3–R1.5, R6）。

metric enum・値域 0–100・期間逆転・スコープ整合（per_color は色4項目必須・
global は色項目なし）を Pydantic で検証する（422）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Metric = Literal["ng_rate", "false_alarm_rate", "miss_rate"]
Scope = Literal["global", "per_color"]

_COLOR_FIELDS = ("color_no", "size", "chain", "tape")


class ThresholdCreate(BaseModel):
    """閾値の新規作成入力。"""

    metric: Metric
    scope: Scope
    color_no: str | None = None
    size: str | None = None
    chain: str | None = None
    tape: str | None = None
    value_pct: float = Field(ge=0, le=100)
    valid_from: datetime
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def _validate(self) -> "ThresholdCreate":
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to は valid_from より後にしてください")

        color_values = [getattr(self, name) for name in _COLOR_FIELDS]
        if self.scope == "per_color":
            if any(v is None for v in color_values):
                raise ValueError("per_color は color_no/size/chain/tape をすべて指定してください")
        else:  # global
            if any(v is not None for v in color_values):
                raise ValueError("global では色項目（color_no/size/chain/tape）を指定できません")
        return self


class ThresholdUpdate(BaseModel):
    """閾値の更新入力（PATCH）。指定された項目のみ更新する。"""

    value_pct: float | None = Field(default=None, ge=0, le=100)
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def _validate(self) -> "ThresholdUpdate":
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to <= self.valid_from
        ):
            raise ValueError("valid_to は valid_from より後にしてください")
        return self


class ThresholdOut(BaseModel):
    """閾値の出力。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    metric: Metric
    scope: Scope
    color_no: str | None
    size: str | None
    chain: str | None
    tape: str | None
    value_pct: float
    valid_from: datetime
    valid_to: datetime | None
    created_at: datetime
    updated_at: datetime
