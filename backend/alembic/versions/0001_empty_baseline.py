"""empty baseline

ver2 DB の空の初期マイグレーション（ベースライン）。テーブルは持たない。
以降の ver2 テーブル追加は各機能 spec が本リビジョンを起点に積む。

Revision ID: 0001_empty_baseline
Revises:
Create Date: 2026-07-02

"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_empty_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """空ベースライン: スキーマ変更なし。"""
    pass


def downgrade() -> None:
    """空ベースライン: スキーマ変更なし。"""
    pass
