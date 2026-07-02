"""集計トリガー API の入出力スキーマ。"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AggregationRunRequest(BaseModel):
    """集計トリガーのリクエスト。

    `date`（単日）か `from`/`to`（期間バックフィル）のいずれか一方を指定する。
    """

    model_config = ConfigDict(populate_by_name=True)

    # フィールド名は型 `date` をシャドウしないよう `day`（JSON キーは alias "date"）。
    day: date | None = Field(default=None, alias="date")
    date_from: date | None = Field(default=None, alias="from")
    date_to: date | None = Field(default=None, alias="to")

    @model_validator(mode="after")
    def _validate_mode(self) -> "AggregationRunRequest":
        has_day = self.day is not None
        has_from = self.date_from is not None
        has_to = self.date_to is not None

        if has_day and (has_from or has_to):
            raise ValueError("date と from/to は同時に指定できません")
        if not has_day and not (has_from and has_to):
            raise ValueError("date、または from と to の両方を指定してください")
        if has_from and has_to and self.date_from is not None and self.date_to is not None:
            if self.date_from > self.date_to:
                raise ValueError("from は to 以前にしてください")
        return self


class AggregationRunResponse(BaseModel):
    """集計トリガーのレスポンス。"""

    status: str
    mode: str
    date_from: date = Field(serialization_alias="from")
    date_to: date = Field(serialization_alias="to")
