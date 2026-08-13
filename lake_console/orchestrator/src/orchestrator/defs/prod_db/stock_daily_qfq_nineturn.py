"""Transactional publisher contract for stock daily QFQ nine-turn serving."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from psycopg2.extras import execute_values

from orchestrator.defs.run_contracts.configs import normalize_iso_trade_date
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_SIGNAL_THRESHOLD,
    QFQ_NINETURN_VERSION,
)

PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE = (
    "core_serving.equity_qfq_nineturn_daily"
)
PROD_CORE_STOCK_DAILY_QFQ_NINETURN_COLUMNS = (
    "ts_code",
    "trade_date",
    "close_qfq",
    "up_count",
    "down_count",
    "nine_up_turn",
    "nine_down_turn",
    "formula_version",
    "published_at",
)
PROD_CORE_STOCK_DAILY_QFQ_NINETURN_FORBIDDEN_COLUMNS = (
    "source",
    "created_at",
    "updated_at",
)
PROD_CORE_STOCK_DAILY_QFQ_NINETURN_BATCH_SIZE = 1_000

_SELECT_COLUMNS_SQL = """
  ts_code,
  trade_date,
  close_qfq,
  up_count,
  down_count,
  nine_up_turn,
  nine_down_turn,
  formula_version,
  published_at
"""

PROD_CORE_STOCK_DAILY_QFQ_NINETURN_DELETE_SQL = f"""
DELETE FROM {PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE}
WHERE trade_date = %s
"""

PROD_CORE_STOCK_DAILY_QFQ_NINETURN_INSERT_SQL = f"""
INSERT INTO {PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE} (
{_SELECT_COLUMNS_SQL}
) VALUES %s
"""

PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SELECT_SQL = f"""
SELECT
{_SELECT_COLUMNS_SQL}
FROM {PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE}
WHERE trade_date = %s
ORDER BY ts_code
"""


@dataclass(frozen=True, slots=True)
class ProdCoreStockDailyQfqNineTurnSyncAudit:
    row_count: int
    observed_columns: tuple[str, ...]
    deleted_row_count: int | None
    inserted_row_count: int
    read_back_row_count: int
    content_hash: str


def replace_prod_core_stock_daily_qfq_nineturn_partition(
    *,
    connection,
    rows: Sequence[Mapping[str, object]],
    partition_key: str,
    published_at: datetime | None = None,
) -> ProdCoreStockDailyQfqNineTurnSyncAudit:
    normalized_partition_key = normalize_iso_trade_date(partition_key)
    normalized_published_at = _normalize_published_at(
        published_at or datetime.now(timezone.utc)
    )
    normalized_rows = _normalize_gold_rows(
        rows=rows,
        partition_key=normalized_partition_key,
        published_at=normalized_published_at,
    )
    cursor = connection.cursor()
    try:
        cursor.execute(
            PROD_CORE_STOCK_DAILY_QFQ_NINETURN_DELETE_SQL,
            (normalized_partition_key,),
        )
        deleted_row_count = _rowcount_or_none(cursor)
        execute_values(
            cursor,
            PROD_CORE_STOCK_DAILY_QFQ_NINETURN_INSERT_SQL,
            [_insert_params(row) for row in normalized_rows],
            page_size=PROD_CORE_STOCK_DAILY_QFQ_NINETURN_BATCH_SIZE,
        )
        inserted_row_count = len(normalized_rows)
        cursor.execute(
            PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SELECT_SQL,
            (normalized_partition_key,),
        )
        read_back_rows = _normalize_read_back_rows(
            cursor.fetchall(),
            partition_key=normalized_partition_key,
        )
        expected_hash = _content_hash(normalized_rows)
        observed_hash = _content_hash(read_back_rows)
        if (
            len(read_back_rows) != len(normalized_rows)
            or _keys(normalized_rows) != _keys(read_back_rows)
            or expected_hash != observed_hash
        ):
            raise RuntimeError(
                "Prod stock daily QFQ nine-turn read-back audit failed: "
                "row count, keys, or content differs."
            )
        return ProdCoreStockDailyQfqNineTurnSyncAudit(
            row_count=len(normalized_rows),
            observed_columns=PROD_CORE_STOCK_DAILY_QFQ_NINETURN_COLUMNS,
            deleted_row_count=deleted_row_count,
            inserted_row_count=inserted_row_count,
            read_back_row_count=len(read_back_rows),
            content_hash=expected_hash,
        )
    except Exception:
        if hasattr(connection, "rollback"):
            connection.rollback()
        raise
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()


def validate_prod_core_stock_daily_qfq_nineturn_sql_contract() -> None:
    combined_sql = (
        f"{PROD_CORE_STOCK_DAILY_QFQ_NINETURN_DELETE_SQL}\n"
        f"{PROD_CORE_STOCK_DAILY_QFQ_NINETURN_INSERT_SQL}\n"
        f"{PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SELECT_SQL}"
    )
    normalized_sql = " ".join(combined_sql.lower().split())
    if "select *" in normalized_sql:
        raise RuntimeError("QFQ nine-turn serving SQL must use explicit projection.")
    for forbidden_column in PROD_CORE_STOCK_DAILY_QFQ_NINETURN_FORBIDDEN_COLUMNS:
        if re.search(rf"\b{re.escape(forbidden_column)}\b", normalized_sql):
            raise RuntimeError(
                "QFQ nine-turn serving SQL contains forbidden column "
                f"{forbidden_column}."
            )
    for required_column in PROD_CORE_STOCK_DAILY_QFQ_NINETURN_COLUMNS:
        if required_column not in normalized_sql:
            raise RuntimeError(
                f"QFQ nine-turn serving SQL is missing {required_column}."
            )
    for required_clause in (
        f"delete from {PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE}",
        f"insert into {PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE}",
        f"from {PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE}",
        "where trade_date = %s",
        "order by ts_code",
    ):
        if required_clause not in normalized_sql:
            raise RuntimeError(
                "QFQ nine-turn serving SQL is missing required clause: "
                f"{required_clause}."
            )


def _normalize_gold_rows(
    *,
    rows: Sequence[Mapping[str, object]],
    partition_key: str,
    published_at: datetime,
) -> tuple[dict[str, object], ...]:
    if not rows:
        raise ValueError("QFQ nine-turn serving sync requires a non-empty partition.")
    normalized = tuple(
        _normalize_gold_row(
            row=row,
            partition_key=partition_key,
            published_at=published_at,
        )
        for row in rows
    )
    if len(_keys(normalized)) != len(normalized):
        raise ValueError("QFQ nine-turn serving sync contains duplicate keys.")
    return tuple(sorted(normalized, key=lambda row: str(row["ts_code"])))


def _normalize_gold_row(
    *,
    row: Mapping[str, object],
    partition_key: str,
    published_at: datetime,
) -> dict[str, object]:
    required_gold_columns = PROD_CORE_STOCK_DAILY_QFQ_NINETURN_COLUMNS[:7]
    missing = [column for column in required_gold_columns if column not in row]
    if missing:
        raise ValueError(f"QFQ nine-turn serving row is missing columns: {missing}.")
    forbidden = [
        column
        for column in PROD_CORE_STOCK_DAILY_QFQ_NINETURN_FORBIDDEN_COLUMNS
        if column in row
    ]
    if forbidden:
        raise ValueError(
            f"QFQ nine-turn serving row contains forbidden columns: {forbidden}."
        )
    ts_code = str(row["ts_code"]).strip().upper()
    if not re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", ts_code):
        raise ValueError("QFQ nine-turn serving row has invalid ts_code.")
    trade_date = _normalize_trade_date(row["trade_date"])
    if trade_date != partition_key:
        raise ValueError(
            "QFQ nine-turn serving row trade_date does not match partition."
        )
    close_qfq = _normalize_close(row["close_qfq"])
    up_count = _normalize_count(row["up_count"], "up_count")
    down_count = _normalize_count(row["down_count"], "down_count")
    if up_count > 0 and down_count > 0:
        raise ValueError("QFQ nine-turn row cannot have both directions active.")
    nine_up_turn = _normalize_signal(row["nine_up_turn"], "+9")
    nine_down_turn = _normalize_signal(row["nine_down_turn"], "-9")
    if nine_up_turn is not None and up_count < QFQ_NINETURN_SIGNAL_THRESHOLD:
        raise ValueError("QFQ nine-turn +9 signal requires up_count >= 9.")
    if nine_down_turn is not None and down_count < QFQ_NINETURN_SIGNAL_THRESHOLD:
        raise ValueError("QFQ nine-turn -9 signal requires down_count >= 9.")
    if nine_up_turn is not None and nine_down_turn is not None:
        raise ValueError("QFQ nine-turn row cannot contain both signals.")
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "close_qfq": close_qfq,
        "up_count": up_count,
        "down_count": down_count,
        "nine_up_turn": nine_up_turn,
        "nine_down_turn": nine_down_turn,
        "formula_version": QFQ_NINETURN_VERSION,
        "published_at": published_at,
    }


def _normalize_read_back_rows(
    rows: Sequence[Sequence[object] | Mapping[str, object]],
    *,
    partition_key: str,
) -> tuple[dict[str, object], ...]:
    mapped_rows: list[Mapping[str, object]] = []
    for row in rows:
        if isinstance(row, Mapping):
            mapped_rows.append(row)
        else:
            mapped_rows.append(
                {
                    column: row[index]
                    for index, column in enumerate(
                        PROD_CORE_STOCK_DAILY_QFQ_NINETURN_COLUMNS
                    )
                }
            )
    normalized = []
    for row in mapped_rows:
        formula_version = int(row["formula_version"])
        if formula_version != QFQ_NINETURN_VERSION:
            raise ValueError("QFQ nine-turn read-back formula version mismatch.")
        normalized.append(
            _normalize_gold_row(
                row=row,
                partition_key=partition_key,
                published_at=_normalize_published_at(row["published_at"]),
            )
        )
    return tuple(sorted(normalized, key=lambda row: str(row["ts_code"])))


def _insert_params(row: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(row[column] for column in PROD_CORE_STOCK_DAILY_QFQ_NINETURN_COLUMNS)


def _keys(rows: Sequence[Mapping[str, object]]) -> set[tuple[str, str]]:
    return {
        (str(row["ts_code"]), str(row["trade_date"]))
        for row in rows
    }


def _content_hash(rows: Sequence[Mapping[str, object]]) -> str:
    payload = "\n".join(
        "\t".join(
            (
                str(row["ts_code"]),
                str(row["trade_date"]),
                format(float(row["close_qfq"]), ".17g"),
                str(row["up_count"]),
                str(row["down_count"]),
                str(row["nine_up_turn"] or ""),
                str(row["nine_down_turn"] or ""),
                str(row["formula_version"]),
                _normalize_published_at(row["published_at"]).isoformat(),
            )
        )
        for row in sorted(rows, key=lambda item: str(item["ts_code"]))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_trade_date(value: object) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return normalize_iso_trade_date(str(value))


def _normalize_published_at(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("QFQ nine-turn published_at must be a datetime.")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_close(value: object) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("QFQ nine-turn close_qfq must be numeric.") from error
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("QFQ nine-turn close_qfq must be finite and positive.")
    return normalized


def _normalize_count(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"QFQ nine-turn {field_name} must be a non-negative integer.")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"QFQ nine-turn {field_name} must be a non-negative integer."
        ) from error
    if normalized < 0 or normalized != value:
        raise ValueError(
            f"QFQ nine-turn {field_name} must be a non-negative integer."
        )
    return normalized


def _normalize_signal(value: object, allowed: str) -> str | None:
    if value is None:
        return None
    normalized = str(value)
    if normalized != allowed:
        raise ValueError(f"QFQ nine-turn signal must be {allowed} or null.")
    return normalized


def _rowcount_or_none(cursor: Any) -> int | None:
    rowcount = getattr(cursor, "rowcount", None)
    if isinstance(rowcount, int) and rowcount >= 0:
        return rowcount
    return None
