"""preserve top_list source variants

Revision ID: 20260507_000099
Revises: 20260506_000098
Create Date: 2026-05-07
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import math
import re
from typing import Any, Mapping
import unicodedata

from alembic import op
import sqlalchemy as sa


revision = "20260507_000099"
down_revision = "20260506_000098"
branch_labels = None
depends_on = None

RAW_SCHEMA = "raw_tushare"
RAW_LEGACY_SCHEMA = "raw"
SERVING_SCHEMA = "core_serving"
SERVING_LEGACY_SCHEMA = "core"
POLICY_VERSION = "top_list_variant_resolution_v1"
TOP_LIST_PAYLOAD_FIELDS = (
    "ts_code",
    "trade_date",
    "reason",
    "name",
    "close",
    "pct_change",
    "turnover_rate",
    "amount",
    "l_sell",
    "l_buy",
    "l_amount",
    "net_amount",
    "net_rate",
    "amount_rate",
    "float_values",
)
PSEUDO_NULL_TEXTS = {"", "nan", "nat", "none", "null"}
WHITESPACE_RE = re.compile(r"\s+")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}")
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SERVING_SCHEMA}")

    _move_table_if_needed(bind, source_schema=RAW_LEGACY_SCHEMA, target_schema=RAW_SCHEMA, table_name="top_list")
    _move_table_if_needed(bind, source_schema=SERVING_LEGACY_SCHEMA, target_schema=SERVING_SCHEMA, table_name="equity_top_list")

    if _table_exists(bind, RAW_SCHEMA, "top_list"):
        _upgrade_raw_top_list(bind)
    if _table_exists(bind, SERVING_SCHEMA, "equity_top_list"):
        _upgrade_serving_top_list(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if _table_exists(bind, SERVING_SCHEMA, "equity_top_list"):
        op.execute(
            f"ALTER TABLE {SERVING_SCHEMA}.equity_top_list "
            "DROP COLUMN IF EXISTS resolution_policy_version"
        )
        op.execute(
            f"ALTER TABLE {SERVING_SCHEMA}.equity_top_list "
            "DROP COLUMN IF EXISTS variant_count"
        )
        op.execute(
            f"ALTER TABLE {SERVING_SCHEMA}.equity_top_list "
            "DROP COLUMN IF EXISTS selected_payload_hash"
        )

    if _table_exists(bind, RAW_SCHEMA, "top_list"):
        op.execute(f"DROP INDEX IF EXISTS {RAW_SCHEMA}.idx_raw_tushare_top_list_reason_hash")
        op.execute(f"DROP INDEX IF EXISTS {RAW_SCHEMA}.idx_raw_tushare_top_list_trade_date")
        op.execute(f"ALTER TABLE {RAW_SCHEMA}.top_list DROP CONSTRAINT IF EXISTS pk_raw_tushare_top_list")
        op.execute(
            f"ALTER TABLE {RAW_SCHEMA}.top_list "
            "ADD CONSTRAINT top_list_pkey PRIMARY KEY (ts_code, trade_date, reason)"
        )
        op.execute(f"ALTER TABLE {RAW_SCHEMA}.top_list DROP COLUMN IF EXISTS payload_hash")
        op.execute(f"ALTER TABLE {RAW_SCHEMA}.top_list DROP COLUMN IF EXISTS reason_hash")


def _upgrade_raw_top_list(bind) -> None:  # type: ignore[no-untyped-def]
    op.execute(
        f"ALTER TABLE {RAW_SCHEMA}.top_list "
        "ADD COLUMN IF NOT EXISTS reason_hash VARCHAR(64)"
    )
    op.execute(
        f"ALTER TABLE {RAW_SCHEMA}.top_list "
        "ADD COLUMN IF NOT EXISTS payload_hash VARCHAR(64)"
    )
    _backfill_raw_hashes(bind)
    op.execute(
        f"ALTER TABLE {RAW_SCHEMA}.top_list "
        "ALTER COLUMN reason_hash SET NOT NULL"
    )
    op.execute(f"ALTER TABLE {RAW_SCHEMA}.top_list DROP CONSTRAINT IF EXISTS top_list_pkey")
    op.execute(f"ALTER TABLE {RAW_SCHEMA}.top_list DROP CONSTRAINT IF EXISTS pk_raw_tushare_top_list")
    op.execute(
        f"ALTER TABLE {RAW_SCHEMA}.top_list "
        "ADD CONSTRAINT pk_raw_tushare_top_list PRIMARY KEY (ts_code, trade_date, reason, payload_hash)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_raw_tushare_top_list_reason_hash "
        f"ON {RAW_SCHEMA}.top_list (ts_code, trade_date, reason_hash)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_raw_tushare_top_list_trade_date "
        f"ON {RAW_SCHEMA}.top_list (trade_date)"
    )


def _upgrade_serving_top_list(bind) -> None:  # type: ignore[no-untyped-def]
    op.execute(
        f"ALTER TABLE {SERVING_SCHEMA}.equity_top_list "
        "ADD COLUMN IF NOT EXISTS reason_hash VARCHAR(64)"
    )
    op.execute(
        f"ALTER TABLE {SERVING_SCHEMA}.equity_top_list "
        "ADD COLUMN IF NOT EXISTS selected_payload_hash VARCHAR(64)"
    )
    op.execute(
        f"ALTER TABLE {SERVING_SCHEMA}.equity_top_list "
        "ADD COLUMN IF NOT EXISTS variant_count INTEGER"
    )
    op.execute(
        f"ALTER TABLE {SERVING_SCHEMA}.equity_top_list "
        "ADD COLUMN IF NOT EXISTS resolution_policy_version VARCHAR(64)"
    )
    _backfill_serving_reason_hash_and_provenance(bind)
    op.execute(
        f"UPDATE {SERVING_SCHEMA}.equity_top_list "
        "SET variant_count = 1 "
        "WHERE variant_count IS NULL OR variant_count < 1"
    )
    op.execute(
        f"ALTER TABLE {SERVING_SCHEMA}.equity_top_list "
        "ALTER COLUMN reason_hash SET NOT NULL"
    )
    op.execute(
        f"ALTER TABLE {SERVING_SCHEMA}.equity_top_list "
        "ALTER COLUMN selected_payload_hash SET NOT NULL"
    )
    op.execute(
        f"ALTER TABLE {SERVING_SCHEMA}.equity_top_list "
        "ALTER COLUMN variant_count SET NOT NULL"
    )
    op.execute(
        f"ALTER TABLE {SERVING_SCHEMA}.equity_top_list "
        "ALTER COLUMN resolution_policy_version SET NOT NULL"
    )
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_equity_top_list_ts_code_trade_date_reason_hash "
        f"ON {SERVING_SCHEMA}.equity_top_list (ts_code, trade_date, reason_hash)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_equity_top_list_trade_date "
        f"ON {SERVING_SCHEMA}.equity_top_list (trade_date)"
    )


def _backfill_raw_hashes(bind) -> None:  # type: ignore[no-untyped-def]
    select_sql = sa.text(
        f"""
        SELECT
            ts_code,
            trade_date,
            reason,
            name,
            close,
            pct_change,
            turnover_rate,
            amount,
            l_sell,
            l_buy,
            l_amount,
            net_amount,
            net_rate,
            amount_rate,
            float_values
        FROM {RAW_SCHEMA}.top_list
        WHERE (reason_hash IS NULL OR payload_hash IS NULL)
          AND (
            :last_trade_date IS NULL
            OR (trade_date, ts_code, reason) > (:last_trade_date, :last_ts_code, :last_reason)
          )
        ORDER BY trade_date, ts_code, reason
        LIMIT :batch_size
        """
    )
    update_sql = sa.text(
        f"""
        UPDATE {RAW_SCHEMA}.top_list
        SET reason_hash = :reason_hash,
            payload_hash = :payload_hash
        WHERE ts_code = :ts_code
          AND trade_date = :trade_date
          AND reason = :reason
        """
    )
    last_trade_date = None
    last_ts_code = None
    last_reason = None
    while True:
        rows = bind.execute(
            select_sql,
            {
                "last_trade_date": last_trade_date,
                "last_ts_code": last_ts_code,
                "last_reason": last_reason,
                "batch_size": 2000,
            },
        ).fetchall()
        if not rows:
            break
        params = []
        for row in rows:
            mapping = dict(row._mapping)
            params.append(
                {
                    "ts_code": mapping["ts_code"],
                    "trade_date": mapping["trade_date"],
                    "reason": mapping["reason"],
                    "reason_hash": _hash_reason(mapping.get("reason")),
                    "payload_hash": _build_payload_hash(mapping),
                },
            )
        bind.execute(update_sql, params)
        last = dict(rows[-1]._mapping)
        last_trade_date = last["trade_date"]
        last_ts_code = last["ts_code"]
        last_reason = last["reason"]


def _backfill_serving_reason_hash_and_provenance(bind) -> None:  # type: ignore[no-untyped-def]
    select_sql = sa.text(
        f"""
        SELECT
            ts_code,
            trade_date,
            reason,
            reason_hash,
            name,
            close,
            pct_chg,
            turnover_rate,
            amount,
            l_sell,
            l_buy,
            l_amount,
            net_amount,
            net_rate,
            amount_rate,
            float_values
        FROM {SERVING_SCHEMA}.equity_top_list
        WHERE (
            :last_trade_date IS NULL
            OR (trade_date, ts_code, reason) > (:last_trade_date, :last_ts_code, :last_reason)
        )
        ORDER BY trade_date, ts_code, reason
        LIMIT :batch_size
        """
    )
    update_sql = sa.text(
        f"""
        UPDATE {SERVING_SCHEMA}.equity_top_list
        SET reason_hash = :reason_hash,
            selected_payload_hash = :selected_payload_hash,
            resolution_policy_version = :resolution_policy_version
        WHERE ts_code = :ts_code
          AND trade_date = :trade_date
          AND reason = :reason
        """
    )
    last_trade_date = None
    last_ts_code = None
    last_reason = None
    while True:
        rows = bind.execute(
            select_sql,
            {
                "last_trade_date": last_trade_date,
                "last_ts_code": last_ts_code,
                "last_reason": last_reason,
                "batch_size": 2000,
            },
        ).fetchall()
        if not rows:
            break
        params = []
        for row in rows:
            mapping = dict(row._mapping)
            params.append(
                {
                    "ts_code": mapping["ts_code"],
                    "trade_date": mapping["trade_date"],
                    "reason": mapping["reason"],
                    "reason_hash": _hash_reason(mapping.get("reason")),
                    "selected_payload_hash": _build_payload_hash(mapping),
                    "resolution_policy_version": POLICY_VERSION,
                },
            )
        bind.execute(update_sql, params)
        last = dict(rows[-1]._mapping)
        last_trade_date = last["trade_date"]
        last_ts_code = last["ts_code"]
        last_reason = last["reason"]

    op.execute("DROP TABLE IF EXISTS _tmp_top_list_variant_counts")
    op.execute(
        f"""
        CREATE TEMP TABLE _tmp_top_list_variant_counts AS
        SELECT
            ts_code,
            trade_date,
            reason_hash,
            COUNT(DISTINCT payload_hash)::INTEGER AS variant_count
        FROM {RAW_SCHEMA}.top_list
        GROUP BY ts_code, trade_date, reason_hash
        """
    )
    op.execute(
        f"""
        UPDATE {SERVING_SCHEMA}.equity_top_list AS target
        SET variant_count = counts.variant_count
        FROM _tmp_top_list_variant_counts AS counts
        WHERE target.ts_code = counts.ts_code
          AND target.trade_date = counts.trade_date
          AND target.reason_hash = counts.reason_hash
        """
    )
    op.execute("DROP TABLE IF EXISTS _tmp_top_list_variant_counts")


def _move_table_if_needed(bind, *, source_schema: str, target_schema: str, table_name: str) -> None:  # type: ignore[no-untyped-def]
    if _table_exists(bind, target_schema, table_name):
        return
    if not _table_exists(bind, source_schema, table_name):
        return
    op.execute(f"ALTER TABLE {source_schema}.{table_name} SET SCHEMA {target_schema}")


def _table_exists(bind, schema: str, table_name: str) -> bool:  # type: ignore[no-untyped-def]
    qualified_name = f"{schema}.{table_name}"
    return bind.execute(sa.text("SELECT to_regclass(:qualified_name)"), {"qualified_name": qualified_name}).scalar() is not None


def _hash_reason(reason: Any) -> str:
    normalized = _normalize_reason(reason)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_reason(reason: Any) -> str:
    text = unicodedata.normalize("NFKC", str(reason or ""))
    return WHITESPACE_RE.sub(" ", text.strip())


def _build_payload_hash(row: Mapping[str, Any]) -> str:
    payload = "\x1f".join(_payload_field_text(field_name, _field_value(row, field_name)) for field_name in TOP_LIST_PAYLOAD_FIELDS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _field_value(row: Mapping[str, Any], field_name: str) -> Any:
    if field_name in row:
        return row.get(field_name)
    if field_name == "pct_change" and "pct_chg" in row:
        return row.get("pct_chg")
    return None


def _payload_field_text(field_name: str, value: Any) -> str:
    normalized = _normalize_payload_value(field_name, value)
    if normalized is None:
        return "null"
    return normalized


def _normalize_payload_value(field_name: str, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value.is_nan():
            return None
        return _canonical_decimal_text(value)
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return _canonical_decimal_text(Decimal(str(value)))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, datetime):
        return value.date().isoformat() if field_name == "trade_date" else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    if text.strip().lower() in PSEUDO_NULL_TEXTS:
        return None
    if field_name in {"reason", "name"}:
        return text
    return text.strip()


def _canonical_decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text
