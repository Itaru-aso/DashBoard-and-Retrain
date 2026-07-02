"""create daily_metrics

日次集計基盤（A-R1）の集計テーブル。JST日 × フルタプル × 号機の件数を貯める。
ユニークキー (jst_date, color_no, size, chain, tape, unit)（tape は空文字も保持）。

Revision ID: 0002_create_daily_metrics
Revises: 0001_empty_baseline
Create Date: 2026-07-02

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_create_daily_metrics"
down_revision: str | None = "0001_empty_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """daily_metrics を作成する。"""
    op.create_table(
        "daily_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        # フルタプル × 号機 × JST日（ユニークキー。NULL を避け空文字で保持）
        sa.Column("jst_date", sa.Date(), nullable=False),
        sa.Column("color_no", sa.String(), nullable=False),
        sa.Column("size", sa.String(), nullable=False),
        sa.Column("chain", sa.String(), nullable=False),
        sa.Column("tape", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        # 件数（分子=全カメラ／分母=monochro。率は services/metrics.py で算出）
        sa.Column("monochro_count", sa.Integer(), nullable=False),
        sa.Column("ng_count", sa.Integer(), nullable=False),
        sa.Column("fp_num", sa.Integer(), nullable=False),
        sa.Column("miss_num", sa.Integer(), nullable=False),
        sa.Column("annotated_count", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "jst_date",
            "color_no",
            "size",
            "chain",
            "tape",
            "unit",
            name="uq_daily_metrics_identity",
        ),
    )


def downgrade() -> None:
    """daily_metrics を削除する。"""
    op.drop_table("daily_metrics")
