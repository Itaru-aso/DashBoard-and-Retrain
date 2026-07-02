"""業者検査 DB 読み取り専用モデル（dashboard task1）の integration テスト。

schema-spec-mapping の主要3テーブル（image_base / annotation_item / dataset_category_item）
の読み取り専用モデルが、業者検査 DB 代役（inspection_session）経由で読めることを確認する。
これらは ExternalBase 側であり ver2 Base（Alembic 対象）には載らない。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session


@pytest.mark.integration
def test_external_models_readable_via_inspection(inspection_session: Session) -> None:
    """3テーブルの読み取り専用モデルを代役 DB から読める。"""
    from src.models.external.annotation_item import AnnotationItem
    from src.models.external.dataset_category_item import DatasetCategoryItem
    from src.models.external.image_base import ImageBase

    inspection_session.execute(
        text(
            "INSERT INTO annotation.image_base "
            "(image_id, inspect_timestamp, unit, camera_model, judgment_result, extra_info) "
            "VALUES (1, :ts, '1', 'camera1_image', 0, '{}')"
        ),
        {"ts": datetime(2026, 7, 1, 10, 0, 0)},
    )
    inspection_session.execute(
        text(
            "INSERT INTO annotation.annotation_item (image_id, dataset_id, item_id, use_flg) "
            "VALUES (1, 1, 10, true)"
        )
    )
    inspection_session.execute(
        text(
            "INSERT INTO admin.dataset_category_item (dataset_id, item_id, on_class) "
            "VALUES (1, 10, '0')"
        )
    )
    inspection_session.flush()

    image = inspection_session.get(ImageBase, 1)
    assert image is not None
    assert image.camera_model == "camera1_image"

    ann = inspection_session.scalars(
        select(AnnotationItem).where(AnnotationItem.image_id == 1)
    ).one()
    assert ann.item_id == 10
    assert ann.use_flg is True

    cat = inspection_session.get(DatasetCategoryItem, (1, 10))
    assert cat is not None
    assert cat.on_class == "0"


@pytest.mark.integration
def test_external_models_not_in_ver2_base() -> None:
    """業者検査 DB のモデルは ver2 Base（Alembic 対象）に載らない。"""
    from src.database import Base
    from src.models.external.annotation_item import AnnotationItem
    from src.models.external.dataset_category_item import DatasetCategoryItem

    assert "annotation.annotation_item" not in Base.metadata.tables
    assert "admin.dataset_category_item" not in Base.metadata.tables
    # ExternalBase 側には登録されている
    assert AnnotationItem.__tablename__ == "annotation_item"
    assert DatasetCategoryItem.__tablename__ == "dataset_category_item"
