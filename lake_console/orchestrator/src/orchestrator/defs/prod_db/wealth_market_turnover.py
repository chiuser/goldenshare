"""Prod core serving write contract for wealth market turnover snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import re
from typing import Any

from psycopg2.extras import Json

from orchestrator.defs.run_contracts.configs import normalize_iso_trade_date
from orchestrator.defs.wealth_market_turnover_contract import (
    GOLD_WEALTH_MARKET_TURNOVER_COLUMNS,
    STK_MINS_FREQS,
    WEALTH_MARKET_TURNOVER_BUILD_STATUS,
    WEALTH_MARKET_TURNOVER_MARKET,
    WEALTH_MARKET_TURNOVER_TYPE,
)


PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE = (
    "core_serving.wealth_market_turnover_snapshot"
)
PROD_CORE_WEALTH_MARKET_TURNOVER_FORBIDDEN_COLUMNS = (
    "source",
    "created_at",
    "updated_at",
)
PROD_CORE_WEALTH_MARKET_TURNOVER_COLUMNS = GOLD_WEALTH_MARKET_TURNOVER_COLUMNS

_INSERT_COLUMNS_SQL = """
  type,
  market,
  trade_date,
  freq,
  build_status,
  latest_trade_time,
  total_amount,
  total_vol,
  security_count,
  source_row_count,
  points_json,
  build_version,
  built_at,
  build_note
"""

PROD_CORE_WEALTH_MARKET_TURNOVER_DELETE_SQL = f"""
DELETE FROM {PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE}
WHERE type = %s
  AND market = %s
  AND trade_date = %s
"""

PROD_CORE_WEALTH_MARKET_TURNOVER_INSERT_SQL = f"""
INSERT INTO {PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE} (
{_INSERT_COLUMNS_SQL}
) VALUES (
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
"""

PROD_CORE_WEALTH_MARKET_TURNOVER_SELECT_SQL = f"""
SELECT
{_INSERT_COLUMNS_SQL}
FROM {PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE}
WHERE type = %s
  AND market = %s
  AND trade_date = %s
ORDER BY freq
"""


@dataclass(frozen=True, slots=True)
class ProdCoreWealthMarketTurnoverSyncAudit:
    row_count: int
    observed_columns: tuple[str, ...]
    deleted_row_count: int | None
    inserted_row_count: int | None
    read_back_row_count: int
    points_json_hash: str


def replace_prod_core_wealth_market_turnover_partition(
    *,
    connection,
    rows: Sequence[Mapping[str, object]],
    partition_key: str,
) -> ProdCoreWealthMarketTurnoverSyncAudit:
    normalized_partition_key = normalize_iso_trade_date(partition_key)
    normalized_rows = _normalize_gold_rows(
        rows=rows,
        partition_key=normalized_partition_key,
    )
    cursor = connection.cursor()
    try:
        cursor.execute(
            PROD_CORE_WEALTH_MARKET_TURNOVER_DELETE_SQL,
            (
                WEALTH_MARKET_TURNOVER_TYPE,
                WEALTH_MARKET_TURNOVER_MARKET,
                normalized_partition_key,
            ),
        )
        deleted_row_count = _rowcount_or_none(cursor)
        cursor.executemany(
            PROD_CORE_WEALTH_MARKET_TURNOVER_INSERT_SQL,
            [_insert_params(row) for row in normalized_rows],
        )
        inserted_row_count = _rowcount_or_none(cursor)
        cursor.execute(
            PROD_CORE_WEALTH_MARKET_TURNOVER_SELECT_SQL,
            (
                WEALTH_MARKET_TURNOVER_TYPE,
                WEALTH_MARKET_TURNOVER_MARKET,
                normalized_partition_key,
            ),
        )
        read_back_rows = _normalize_read_back_rows(
            cursor.fetchall(),
            partition_key=normalized_partition_key,
        )
        if _rows_by_freq(normalized_rows) != _rows_by_freq(read_back_rows):
            raise RuntimeError(
                "Prod wealth_market_turnover read-back audit failed: "
                "inserted rows do not match selected rows."
            )
        points_json_hash = _points_json_hash(normalized_rows)
        return ProdCoreWealthMarketTurnoverSyncAudit(
            row_count=len(normalized_rows),
            observed_columns=PROD_CORE_WEALTH_MARKET_TURNOVER_COLUMNS,
            deleted_row_count=deleted_row_count,
            inserted_row_count=inserted_row_count,
            read_back_row_count=len(read_back_rows),
            points_json_hash=points_json_hash,
        )
    except Exception:
        if hasattr(connection, "rollback"):
            connection.rollback()
        raise
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()


def validate_prod_core_wealth_market_turnover_sql_contract() -> None:
    combined_sql = "\n".join(
        (
            PROD_CORE_WEALTH_MARKET_TURNOVER_DELETE_SQL,
            PROD_CORE_WEALTH_MARKET_TURNOVER_INSERT_SQL,
            PROD_CORE_WEALTH_MARKET_TURNOVER_SELECT_SQL,
        )
    )
    normalized_sql = " ".join(combined_sql.lower().split())
    if "select" + " *" in normalized_sql:
        raise RuntimeError(
            "Prod wealth_market_turnover SQL must not use wildcard projection."
        )
    for forbidden_column in PROD_CORE_WEALTH_MARKET_TURNOVER_FORBIDDEN_COLUMNS:
        if re.search(rf"\b{re.escape(forbidden_column)}\b", normalized_sql):
            raise RuntimeError(
                "Prod wealth_market_turnover SQL must not write or read "
                f"{forbidden_column}."
            )
    for required_column in PROD_CORE_WEALTH_MARKET_TURNOVER_COLUMNS:
        if required_column not in normalized_sql:
            raise RuntimeError(
                "Prod wealth_market_turnover SQL is missing required column "
                f"{required_column}."
            )
    for required_clause in (
        f"delete from {PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE}",
        f"insert into {PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE}",
        f"from {PROD_CORE_WEALTH_MARKET_TURNOVER_TABLE}",
        "where type = %s and market = %s and trade_date = %s",
        "order by freq",
    ):
        if required_clause not in normalized_sql:
            raise RuntimeError(
                "Prod wealth_market_turnover SQL is missing required clause: "
                f"{required_clause}."
            )


def _normalize_gold_rows(
    *,
    rows: Sequence[Mapping[str, object]],
    partition_key: str,
) -> tuple[dict[str, object], ...]:
    if len(rows) != len(STK_MINS_FREQS):
        raise ValueError("prod wealth_market_turnover sync requires exactly five rows.")
    normalized_rows = tuple(
        _normalize_gold_row(row=row, partition_key=partition_key) for row in rows
    )
    observed_freqs = tuple(sorted(int(row["freq"]) for row in normalized_rows))
    if observed_freqs != tuple(STK_MINS_FREQS):
        raise ValueError(
            "prod wealth_market_turnover sync requires freqs "
            f"{tuple(STK_MINS_FREQS)}; observed {observed_freqs}."
        )
    if len({int(row["freq"]) for row in normalized_rows}) != len(normalized_rows):
        raise ValueError("prod wealth_market_turnover sync rows contain duplicate freq.")
    return tuple(sorted(normalized_rows, key=lambda row: int(row["freq"])))


def _normalize_gold_row(
    *,
    row: Mapping[str, object],
    partition_key: str,
) -> dict[str, object]:
    missing_columns = [
        column for column in PROD_CORE_WEALTH_MARKET_TURNOVER_COLUMNS if column not in row
    ]
    if missing_columns:
        raise ValueError(
            "prod wealth_market_turnover sync row is missing columns: "
            f"{missing_columns}."
        )
    forbidden_columns = [
        column
        for column in PROD_CORE_WEALTH_MARKET_TURNOVER_FORBIDDEN_COLUMNS
        if column in row
    ]
    if forbidden_columns:
        raise ValueError(
            "prod wealth_market_turnover sync row contains forbidden columns: "
            f"{forbidden_columns}."
        )
    normalized_trade_date = _normalize_trade_date(row["trade_date"])
    if normalized_trade_date != partition_key:
        raise ValueError(
            "prod wealth_market_turnover sync row trade_date does not match "
            f"partition: {normalized_trade_date} != {partition_key}."
        )
    normalized_row = {
        "type": str(row["type"]),
        "market": str(row["market"]),
        "trade_date": normalized_trade_date,
        "freq": int(row["freq"]),
        "build_status": str(row["build_status"]),
        "latest_trade_time": _required_value(row["latest_trade_time"], "latest_trade_time"),
        "total_amount": _normalize_decimal(row["total_amount"]),
        "total_vol": int(_required_value(row["total_vol"], "total_vol")),
        "security_count": int(_required_value(row["security_count"], "security_count")),
        "source_row_count": int(_required_value(row["source_row_count"], "source_row_count")),
        "points_json": _normalize_points_json(row["points_json"]),
        "build_version": str(_required_value(row["build_version"], "build_version")),
        "built_at": _required_value(row["built_at"], "built_at"),
        "build_note": row["build_note"],
    }
    if normalized_row["type"] != WEALTH_MARKET_TURNOVER_TYPE:
        raise ValueError("prod wealth_market_turnover sync row has invalid type.")
    if normalized_row["market"] != WEALTH_MARKET_TURNOVER_MARKET:
        raise ValueError("prod wealth_market_turnover sync row has invalid market.")
    if normalized_row["build_status"] != WEALTH_MARKET_TURNOVER_BUILD_STATUS:
        raise ValueError("prod wealth_market_turnover sync row is not READY.")
    if normalized_row["freq"] not in set(STK_MINS_FREQS):
        raise ValueError("prod wealth_market_turnover sync row has invalid freq.")
    return normalized_row


def _normalize_read_back_rows(
    rows: Sequence[Sequence[object] | Mapping[str, object]],
    *,
    partition_key: str,
) -> tuple[dict[str, object], ...]:
    mapped_rows = []
    for row in rows:
        if isinstance(row, Mapping):
            mapped_rows.append(row)
            continue
        mapped_rows.append(
            {
                column: row[index]
                for index, column in enumerate(PROD_CORE_WEALTH_MARKET_TURNOVER_COLUMNS)
            }
        )
    return _normalize_gold_rows(rows=mapped_rows, partition_key=partition_key)


def _insert_params(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        row["type"],
        row["market"],
        row["trade_date"],
        row["freq"],
        row["build_status"],
        row["latest_trade_time"],
        row["total_amount"],
        row["total_vol"],
        row["security_count"],
        row["source_row_count"],
        Json(_json_value_for_postgres(row["points_json"])),
        row["build_version"],
        row["built_at"],
        row["build_note"],
    )


def _rows_by_freq(rows: Sequence[Mapping[str, object]]) -> dict[int, dict[str, object]]:
    return {int(row["freq"]): dict(row) for row in rows}


def _points_json_hash(rows: Sequence[Mapping[str, object]]) -> str:
    hash_input = "\n".join(
        f"{row['freq']}\t{_canonical_json_payload(row['points_json'])}"
        for row in sorted(rows, key=lambda row: int(row["freq"]))
    )
    return hashlib.md5(hash_input.encode("utf-8")).hexdigest()


def _normalize_points_json(value: object) -> object:
    if value is None:
        raise ValueError("prod wealth_market_turnover sync points_json must not be null.")
    points = json.loads(value) if isinstance(value, str) else value
    if not isinstance(points, list) or not points:
        raise ValueError(
            "prod wealth_market_turnover sync points_json must be a non-empty JSON array."
        )
    return points


def _canonical_json_payload(value: object) -> str:
    return json.dumps(
        _canonical_json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(value[key])
            for key in sorted(value)
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, Decimal):
        return _normalize_decimal_text(value)
    if isinstance(value, float):
        return _normalize_decimal_text(value)
    if isinstance(value, int):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _json_value_for_postgres(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_value_for_postgres(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_value_for_postgres(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _normalize_trade_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return normalize_iso_trade_date(str(value))


def _normalize_decimal(value: object) -> Decimal:
    if value is None:
        raise ValueError("prod wealth_market_turnover sync numeric value is null.")
    return Decimal(str(value))


def _normalize_decimal_text(value: object) -> str:
    return format(_normalize_decimal(value).normalize(), "f")


def _required_value(value: object, column_name: str) -> object:
    if value is None:
        raise ValueError(f"prod wealth_market_turnover sync {column_name} must not be null.")
    return value


def _rowcount_or_none(cursor) -> int | None:
    rowcount = getattr(cursor, "rowcount", None)
    if rowcount is None or rowcount < 0:
        return None
    return int(rowcount)
