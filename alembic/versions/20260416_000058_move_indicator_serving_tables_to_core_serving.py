"""move indicator serving tables to core_serving

Revision ID: 20260416_000058
Revises: 20260416_000057
Create Date: 2026-04-16
"""

from __future__ import annotations

from alembic import op


revision = "20260416_000058"
down_revision = "20260416_000057"
branch_labels = None
depends_on = None


def _merge_core_to_serving(table_name: str, columns_sql: str, pk_sql: str, update_sql: str) -> None:
    op.execute(
        f"""
DO $$
BEGIN
    IF to_regclass('core.{table_name}') IS NOT NULL THEN
        IF to_regclass('core_serving.{table_name}') IS NULL THEN
            EXECUTE 'ALTER TABLE core.{table_name} SET SCHEMA core_serving';
        ELSE
            EXECUTE $SQL$
                INSERT INTO core_serving.{table_name} ({columns_sql})
                SELECT {columns_sql}
                FROM core.{table_name}
                ON CONFLICT ({pk_sql}) DO UPDATE
                SET {update_sql}
            $SQL$;
            EXECUTE 'DROP TABLE core.{table_name}';
        END IF;
    END IF;
END
$$;
        """
    )


def _merge_serving_to_core(table_name: str, columns_sql: str, pk_sql: str, update_sql: str) -> None:
    op.execute(
        f"""
DO $$
BEGIN
    IF to_regclass('core_serving.{table_name}') IS NOT NULL THEN
        IF to_regclass('core.{table_name}') IS NULL THEN
            EXECUTE 'ALTER TABLE core_serving.{table_name} SET SCHEMA core';
        ELSE
            EXECUTE $SQL$
                INSERT INTO core.{table_name} ({columns_sql})
                SELECT {columns_sql}
                FROM core_serving.{table_name}
                ON CONFLICT ({pk_sql}) DO UPDATE
                SET {update_sql}
            $SQL$;
            EXECUTE 'DROP TABLE core_serving.{table_name}';
        END IF;
    END IF;
END
$$;
        """
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")

    columns = "ts_code, trade_date, adjustment, version, created_at, updated_at, is_valid"
    pk = "ts_code, trade_date, adjustment, version"

    _merge_core_to_serving(
        table_name="ind_macd",
        columns_sql=f"{columns}, dif, dea, macd_bar",
        pk_sql=pk,
        update_sql=(
            "created_at = LEAST(core_serving.ind_macd.created_at, EXCLUDED.created_at), "
            "updated_at = GREATEST(core_serving.ind_macd.updated_at, EXCLUDED.updated_at), "
            "is_valid = EXCLUDED.is_valid, "
            "dif = EXCLUDED.dif, "
            "dea = EXCLUDED.dea, "
            "macd_bar = EXCLUDED.macd_bar"
        ),
    )
    _merge_core_to_serving(
        table_name="ind_kdj",
        columns_sql=f"{columns}, rsv, k, d, j",
        pk_sql=pk,
        update_sql=(
            "created_at = LEAST(core_serving.ind_kdj.created_at, EXCLUDED.created_at), "
            "updated_at = GREATEST(core_serving.ind_kdj.updated_at, EXCLUDED.updated_at), "
            "is_valid = EXCLUDED.is_valid, "
            "rsv = EXCLUDED.rsv, "
            "k = EXCLUDED.k, "
            "d = EXCLUDED.d, "
            "j = EXCLUDED.j"
        ),
    )
    _merge_core_to_serving(
        table_name="ind_rsi",
        columns_sql=f"{columns}, rsi_6, rsi_12, rsi_24",
        pk_sql=pk,
        update_sql=(
            "created_at = LEAST(core_serving.ind_rsi.created_at, EXCLUDED.created_at), "
            "updated_at = GREATEST(core_serving.ind_rsi.updated_at, EXCLUDED.updated_at), "
            "is_valid = EXCLUDED.is_valid, "
            "rsi_6 = EXCLUDED.rsi_6, "
            "rsi_12 = EXCLUDED.rsi_12, "
            "rsi_24 = EXCLUDED.rsi_24"
        ),
    )


def downgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")

    columns = "ts_code, trade_date, adjustment, version, created_at, updated_at, is_valid"
    pk = "ts_code, trade_date, adjustment, version"

    _merge_serving_to_core(
        table_name="ind_macd",
        columns_sql=f"{columns}, dif, dea, macd_bar",
        pk_sql=pk,
        update_sql=(
            "created_at = LEAST(core.ind_macd.created_at, EXCLUDED.created_at), "
            "updated_at = GREATEST(core.ind_macd.updated_at, EXCLUDED.updated_at), "
            "is_valid = EXCLUDED.is_valid, "
            "dif = EXCLUDED.dif, "
            "dea = EXCLUDED.dea, "
            "macd_bar = EXCLUDED.macd_bar"
        ),
    )
    _merge_serving_to_core(
        table_name="ind_kdj",
        columns_sql=f"{columns}, rsv, k, d, j",
        pk_sql=pk,
        update_sql=(
            "created_at = LEAST(core.ind_kdj.created_at, EXCLUDED.created_at), "
            "updated_at = GREATEST(core.ind_kdj.updated_at, EXCLUDED.updated_at), "
            "is_valid = EXCLUDED.is_valid, "
            "rsv = EXCLUDED.rsv, "
            "k = EXCLUDED.k, "
            "d = EXCLUDED.d, "
            "j = EXCLUDED.j"
        ),
    )
    _merge_serving_to_core(
        table_name="ind_rsi",
        columns_sql=f"{columns}, rsi_6, rsi_12, rsi_24",
        pk_sql=pk,
        update_sql=(
            "created_at = LEAST(core.ind_rsi.created_at, EXCLUDED.created_at), "
            "updated_at = GREATEST(core.ind_rsi.updated_at, EXCLUDED.updated_at), "
            "is_valid = EXCLUDED.is_valid, "
            "rsi_6 = EXCLUDED.rsi_6, "
            "rsi_12 = EXCLUDED.rsi_12, "
            "rsi_24 = EXCLUDED.rsi_24"
        ),
    )
