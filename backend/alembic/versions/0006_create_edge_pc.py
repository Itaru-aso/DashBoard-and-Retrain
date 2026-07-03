"""create edge_pc

エッジPC（検査PC）の接続情報（edge E-R1）。配信先＝有効な全台（find_enabled）。
パスワードは ver1 踏襲で平文（任意）。配信ポートは model_port。FTP 送信可否を記録。

Revision ID: 0006_create_edge_pc
Revises: 0005_create_color_master
Create Date: 2026-07-03

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_create_edge_pc"
down_revision: str | None = "0005_create_color_master"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """edge_pc を作成する（name ユニーク）。"""
    op.execute("""
        CREATE TABLE edge_pc (
            id bigserial PRIMARY KEY,
            name text NOT NULL,
            host text NOT NULL,
            username text,
            password text,
            model_port integer,
            enabled boolean NOT NULL DEFAULT true,
            last_ftp_ok boolean,
            last_ftp_checked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_edge_pc_name UNIQUE (name)
        )
        """)


def downgrade() -> None:
    """edge_pc を削除する。"""
    op.execute("DROP TABLE edge_pc")
