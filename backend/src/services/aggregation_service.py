"""集計 Service（A-R2/A-R3/A-R4）。

app_db（業者検査 DB・読み取り専用）の当日パーティションを集計し、ver2 の
`daily_metrics` へ upsert する。2エンジン（`get_inspection_db` 読み取り／`get_db` 書き込み）で、
**越境結合はしない**（app_db 内の結合のみ・ver2 への書き込みは別セッション）。

- `aggregate_day(jst_date)`: app_db を集計 → `upsert_day` で ver2 へ（冪等）。
- `aggregate_window(window_days)`: 直近 n 日を再集計（後追いアノテーション反映）。
- `backfill(from, to)`: 期間を日ごとに集計（初期構築・復旧）。
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from src.config import settings
from src.repositories.daily_metrics_repository import (
    DailyMetricRow,
    DailyMetricsRepository,
)

# app_db 集計クエリ（1日パーティション）。正解は image_id 単位に MAX(on_class) で集約
# （'1'が1つでもNG／全'0'でOK／無ければ NULL・use_flg では絞らない）。
# 分子=全カメラ／分母=monochro。monochro はカメラ機種コードで判定
# （開発用ダミー値 camera1_image・実機コード CA-HL04MX）。フルタプル・号機は NULL を空文字へ寄せる。
_MONOCHRO_CAMERA_MODELS = ("camera1_image", "CA-HL04MX")

_AGG_QUERY = text("""
WITH ann AS (
  SELECT ai.image_id, MAX(dci.on_class) AS correct
  FROM annotation.annotation_item ai
  JOIN admin.dataset_category_item dci
    ON dci.dataset_id = ai.dataset_id AND dci.item_id = ai.item_id
  WHERE ai.image_id IN (
    SELECT image_id FROM annotation.image_base
    WHERE inspect_timestamp >= :d AND inspect_timestamp < :d1
  )
  GROUP BY ai.image_id
)
SELECT
  COALESCE(ib.extra_info->>'colorNo', '') AS color_no,
  COALESCE(ib.extra_info->>'size', '')    AS size,
  COALESCE(ib.extra_info->>'chain', '')   AS chain,
  COALESCE(ib.extra_info->>'tape', '')    AS tape,
  COALESCE(ib.unit, '')                   AS unit,
  COUNT(*) FILTER (WHERE ib.camera_model IN :monochro_models)        AS monochro_count,
  COUNT(*) FILTER (WHERE ib.judgment_result = 1)                     AS ng_count,
  COUNT(*) FILTER (WHERE ib.judgment_result = 1 AND a.correct = '0') AS fp_num,
  COUNT(*) FILTER (WHERE ib.judgment_result = 0 AND a.correct = '1') AS miss_num,
  COUNT(*) FILTER (WHERE a.correct IS NOT NULL)                      AS annotated_count
FROM annotation.image_base ib
LEFT JOIN ann a ON a.image_id = ib.image_id
WHERE ib.inspect_timestamp >= :d AND ib.inspect_timestamp < :d1
GROUP BY 1, 2, 3, 4, 5
""").bindparams(bindparam("monochro_models", expanding=True))


class AggregationService:
    """app_db を集計して ver2 `daily_metrics` を更新する Service。"""

    def __init__(self, inspection_session: Session, repository: DailyMetricsRepository) -> None:
        self._inspection = inspection_session
        self._repository = repository

    def aggregate_day(self, jst_date: date) -> None:
        """対象 JST 日の app_db を集計し、ver2 へ upsert する（冪等）。"""
        next_day = jst_date + timedelta(days=1)
        params = {"d": jst_date, "d1": next_day, "monochro_models": _MONOCHRO_CAMERA_MODELS}
        result = self._inspection.execute(_AGG_QUERY, params).mappings()
        rows = [
            DailyMetricRow(
                color_no=m["color_no"],
                size=m["size"],
                chain=m["chain"],
                tape=m["tape"],
                unit=m["unit"],
                monochro_count=m["monochro_count"],
                ng_count=m["ng_count"],
                fp_num=m["fp_num"],
                miss_num=m["miss_num"],
                annotated_count=m["annotated_count"],
            )
            for m in result
        ]
        self._repository.upsert_day(jst_date, rows)

    def aggregate_window(
        self, window_days: int | None = None, *, end_date: date | None = None
    ) -> None:
        """直近 n 日（既定 `AGG_WINDOW_DAYS`）を再集計する（後追いアノテーション反映）。"""
        days = window_days if window_days is not None else settings.AGG_WINDOW_DAYS
        end = end_date if end_date is not None else date.today()
        for offset in range(days):
            self.aggregate_day(end - timedelta(days=offset))

    def backfill(self, date_from: date, date_to: date) -> None:
        """期間 [date_from, date_to] を日ごとに集計する（初期構築・復旧）。"""
        current = date_from
        while current <= date_to:
            self.aggregate_day(current)
            current += timedelta(days=1)
