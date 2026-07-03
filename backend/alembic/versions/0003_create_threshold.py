"""create threshold

閾値管理（R1）の補填テーブル。同一(メトリクス, スコープ, フルタプル)で有効期間が
重複しないことを btree_gist の部分排他制約で保証する（per_color / global を分離）。

Revision ID: 0003_create_threshold
Revises: 0002_create_daily_metrics
Create Date: 2026-07-02

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_create_threshold"
down_revision: str | None = "0002_create_daily_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """threshold を作成する（CHECK・部分排他制約・解決用索引つき）。"""
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.execute("""
        CREATE TABLE threshold (
            id bigserial PRIMARY KEY,
            metric text NOT NULL,
            scope text NOT NULL,
            color_no text,
            size text,
            chain text,
            tape text,
            value_pct numeric(5, 2) NOT NULL,
            valid_from timestamptz NOT NULL,
            valid_to timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_threshold_value_pct CHECK (value_pct >= 0 AND value_pct <= 100),
            CONSTRAINT ck_threshold_period CHECK (valid_to IS NULL OR valid_to > valid_from),
            CONSTRAINT ck_threshold_metric
                CHECK (metric IN ('ng_rate', 'false_alarm_rate', 'miss_rate')),
            CONSTRAINT ck_threshold_scope CHECK (scope IN ('global', 'per_color')),
            CONSTRAINT ck_threshold_scope_cols CHECK (
                (scope = 'per_color'
                    AND color_no IS NOT NULL AND size IS NOT NULL
                    AND chain IS NOT NULL AND tape IS NOT NULL)
                OR (scope = 'global'
                    AND color_no IS NULL AND size IS NULL
                    AND chain IS NULL AND tape IS NULL)
            )
        )
        """)

    # per_color 用の部分排他制約（フルタプル一致かつ期間が重なる行を禁止）
    op.execute("""
        ALTER TABLE threshold ADD CONSTRAINT ex_threshold_per_color
        EXCLUDE USING gist (
            metric WITH =, color_no WITH =, size WITH =, chain WITH =, tape WITH =,
            tstzrange(valid_from, valid_to) WITH &&
        ) WHERE (scope = 'per_color')
        """)

    # global 用の部分排他制約（色カラムが NULL のため per_color とは別制約が必須）
    op.execute("""
        ALTER TABLE threshold ADD CONSTRAINT ex_threshold_global
        EXCLUDE USING gist (
            metric WITH =, tstzrange(valid_from, valid_to) WITH &&
        ) WHERE (scope = 'global')
        """)

    op.execute(
        "CREATE INDEX ix_threshold_resolve "
        "ON threshold (metric, scope, color_no, size, chain, tape)"
    )


def downgrade() -> None:
    """threshold を削除する（btree_gist 拡張は他で使う可能性があり残す）。"""
    op.execute("DROP TABLE threshold")
