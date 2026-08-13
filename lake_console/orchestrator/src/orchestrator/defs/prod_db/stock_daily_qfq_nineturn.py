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
PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CHECK_NAME = (
    "prod_core_stock_daily_qfq_nineturn_partition_check"
)

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

PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CHECKPOINT_SELECT_SQL = f"""
SELECT
{_SELECT_COLUMNS_SQL}
FROM {PROD_CORE_STOCK_DAILY_QFQ_NINETURN_TABLE}
WHERE trade_date = ANY(%s::date[])
ORDER BY trade_date, ts_code
"""


@dataclass(frozen=True, slots=True)
class ProdCoreStockDailyQfqNineTurnSyncAudit:
    row_count: int
    observed_columns: tuple[str, ...]
    deleted_row_count: int | None
    inserted_row_count: int
    read_back_row_count: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class ProdCoreStockDailyQfqNineTurnReadAudit:
    passed: bool
    expected_row_count: int
    read_back_row_count: int
    expected_content_hash: str
    observed_content_hash: str
    failed_rule_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProdCoreStockDailyQfqNineTurnCheckpointAudit:
    passed: bool
    expected_partition_count: int
    observed_partition_count: int
    read_back_row_count: int
    failed_partition_keys: tuple[str, ...]


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


def audit_prod_core_stock_daily_qfq_nineturn_partition(
    *,
    connection,
    rows: Sequence[Mapping[str, object]],
    partition_key: str,
) -> ProdCoreStockDailyQfqNineTurnReadAudit:
    normalized_partition_key = normalize_iso_trade_date(partition_key)
    audit_timestamp = datetime(1970, 1, 1, tzinfo=timezone.utc)
    expected_rows = _normalize_gold_rows(
        rows=rows,
        partition_key=normalized_partition_key,
        published_at=audit_timestamp,
    )
    cursor = connection.cursor()
    try:
        cursor.execute(
            PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SELECT_SQL,
            (normalized_partition_key,),
        )
        observed_rows = _normalize_read_back_rows(
            cursor.fetchall(),
            partition_key=normalized_partition_key,
        )
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()
    expected_hash = _business_content_hash(expected_rows)
    observed_hash = _business_content_hash(observed_rows)
    failed_rules = []
    if len(observed_rows) != len(expected_rows):
        failed_rules.append("row_count")
    if _keys(observed_rows) != _keys(expected_rows):
        failed_rules.append("keys")
    if observed_hash != expected_hash:
        failed_rules.append("content")
    return ProdCoreStockDailyQfqNineTurnReadAudit(
        passed=not failed_rules,
        expected_row_count=len(expected_rows),
        read_back_row_count=len(observed_rows),
        expected_content_hash=expected_hash,
        observed_content_hash=observed_hash,
        failed_rule_names=tuple(failed_rules),
    )


def audit_prod_core_stock_daily_qfq_nineturn_checkpoint_partitions(
    *,
    connection,
    expected_content_hashes: Mapping[str, object],
    fetch_size: int = 1_000,
) -> ProdCoreStockDailyQfqNineTurnCheckpointAudit:
    if isinstance(fetch_size, bool) or not isinstance(fetch_size, int) or fetch_size <= 0:
        raise ValueError("Checkpoint fetch size must be a positive integer.")
    normalized_expected = {
        normalize_iso_trade_date(partition_key): str(content_hash).strip().lower()
        for partition_key, content_hash in expected_content_hashes.items()
    }
    if len(normalized_expected) != len(expected_content_hashes):
        raise ValueError("Checkpoint contains duplicate normalized partition keys.")
    if any(
        not re.fullmatch(r"[0-9a-f]{64}", content_hash)
        for content_hash in normalized_expected.values()
    ):
        raise ValueError("Checkpoint content hash must be lowercase SHA-256.")
    if not normalized_expected:
        return ProdCoreStockDailyQfqNineTurnCheckpointAudit(
            passed=True,
            expected_partition_count=0,
            observed_partition_count=0,
            read_back_row_count=0,
            failed_partition_keys=(),
        )
    cursor = connection.cursor(name="qfq_nineturn_checkpoint_audit")
    try:
        cursor.itersize = fetch_size
        cursor.execute(
            PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CHECKPOINT_SELECT_SQL,
            (sorted(normalized_expected),),
        )
        observed_hashes: dict[str, str] = {}
        read_back_row_count = 0
        current_partition_key: str | None = None
        current_rows: list[Sequence[object] | Mapping[str, object]] = []
        while rows := cursor.fetchmany(fetch_size):
            for row in rows:
                trade_date_value = (
                    row[1] if not isinstance(row, Mapping) else row["trade_date"]
                )
                partition_key = _normalize_trade_date(trade_date_value)
                if partition_key not in normalized_expected:
                    raise ValueError(
                        "Checkpoint read-back returned an unexpected partition."
                    )
                if (
                    current_partition_key is not None
                    and partition_key != current_partition_key
                ):
                    observed_hashes[current_partition_key] = _business_content_hash(
                        _normalize_read_back_rows(
                            current_rows,
                            partition_key=current_partition_key,
                        )
                    )
                    read_back_row_count += len(current_rows)
                    current_rows = []
                current_partition_key = partition_key
                current_rows.append(row)
        if current_partition_key is not None:
            observed_hashes[current_partition_key] = _business_content_hash(
                _normalize_read_back_rows(
                    current_rows,
                    partition_key=current_partition_key,
                )
            )
            read_back_row_count += len(current_rows)
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()
    failed_partition_keys = tuple(
        partition_key
        for partition_key, expected_hash in sorted(normalized_expected.items())
        if observed_hashes.get(partition_key) != expected_hash
    )
    return ProdCoreStockDailyQfqNineTurnCheckpointAudit(
        passed=not failed_partition_keys,
        expected_partition_count=len(normalized_expected),
        observed_partition_count=len(observed_hashes),
        read_back_row_count=read_back_row_count,
        failed_partition_keys=failed_partition_keys,
    )


def validate_prod_core_stock_daily_qfq_nineturn_sql_contract() -> None:
    combined_sql = (
        f"{PROD_CORE_STOCK_DAILY_QFQ_NINETURN_DELETE_SQL}\n"
        f"{PROD_CORE_STOCK_DAILY_QFQ_NINETURN_INSERT_SQL}\n"
        f"{PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SELECT_SQL}\n"
        f"{PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CHECKPOINT_SELECT_SQL}"
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
        "where trade_date = any(%s::date[])",
        "order by trade_date, ts_code",
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


def _business_content_hash(rows: Sequence[Mapping[str, object]]) -> str:
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
