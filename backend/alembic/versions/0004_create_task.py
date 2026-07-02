"""create task

保守タスク（task R2.5）。同キーにアクティブ（OPEN/IN_PROGRESS）なタスクは高々1件を
部分ユニークインデックスで担保する（DONE は再発履歴として重複可）。

Revision ID: 0004_create_task
Revises: 0003_create_threshold
Create Date: 2026-07-02

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_create_task"
down_revision: str | None = "0003_create_threshold"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """task を作成する（enum CHECK・comments JSONB・部分ユニーク）。"""
    op.execute(
        """
        CREATE TABLE task (
            id bigserial PRIMARY KEY,
            color_no text NOT NULL,
            size text NOT NULL,
            chain text NOT NULL,
            tape text NOT NULL,
            task_type text NOT NULL,
            status text NOT NULL DEFAULT 'OPEN',
            detected_value numeric(5, 2),
            threshold_value numeric(5, 2),
            evaluation_date date,
            comments jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_task_type
                CHECK (task_type IN ('ng_rate', 'false_alarm_rate', 'miss_rate')),
            CONSTRAINT ck_task_status
                CHECK (status IN ('OPEN', 'IN_PROGRESS', 'DONE'))
        )
        """
    )
    # 同キーにアクティブなタスクは高々1件（多重発火・同時実行でも DB で担保）。
    op.execute(
        """
        CREATE UNIQUE INDEX uq_task_active
        ON task (color_no, size, chain, tape, task_type)
        WHERE status IN ('OPEN', 'IN_PROGRESS')
        """
    )


def downgrade() -> None:
    """task を削除する。"""
    op.execute("DROP TABLE task")
