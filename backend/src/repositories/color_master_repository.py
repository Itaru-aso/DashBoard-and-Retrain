"""色マスター Repository（ver2 DB・color C-R1, C-R2, C-R5）。

- create: 未実施で新規作成。
- upsert_by_tuple: 同一タプルがあれば色見本を更新し **status は保持**、無ければ未実施で作成。
- set_status: 未実施 → 量産検証 → 実生産 の**隣接前進のみ**（後戻り・段飛ばしは拒否）。
  遷移時に verification_at / production_at を記録。
- list / find_by_status: 検索。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.color_master import ColorMaster

_ORDER = ["未実施", "量産検証", "実生産"]


class ColorTransitionError(Exception):
    """status 遷移が前進（隣接）でない（後戻り・段飛ばし）。"""


class ColorMasterRepository:
    """color_master（ver2 DB）の登録・upsert・状態更新・検索。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, color_id: int) -> ColorMaster | None:
        """id で取得する。"""
        return self._session.get(ColorMaster, color_id)

    def find_by_tuple(self, color_no: str, size: str, chain: str, tape: str) -> ColorMaster | None:
        """同一性タプルで取得する。"""
        stmt = select(ColorMaster).where(
            ColorMaster.color_no == color_no,
            ColorMaster.size == size,
            ColorMaster.chain == chain,
            ColorMaster.tape == tape,
        )
        return self._session.scalars(stmt).one_or_none()

    def create(
        self,
        color_no: str,
        size: str,
        chain: str,
        tape: str,
        rgb_r: int | None = None,
        rgb_g: int | None = None,
        rgb_b: int | None = None,
        lab_l: float | None = None,
        lab_a: float | None = None,
        lab_b: float | None = None,
    ) -> ColorMaster:
        """未実施で色を新規作成する。"""
        color = ColorMaster(
            color_no=color_no,
            size=size,
            chain=chain,
            tape=tape,
            rgb_r=rgb_r,
            rgb_g=rgb_g,
            rgb_b=rgb_b,
            lab_l=lab_l,
            lab_a=lab_a,
            lab_b=lab_b,
            status="未実施",
        )
        self._session.add(color)
        self._session.flush()
        self._session.refresh(color)
        return color

    def upsert_by_tuple(
        self,
        color_no: str,
        size: str,
        chain: str,
        tape: str,
        rgb_r: int | None = None,
        rgb_g: int | None = None,
        rgb_b: int | None = None,
        lab_l: float | None = None,
        lab_a: float | None = None,
        lab_b: float | None = None,
    ) -> ColorMaster:
        """タプルで upsert する（既存は色見本を更新し status は保持）。"""
        existing = self.find_by_tuple(color_no, size, chain, tape)
        if existing is None:
            return self.create(
                color_no, size, chain, tape, rgb_r, rgb_g, rgb_b, lab_l, lab_a, lab_b
            )
        existing.rgb_r = rgb_r
        existing.rgb_g = rgb_g
        existing.rgb_b = rgb_b
        existing.lab_l = None if lab_l is None else Decimal(str(lab_l))
        existing.lab_a = None if lab_a is None else Decimal(str(lab_a))
        existing.lab_b = None if lab_b is None else Decimal(str(lab_b))
        existing.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        self._session.refresh(existing)
        return existing

    def set_status(self, color_id: int, target: str) -> ColorMaster:
        """隣接前進のみ許可し、遷移時刻を記録する。"""
        color = self._session.get(ColorMaster, color_id)
        if color is None:
            raise ColorTransitionError(f"color {color_id} が見つかりません")
        current_idx = _ORDER.index(color.status)
        target_idx = _ORDER.index(target)
        if target_idx != current_idx + 1:
            raise ColorTransitionError(
                f"{color.status} -> {target} は許可されない遷移です（隣接前進のみ）"
            )
        now = datetime.now(timezone.utc)
        color.status = target
        if target == "量産検証":
            color.verification_at = now
        elif target == "実生産":
            color.production_at = now
        color.updated_at = now
        self._session.flush()
        self._session.refresh(color)
        return color

    def list(
        self,
        status: str | None = None,
        color_no: str | None = None,
        size: str | None = None,
        chain: str | None = None,
        tape: str | None = None,
    ) -> list[ColorMaster]:
        """絞り込んで一覧する。"""
        stmt = select(ColorMaster)
        if status is not None:
            stmt = stmt.where(ColorMaster.status == status)
        if color_no is not None:
            stmt = stmt.where(ColorMaster.color_no == color_no)
        if size is not None:
            stmt = stmt.where(ColorMaster.size == size)
        if chain is not None:
            stmt = stmt.where(ColorMaster.chain == chain)
        if tape is not None:
            stmt = stmt.where(ColorMaster.tape == tape)
        stmt = stmt.order_by(ColorMaster.color_no, ColorMaster.size)
        return list(self._session.scalars(stmt))

    def find_by_status(self, status: str) -> Sequence[ColorMaster]:
        """指定 status の色を返す。"""
        return self.list(status=status)
