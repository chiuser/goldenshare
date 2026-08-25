"""add ETF historical minute bar table on HDD

Revision ID: 20260825_000151
Revises: 20260824_000150
Create Date: 2026-08-25
"""

from __future__ import annotations

from datetime import date

from alembic import op
import sqlalchemy as sa


revision = "20260825_000151"
down_revision = "20260824_000150"
branch_labels = None
depends_on = None

_SCHEMA = "raw_tushare"
_TABLE = "etf_minute_bar"
_TABLESPACE = "gs_raw_cold_hdd"
_FIRST_MONTH = date(2009, 1, 1)
_LAST_MONTH = date(2037, 12, 1)


def _assert_hdd_tablespace() -> None:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"),
        {"name": _TABLESPACE},
    ).scalar()
    if not exists:
        raise RuntimeError(
            f"ETF 历史分钟行情要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD"
        )


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _partition_months() -> tuple[date, ...]:
    months: list[date] = []
    cursor = _FIRST_MONTH
    while cursor <= _LAST_MONTH:
        months.append(cursor)
        cursor = _next_month(cursor)
    return tuple(months)


def _move_relation_indexes_to_hdd(relation_name: str) -> None:
    index_names = op.get_bind().execute(
        sa.text(
            "SELECT quote_ident(index_ns.nspname) || '.' || quote_ident(index_rel.relname) "
            "FROM pg_index index_info "
            "JOIN pg_class table_rel ON table_rel.oid = index_info.indrelid "
            "JOIN pg_namespace table_ns ON table_ns.oid = table_rel.relnamespace "
            "JOIN pg_class index_rel ON index_rel.oid = index_info.indexrelid "
            "JOIN pg_namespace index_ns ON index_ns.oid = index_rel.relnamespace "
            "WHERE table_ns.nspname = :schema AND table_rel.relname = :relation"
        ),
        {"schema": _SCHEMA, "relation": relation_name},
    ).scalars()
    for index_name in index_names:
        op.execute(f"ALTER INDEX {index_name} SET TABLESPACE {_TABLESPACE}")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _assert_hdd_tablespace()
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
    op.execute(
        f"""
        CREATE TABLE {_SCHEMA}.{_TABLE} (
            ts_code varchar(16) NOT NULL,
            freq varchar(8) NOT NULL,
            trade_time timestamp without time zone NOT NULL,
            open double precision,
            close double precision,
            high double precision,
            low double precision,
            vol bigint,
            amount double precision,
            vwap double precision,
            exchange varchar(16),
            CONSTRAINT pk_raw_tushare_etf_minute_bar
                PRIMARY KEY (ts_code, freq, trade_time)
                USING INDEX TABLESPACE {_TABLESPACE}
        ) PARTITION BY RANGE (trade_time)
        TABLESPACE {_TABLESPACE}
        """
    )

    partition_names: list[str] = []
    for month_start in _partition_months():
        month_end = _next_month(month_start)
        partition_name = f"{_TABLE}_{month_start:%Y%m}"
        partition_names.append(partition_name)
        op.execute(
            f"CREATE TABLE {_SCHEMA}.{partition_name} "
            f"PARTITION OF {_SCHEMA}.{_TABLE} "
            f"FOR VALUES FROM ('{month_start.isoformat()}') TO ('{month_end.isoformat()}') "
            f"TABLESPACE {_TABLESPACE}"
        )

    default_partition = f"{_TABLE}_default"
    partition_names.append(default_partition)
    op.execute(
        f"CREATE TABLE {_SCHEMA}.{default_partition} "
        f"PARTITION OF {_SCHEMA}.{_TABLE} DEFAULT "
        f"TABLESPACE {_TABLESPACE}"
    )
    op.execute(
        f"CREATE INDEX idx_raw_tushare_etf_minute_bar_freq_trade_time_ts_code "
        f"ON {_SCHEMA}.{_TABLE} (freq, trade_time DESC, ts_code) "
        f"TABLESPACE {_TABLESPACE}"
    )

    _move_relation_indexes_to_hdd(_TABLE)
    for partition_name in partition_names:
        _move_relation_indexes_to_hdd(partition_name)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    existing_rows = bind.execute(
        sa.text(f"SELECT EXISTS (SELECT 1 FROM {_SCHEMA}.{_TABLE} LIMIT 1)")
    ).scalar()
    if existing_rows:
        raise RuntimeError("ETF 历史分钟表已有业务数据，禁止自动 downgrade 删除")
    op.execute(f"DROP TABLE {_SCHEMA}.{_TABLE}")
