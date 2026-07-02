"""色一覧取り込みサービス（color C-R1）の integration テスト。

xlsx（Sheet1）をパースして upsert。color_no の trim・文字列保持・tape 空欄・
status 列無視（常に未実施）・不正行レポート・重複タプルの status 保持を検証する。
"""

from __future__ import annotations

from io import BytesIO

import openpyxl
import pytest
from sqlalchemy.orm import Session

_HEADER = [
    "status",
    "size",
    "chain",
    "tape",
    "color_no",
    "R",
    "G",
    "B",
    "L",
    "a",
    "b",
    "update_date",
]


def _xlsx(rows: list[list[object]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(_HEADER)
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _import(db: Session, data: bytes):
    from src.services.color_import_service import ColorImportService

    return ColorImportService(db).import_workbook(data)


@pytest.mark.integration
def test_import_creates_and_trims_and_keeps_string(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository

    data = _xlsx(
        [
            ["実生産", "05", "CZT8", "", "  001  ", 10, 20, 30, 50.0, 1.0, -2.0, "2026-01-01"],
        ]
    )
    result = _import(db_session, data)
    assert result.created == 1

    repo = ColorMasterRepository(db_session)
    color = repo.find_by_tuple("001", "05", "CZT8", "")
    assert color is not None  # color_no は trim される
    assert color.status == "未実施"  # status 列は無視（常に未実施）
    assert color.rgb_r == 10
    # 文字列保持: "001" は "1" と別
    assert repo.find_by_tuple("1", "05", "CZT8", "") is None


@pytest.mark.integration
def test_import_reports_invalid_row(db_session: Session) -> None:
    data = _xlsx(
        [
            ["", "05", "CZT8", "", "", 10, 20, 30, 50.0, 1.0, -2.0, ""],  # color_no 欠落
            ["", "05", "CZT8", "", "002", 1, 2, 3, 4.0, 5.0, 6.0, ""],
        ]
    )
    result = _import(db_session, data)
    assert result.created == 1
    assert result.skipped == 1
    assert len(result.errors) == 1


@pytest.mark.integration
def test_import_updates_and_keeps_status(db_session: Session) -> None:
    from src.repositories.color_master_repository import ColorMasterRepository

    repo = ColorMasterRepository(db_session)
    color = repo.create(color_no="001", size="05", chain="CZT8", tape="", rgb_r=1)
    repo.set_status(color.id, "量産検証")

    data = _xlsx([["", "05", "CZT8", "", "001", 99, 88, 77, 1.0, 2.0, 3.0, ""]])
    result = _import(db_session, data)
    assert result.updated == 1

    refreshed = repo.find_by_tuple("001", "05", "CZT8", "")
    assert refreshed.rgb_r == 99  # 色見本更新
    assert refreshed.status == "量産検証"  # status 保持
