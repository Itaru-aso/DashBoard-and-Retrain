"""create color_master

色マスター（C-R1.1）。同一性タプル＋色見本(RGB/Lab)＋ライフサイクル status（自動管理）。
同一性タプルはユニーク。status は 未実施 → 量産検証 → 実生産（一方向・自動遷移）。

Revision ID: 0005_create_color_master
Revises: 0004_create_task
Create Date: 2026-07-02

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_create_color_master"
down_revision: str | None = "0004_create_task"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """color_master を作成する（タプルユニーク・status CHECK）。"""
    op.execute(
        """
        CREATE TABLE color_master (
            id bigserial PRIMARY KEY,
            color_no text NOT NULL,
            size text NOT NULL,
            chain text NOT NULL,
            tape text NOT NULL,
            rgb_r integer,
            rgb_g integer,
            rgb_b integer,
            lab_l numeric(6, 2),
            lab_a numeric(6, 2),
            lab_b numeric(6, 2),
            status text NOT NULL DEFAULT '未実施',
            verification_at timestamptz,
            production_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_color_master_status
                CHECK (status IN ('未実施', '量産検証', '実生産')),
            CONSTRAINT uq_color_master_tuple UNIQUE (color_no, size, chain, tape)
        )
        """
    )


def downgrade() -> None:
    """color_master を削除する。"""
    op.execute("DROP TABLE color_master")
