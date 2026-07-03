"""create retraining_job and deployed_model

再学習ジョブ（履歴・状態）と現行配信モデル（色フルタプル単位）の2テーブルを作成する（retraining M-R7, M-R8.3）。
status/deploy_status は CHECK 制約、deployed_model はフルタプルでユニーク、job_id は retraining_job への FK。
ver2 DB のみ対象（app_db は Alembic 管理外）。

Revision ID: 0007_create_retraining
Revises: 0006_create_edge_pc
Create Date: 2026-07-03

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_create_retraining"
down_revision: str | None = "0006_create_edge_pc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """retraining_job と deployed_model を作成する。"""
    op.execute("""
        CREATE TABLE retraining_job (
            id bigserial PRIMARY KEY,
            color_no text NOT NULL,
            size text NOT NULL DEFAULT '',
            chain text NOT NULL DEFAULT '',
            tape text NOT NULL DEFAULT '',
            status text NOT NULL DEFAULT 'QUEUED',
            queued_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz,
            finished_at timestamptz,
            error_message text,
            onnx_monochro_path text,
            onnx_color_path text,
            created_by text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_retraining_job_status
                CHECK (status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED'))
        )
        """)
    op.execute(
        "CREATE INDEX ix_retraining_job_tuple ON retraining_job " "(color_no, size, chain, tape)"
    )
    op.execute("CREATE INDEX ix_retraining_job_status ON retraining_job (status)")

    op.execute("""
        CREATE TABLE deployed_model (
            id bigserial PRIMARY KEY,
            color_no text NOT NULL,
            size text NOT NULL DEFAULT '',
            chain text NOT NULL DEFAULT '',
            tape text NOT NULL DEFAULT '',
            job_id bigint NOT NULL,
            onnx_monochro_path text,
            onnx_color_path text,
            deploy_status text NOT NULL DEFAULT 'SUCCESS',
            deploy_detail text,
            deployed_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_deployed_model_job
                FOREIGN KEY (job_id) REFERENCES retraining_job (id) ON DELETE RESTRICT,
            CONSTRAINT uq_deployed_model_tuple
                UNIQUE (color_no, size, chain, tape),
            CONSTRAINT ck_deployed_model_status
                CHECK (deploy_status IN ('SUCCESS','PARTIAL','FAILED'))
        )
        """)


def downgrade() -> None:
    """deployed_model と retraining_job を削除する。"""
    op.execute("DROP TABLE deployed_model")
    op.execute("DROP TABLE retraining_job")
