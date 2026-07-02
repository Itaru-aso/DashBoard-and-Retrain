"""集計 Service `src.services.aggregation_service`（A-R2/A-R3/A-R4）の integration テスト。

2-DB 代役（app_db 代役の inspection_session／ver2 の db_session）で検証する。
- aggregate_day の件数正しさ: monochro 分母・全カメラ分子・正解集約 MAX(on_class)・
  use_flg 無視・アノテーションなしは annotated から除外。
- 冪等再集計で後追いアノテーションが反映される（delete→insert・重複なし）。
- backfill（複数日）。
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

D1 = date(2026, 7, 1)
D2 = date(2026, 7, 2)

# dataset_category_item: item 10 -> OK('0') / item 20 -> NG('1')
_ITEM_OK = 10
_ITEM_NG = 20


def _seed_categories(session: Session) -> None:
    session.execute(
        text(
            "INSERT INTO admin.dataset_category_item (dataset_id, item_id, on_class) "
            "VALUES (1, :ok, '0'), (1, :ng, '1')"
        ),
        {"ok": _ITEM_OK, "ng": _ITEM_NG},
    )


def _insert_image(
    session: Session,
    image_id: int,
    day: date,
    camera: str,
    judgment: int,
    *,
    unit: str = "1",
    color: str = "501",
    size: str = "05",
    chain: str = "CZT8",
    tape: str = "",
) -> None:
    session.execute(
        text(
            "INSERT INTO annotation.image_base "
            "(image_id, inspect_timestamp, unit, camera_model, judgment_result, extra_info) "
            "VALUES (:id, :ts, :unit, :cam, :jr, CAST(:extra AS jsonb))"
        ),
        {
            "id": image_id,
            "ts": datetime(day.year, day.month, day.day, 10, 0, 0),
            "unit": unit,
            "cam": camera,
            "jr": judgment,
            "extra": json.dumps({"colorNo": color, "size": size, "chain": chain, "tape": tape}),
        },
    )


def _annotate(session: Session, image_id: int, item_id: int, use_flg: bool = True) -> None:
    session.execute(
        text(
            "INSERT INTO annotation.annotation_item (image_id, dataset_id, item_id, use_flg) "
            "VALUES (:img, 1, :it, :uf)"
        ),
        {"img": image_id, "it": item_id, "uf": use_flg},
    )


@pytest.mark.integration
def test_aggregate_day_counts_are_correct(inspection_session: Session, db_session: Session) -> None:
    """monochro 分母・全カメラ分子・正解集約・use_flg 無視・アノテーションなし除外。"""
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.services.aggregation_service import AggregationService

    _seed_categories(inspection_session)
    # img1: monochro NG, 正解 {OK,NG}->NG（MAX 集約） => true positive
    _insert_image(inspection_session, 1, D1, "camera1_image", 1)
    _annotate(inspection_session, 1, _ITEM_OK)
    _annotate(inspection_session, 1, _ITEM_NG)
    # img2: monochro NG, 正解 OK => 虚報(fp)
    _insert_image(inspection_session, 2, D1, "camera1_image", 1)
    _annotate(inspection_session, 2, _ITEM_OK)
    # img3: monochro OK, 正解 NG => 見逃し(miss)
    _insert_image(inspection_session, 3, D1, "camera1_image", 0)
    _annotate(inspection_session, 3, _ITEM_NG)
    # img4: color(非monochro) NG, 正解 OK => 全カメラ分子(ng, fp)に寄与・monochro には非算入
    _insert_image(inspection_session, 4, D1, "camera2_image", 1)
    _annotate(inspection_session, 4, _ITEM_OK)
    # img5: monochro OK, アノテーションなし => annotated から除外
    _insert_image(inspection_session, 5, D1, "camera1_image", 0)
    # img6: monochro OK, 正解 OK だが use_flg=false => use_flg 無視で annotated に算入
    _insert_image(inspection_session, 6, D1, "camera1_image", 0)
    _annotate(inspection_session, 6, _ITEM_OK, use_flg=False)
    inspection_session.flush()

    repo = DailyMetricsRepository(db_session)
    service = AggregationService(inspection_session, repo)
    service.aggregate_day(D1)

    rows = repo.read(D1, D1)
    assert len(rows) == 1
    r = rows[0]
    assert (r.color_no, r.size, r.chain, r.tape, r.unit) == ("501", "05", "CZT8", "", "1")
    assert r.monochro_count == 5  # img1,2,3,5,6（img4 は color）
    assert r.ng_count == 3  # img1,2,4（全カメラ）
    assert r.fp_num == 2  # img2,img4（judgment=1 かつ 正解OK）
    assert r.miss_num == 1  # img3（judgment=0 かつ 正解NG）
    assert r.annotated_count == 5  # img1,2,3,4,6（img5 は正解なし）


@pytest.mark.integration
def test_reaggregation_reflects_late_annotation(
    inspection_session: Session, db_session: Session
) -> None:
    """後追いアノテーションを再集計で反映（冪等・重複なし）。"""
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.services.aggregation_service import AggregationService

    _seed_categories(inspection_session)
    _insert_image(inspection_session, 1, D1, "camera1_image", 0)
    _annotate(inspection_session, 1, _ITEM_OK)
    _insert_image(inspection_session, 2, D1, "camera1_image", 0)  # まだ正解なし
    inspection_session.flush()

    repo = DailyMetricsRepository(db_session)
    service = AggregationService(inspection_session, repo)
    service.aggregate_day(D1)
    assert repo.read(D1, D1)[0].annotated_count == 1

    # img2 に後追いでアノテーション付与 → 再集計
    _annotate(inspection_session, 2, _ITEM_OK)
    inspection_session.flush()
    service.aggregate_day(D1)

    rows = repo.read(D1, D1)
    assert len(rows) == 1  # 重複なし
    assert rows[0].annotated_count == 2


@pytest.mark.integration
def test_backfill_aggregates_each_day(inspection_session: Session, db_session: Session) -> None:
    """backfill が期間内の各日を集計する。"""
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.services.aggregation_service import AggregationService

    _seed_categories(inspection_session)
    _insert_image(inspection_session, 1, D1, "camera1_image", 0)
    _annotate(inspection_session, 1, _ITEM_OK)
    _insert_image(inspection_session, 2, D2, "camera1_image", 1)
    _annotate(inspection_session, 2, _ITEM_NG)
    inspection_session.flush()

    repo = DailyMetricsRepository(db_session)
    service = AggregationService(inspection_session, repo)
    service.backfill(D1, D2)

    assert len(repo.read(D1, D1)) == 1
    assert len(repo.read(D2, D2)) == 1
    assert repo.read(D2, D2)[0].ng_count == 1


@pytest.mark.integration
def test_aggregate_window_reaggregates_recent_days(
    inspection_session: Session, db_session: Session
) -> None:
    """aggregate_window が直近 n 日（end_date 起点）を再集計する。"""
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.services.aggregation_service import AggregationService

    _seed_categories(inspection_session)
    _insert_image(inspection_session, 1, D1, "camera1_image", 0)
    _annotate(inspection_session, 1, _ITEM_OK)
    _insert_image(inspection_session, 2, D2, "camera1_image", 0)
    _annotate(inspection_session, 2, _ITEM_OK)
    inspection_session.flush()

    repo = DailyMetricsRepository(db_session)
    service = AggregationService(inspection_session, repo)

    service.aggregate_window(window_days=2, end_date=D2)
    assert len(repo.read(D1, D2)) == 2

    # 既定引数（AGG_WINDOW_DAYS・今日起点）でも例外なく走る。
    service.aggregate_window()
