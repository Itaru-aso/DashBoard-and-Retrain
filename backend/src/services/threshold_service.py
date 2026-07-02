"""閾値 Service（R2, R3, R4）。

- resolve_effective: 色別 → global → None の優先順位で有効閾値を一意に解決（R3）。
- create: 検証済みデータを登録。期間重複（排他制約違反）は Conflict 例外へ変換（R1.2）。
- update: 指定項目を in-place 更新（未有効化レコードの訂正）。重複は Conflict。
- supersede: 現行を close（valid_to=at）＋新規作成（valid_from=at）で履歴保持（R2.1）。
- disable: valid_to を設定して以降を解決対象外にする（R2.3）。

排他制約違反は begin_nested（SAVEPOINT）で局所ロールバックし、セッションを再利用可能に保つ。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models.threshold import Threshold
from src.repositories.threshold_repository import ThresholdRepository
from src.schemas.threshold import ThresholdCreate, ThresholdUpdate


class ThresholdConflictError(Exception):
    """有効期間が既存レコードと重複する（排他制約違反）。API では 409。"""


class ThresholdNotFoundError(Exception):
    """対象の閾値が存在しない。"""


class ThresholdService:
    """閾値の検証・解決・変更（supersede / disable）を担う Service。"""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ThresholdRepository(session)

    def get(self, threshold_id: int) -> Threshold | None:
        """id で取得する。"""
        return self._repo.get(threshold_id)

    def list(self, metric: str | None = None, scope: str | None = None) -> list[Threshold]:
        """メトリクス・スコープで絞り込んで一覧する。"""
        return self._repo.list(metric, scope)

    def resolve_effective(
        self, metric: str, color: Sequence[str], at: datetime
    ) -> Threshold | None:
        """色別 → global → None の優先順位で有効閾値を返す（高々1件）。"""
        per_color = self._repo.find_active(metric, "per_color", color, at)
        if per_color is not None:
            return per_color
        return self._repo.find_active(metric, "global", None, at)

    def create(self, data: ThresholdCreate) -> Threshold:
        """閾値を作成する。期間重複は ThresholdConflictError。"""
        try:
            with self._session.begin_nested():
                return self._repo.create(data)
        except IntegrityError as exc:
            raise ThresholdConflictError("有効期間が既存レコードと重複しています") from exc

    def update(self, threshold_id: int, data: ThresholdUpdate) -> Threshold | None:
        """指定項目を in-place 更新する。期間重複は ThresholdConflictError。"""
        try:
            with self._session.begin_nested():
                return self._repo.update(threshold_id, data)
        except IntegrityError as exc:
            raise ThresholdConflictError("有効期間が既存レコードと重複しています") from exc

    def supersede(self, threshold_id: int, new_value_pct: float, at: datetime) -> Threshold:
        """現行を close（valid_to=at）し、新値で新レコードを作成する（履歴保持）。"""
        current = self._repo.get(threshold_id)
        if current is None:
            raise ThresholdNotFoundError(f"threshold {threshold_id} が見つかりません")

        # 先に現行を閉じてから新規挿入（半開区間なので [.., at) と [at, ..) は重ならない）。
        current.valid_to = at
        current.updated_at = datetime.now(timezone.utc)
        self._session.flush()

        new_row = Threshold(
            metric=current.metric,
            scope=current.scope,
            color_no=current.color_no,
            size=current.size,
            chain=current.chain,
            tape=current.tape,
            value_pct=Decimal(str(new_value_pct)),
            valid_from=at,
            valid_to=None,
        )
        self._session.add(new_row)
        self._session.flush()
        self._session.refresh(new_row)
        return new_row

    def disable(self, threshold_id: int, at: datetime) -> Threshold | None:
        """valid_to を設定して以降を解決対象外にする。"""
        row = self._repo.get(threshold_id)
        if row is None:
            return None
        row.valid_to = at
        row.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        self._session.refresh(row)
        return row
