"""色一覧取り込みサービス（color C-R1）。

xlsx（`Sheet1`）をパースし、同一性タプル＋色見本を抽出して `upsert_by_tuple`。
新規は未実施・時刻は取り込み時刻。**`status`・`update_date` 列は無視**。
`color_no`・`size` は文字列で保持（ゼロ埋め維持）、`color_no` は前後空白を trim。
結果レポート（created/updated/skipped/errors）を返す。
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import openpyxl
from sqlalchemy.orm import Session

from src.repositories.color_master_repository import ColorMasterRepository
from src.schemas.color_master import ImportResult

_SHEET = "Sheet1"


def _to_str(value: Any) -> str:
    """セル値を文字列化する（None は空文字）。"""
    if value is None:
        return ""
    return str(value)


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


class ColorImportService:
    """一覧ファイルの取り込み（パース→upsert→結果レポート）。"""

    def __init__(self, session: Session) -> None:
        self._repo = ColorMasterRepository(session)

    def import_workbook(self, data: bytes) -> ImportResult:
        """xlsx バイト列を取り込み、結果レポートを返す。"""
        workbook = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)
        worksheet = workbook[_SHEET]
        rows = worksheet.iter_rows(values_only=True)

        header = next(rows, None)
        if header is None:
            return ImportResult(created=0, updated=0, skipped=0, errors=["ヘッダ行がありません"])
        index = {name: i for i, name in enumerate(header) if name is not None}

        created = updated = skipped = 0
        errors: list[str] = []

        for row_number, row in enumerate(rows, start=2):
            color_no = _to_str(_cell(row, index, "color_no")).strip()
            size = _to_str(_cell(row, index, "size"))
            chain = _to_str(_cell(row, index, "chain"))
            tape = _to_str(_cell(row, index, "tape"))  # 空欄可

            if not color_no or not size or not chain:
                errors.append(f"行{row_number}: color_no / size / chain が必要です")
                skipped += 1
                continue

            existed = self._repo.find_by_tuple(color_no, size, chain, tape) is not None
            self._repo.upsert_by_tuple(
                color_no=color_no,
                size=size,
                chain=chain,
                tape=tape,
                rgb_r=_to_int(_cell(row, index, "R")),
                rgb_g=_to_int(_cell(row, index, "G")),
                rgb_b=_to_int(_cell(row, index, "B")),
                lab_l=_to_float(_cell(row, index, "L")),
                lab_a=_to_float(_cell(row, index, "a")),
                lab_b=_to_float(_cell(row, index, "b")),
            )
            if existed:
                updated += 1
            else:
                created += 1

        return ImportResult(created=created, updated=updated, skipped=skipped, errors=errors)


def _cell(row: tuple[Any, ...], index: dict[str, int], name: str) -> Any:
    """ヘッダ名から該当セルを取り出す（列が無ければ None）。"""
    position = index.get(name)
    if position is None or position >= len(row):
        return None
    return row[position]
