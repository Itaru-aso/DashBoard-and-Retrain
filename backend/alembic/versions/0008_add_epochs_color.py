"""add epochs_color to retraining_job

再学習ジョブに color 学習の epochs 上書き値（任意）を追加する（retraining epochs override）。
未指定（NULL）時は training/ 側の config.yaml 既定値（epochs=40）にフォールバックする。
monochro の epochs は対象外（316 の ADR チューニングは color 限定のため）。

Revision ID: 0008_add_epochs_color
Revises: 0007_create_retraining
Create Date: 2026-08-03

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_add_epochs_color"
down_revision: str | None = "0007_create_retraining"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """retraining_job に epochs_color（nullable）を追加する。"""
    op.execute("ALTER TABLE retraining_job ADD COLUMN epochs_color integer")


def downgrade() -> None:
    """epochs_color を削除する。"""
    op.execute("ALTER TABLE retraining_job DROP COLUMN epochs_color")
