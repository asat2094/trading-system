"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-17
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# TIMESTAMPTZ is TIMESTAMP(timezone=True) in SQLAlchemy
TIMESTAMPTZ = sa.TIMESTAMP(timezone=True)

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "stocks",
        sa.Column("symbol", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("sector", sa.Text),
        sa.Column("industry", sa.Text),
        sa.Column("market_cap", sa.BigInteger),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.CheckConstraint("exchange IN ('NSE','BSE')", name="stocks_exchange_check"),
    )

    op.create_table(
        "stock_attributes",
        sa.Column("symbol", sa.Text, sa.ForeignKey("stocks.symbol", ondelete="CASCADE"), nullable=False),
        sa.Column("group_name", sa.Text, nullable=False),
        sa.Column("attributes", JSONB, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", "group_name"),
    )
    op.execute("CREATE INDEX idx_stock_attributes_gin ON stock_attributes USING GIN (attributes)")

    op.create_table(
        "scan_results",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scan_name", sa.Text, nullable=False),
        sa.Column("run_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("signals", JSONB, nullable=False),
        sa.Column("score", sa.Numeric),
    )
    op.create_index("idx_scan_results_name_run", "scan_results", ["scan_name", sa.text("run_at DESC")])
    op.create_index("idx_scan_results_symbol", "scan_results", ["symbol", sa.text("run_at DESC")])

    op.create_table(
        "trading_calendar",
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("is_trading", sa.Boolean, nullable=False),
        sa.Column("session_type", sa.Text),
        sa.Column("open_time", sa.Time),
        sa.Column("close_time", sa.Time),
        sa.Column("minutes", sa.Integer),
        sa.PrimaryKeyConstraint("date", "exchange"),
    )

    op.create_table(
        "agent_activities",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("generator", sa.Text),
        sa.Column("prompt", sa.Text),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("approved_by", sa.Text),
        sa.Column("approved_at", TIMESTAMPTZ),
        sa.Column("disabled_at", TIMESTAMPTZ),
        sa.Column("git_sha", sa.Text),
        sa.CheckConstraint(
            "status IN ('proposed','approved','promoted','disabled')",
            name="agent_activities_status_check",
        ),
    )

    op.create_table(
        "market_event_types",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("description", sa.Text),
        sa.Column("source", sa.Text),
        sa.Column("collection_windows", JSONB, nullable=False),
        sa.Column("schema_hint", JSONB),
    )

    op.create_table(
        "market_events",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.Text, sa.ForeignKey("market_event_types.name", ondelete="RESTRICT"), nullable=False),
        sa.Column("collection_label", sa.Text, nullable=False, server_default="default"),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("symbol", sa.Text, sa.ForeignKey("stocks.symbol", ondelete="SET NULL")),
        sa.Column("rank", sa.Integer),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("captured_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_market_events_dedup ON market_events "
        "(event_type, collection_label, date, COALESCE(symbol, ''))"
    )
    op.create_index("idx_market_events_type", "market_events", ["event_type", sa.text("date DESC")])
    op.create_index(
        "idx_market_events_symbol", "market_events",
        ["symbol", "event_type", sa.text("date DESC")]
    )
    op.execute("CREATE INDEX idx_market_events_gin ON market_events USING GIN (data)")

    op.create_table(
        "data_quality_alerts",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("check_name", sa.Text, nullable=False),
        sa.Column("symbol", sa.Text),
        sa.Column("timeframe", sa.Text),
        sa.Column("detail", JSONB),
        sa.Column("fired_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("resolved_at", TIMESTAMPTZ),
    )

    op.create_table(
        "adjustment_factors",
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("factor", sa.Numeric, nullable=False),
        sa.Column("action_type", sa.Text),
        sa.PrimaryKeyConstraint("symbol", "effective_date"),
    )


def downgrade() -> None:
    for table in [
        "adjustment_factors",
        "data_quality_alerts",
        "market_events",
        "market_event_types",
        "agent_activities",
        "trading_calendar",
        "scan_results",
        "stock_attributes",
        "stocks",
    ]:
        op.drop_table(table)
