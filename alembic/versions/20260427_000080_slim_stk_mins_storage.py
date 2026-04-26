"""slim stk_mins storage

Revision ID: 20260427_000080
Revises: 20260426_000079
Create Date: 2026-04-27
"""

from __future__ import annotations

from datetime import date

from alembic import op
import sqlalchemy as sa


revision = "20260427_000080"
down_revision = "20260426_000079"
branch_labels = None
depends_on = None


def _month_starts(start_year: int, end_year_exclusive: int) -> list[date]:
    return [date(year, month, 1) for year in range(start_year, end_year_exclusive) for month in range(1, 13)]


def _tablespace_exists(name: str) -> bool:
    bind = op.get_bind()
    return bool(bind.execute(sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"), {"name": name}).scalar())


def _add_dataset_status_observed_at_columns() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("dataset_status_snapshot", schema="ops"):
        return
    columns = {column["name"] for column in inspector.get_columns("dataset_status_snapshot", schema="ops")}
    if "earliest_observed_at" not in columns:
        op.add_column(
            "dataset_status_snapshot",
            sa.Column("earliest_observed_at", sa.DateTime(timezone=True), nullable=True),
            schema="ops",
        )
    if "latest_observed_at" not in columns:
        op.add_column(
            "dataset_status_snapshot",
            sa.Column("latest_observed_at", sa.DateTime(timezone=True), nullable=True),
            schema="ops",
        )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    _add_dataset_status_observed_at_columns()

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('raw_tushare.stk_mins') IS NOT NULL
               AND EXISTS (SELECT 1 FROM raw_tushare.stk_mins LIMIT 1) THEN
                RAISE EXCEPTION 'raw_tushare.stk_mins is not empty; stop before slimming storage';
            END IF;
        END $$;
        """
    )
    op.execute("DROP VIEW IF EXISTS core_serving.equity_minute_bar")
    op.execute("DROP TABLE IF EXISTS raw_tushare.stk_mins CASCADE")
    op.execute(
        """
        CREATE TABLE raw_tushare.stk_mins (
            ts_code varchar(16) NOT NULL,
            freq smallint NOT NULL,
            trade_time timestamp without time zone NOT NULL,
            open real,
            close real,
            high real,
            low real,
            vol integer,
            amount real,
            CONSTRAINT pk_raw_tushare_stk_mins PRIMARY KEY (ts_code, freq, trade_time)
        ) PARTITION BY RANGE (trade_time)
        """
    )

    hdd_tablespace = "gs_stk_mins_hdd"
    has_hdd_tablespace = _tablespace_exists(hdd_tablespace)
    month_starts = _month_starts(2010, 2037)
    for index, start_date in enumerate(month_starts):
        if index + 1 < len(month_starts):
            end_date = month_starts[index + 1]
        else:
            end_date = date(start_date.year + 1, 1, 1)
        partition_name = f"stk_mins_{start_date:%Y_%m}"
        tablespace_clause = f" TABLESPACE {hdd_tablespace}" if has_hdd_tablespace and start_date.year <= 2025 else ""
        op.execute(
            f"""
            CREATE TABLE raw_tushare.{partition_name}
            PARTITION OF raw_tushare.stk_mins
            FOR VALUES FROM ('{start_date.isoformat()} 00:00:00') TO ('{end_date.isoformat()} 00:00:00')
            {tablespace_clause}
            """
        )
        if has_hdd_tablespace and start_date.year <= 2025:
            op.execute(f"ALTER INDEX IF EXISTS raw_tushare.{partition_name}_pkey SET TABLESPACE {hdd_tablespace}")

    op.execute(
        """
        CREATE TABLE raw_tushare.stk_mins_default
        PARTITION OF raw_tushare.stk_mins DEFAULT
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW core_serving.equity_minute_bar AS
        SELECT
            ts_code,
            freq,
            trade_time,
            trade_time::date AS trade_date,
            open,
            close,
            high,
            low,
            vol,
            amount,
            'tushare'::varchar(32) AS source
        FROM raw_tushare.stk_mins
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core_serving.equity_minute_bar")
    op.execute("DROP TABLE IF EXISTS raw_tushare.stk_mins CASCADE")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("dataset_status_snapshot", schema="ops"):
        columns = {column["name"] for column in inspector.get_columns("dataset_status_snapshot", schema="ops")}
        if "latest_observed_at" in columns:
            op.drop_column("dataset_status_snapshot", "latest_observed_at", schema="ops")
        if "earliest_observed_at" in columns:
            op.drop_column("dataset_status_snapshot", "earliest_observed_at", schema="ops")
