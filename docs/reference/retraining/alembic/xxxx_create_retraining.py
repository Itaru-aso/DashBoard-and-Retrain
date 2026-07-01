"""create retraining_job and deployed_model

再学習ジョブ（履歴・状態）と現行配信モデル（色フルタプル単位）の2テーブルを作成する。
ver2 DB のみ対象（app_db は Alembic 管理外）。

Revision ID: <set on generate>
Revises: <set to current ver2 head>
Create Date: 2026-06-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers.
revision = "xxxx_create_retraining"
# TODO: ver2 の現行 head に合わせて設定する（複数 head 回避）。
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retraining_job",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("color_no", sa.String(length=50), nullable=False),
        sa.Column("size", sa.String(length=50), nullable=False),
        sa.Column("chain", sa.String(length=50), nullable=False),
        sa.Column("tape", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="QUEUED"),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("onnx_monochro_path", sa.String(length=1024), nullable=True),
        sa.Column("onnx_color_path", sa.String(length=1024), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_retraining_job_status",
        ),
    )
    op.create_index(
        "ix_retraining_job_tuple", "retraining_job",
        ["color_no", "size", "chain", "tape"],
    )
    op.create_index("ix_retraining_job_status", "retraining_job", ["status"])

    op.create_table(
        "deployed_model",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("color_no", sa.String(length=50), nullable=False),
        sa.Column("size", sa.String(length=50), nullable=False),
        sa.Column("chain", sa.String(length=50), nullable=False),
        sa.Column("tape", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("onnx_monochro_path", sa.String(length=1024), nullable=True),
        sa.Column("onnx_color_path", sa.String(length=1024), nullable=True),
        sa.Column("deploy_status", sa.String(length=20), nullable=False,
                  server_default="SUCCESS"),
        sa.Column("deploy_detail", sa.Text(), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["job_id"], ["retraining_job.id"], ondelete="RESTRICT",
            name="fk_deployed_model_job",
        ),
        sa.UniqueConstraint(
            "color_no", "size", "chain", "tape", name="uq_deployed_model_tuple"
        ),
        sa.CheckConstraint(
            "deploy_status IN ('SUCCESS','PARTIAL','FAILED')",
            name="ck_deployed_model_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("deployed_model")
    op.drop_index("ix_retraining_job_status", table_name="retraining_job")
    op.drop_index("ix_retraining_job_tuple", table_name="retraining_job")
    op.drop_table("retraining_job")
