"""Transactional publication contract for index daily nine-turn serving."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from psycopg2.extras import execute_values

from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_VERSION,
)

PROD_CORE_INDEX_DAILY_NINETURN_TABLE = "core_serving.index_nineturn_daily"
PROD_CORE_INDEX_DAILY_NINETURN_CHECK_NAME = (
    "prod_core_index_daily_nineturn_partition_check"
)
PROD_CORE_INDEX_DAILY_NINETURN_COLUMNS = (
    "ts_code",
    "trade_date",
    "close",
    "up_count",
    "down_count",
    "nine_up_turn",
    "nine_down_turn",
    "formula_version",
    "published_at",
)


@dataclass(frozen=True, slots=True)
class ProdCoreIndexDailyNineturnSyncAudit:
    row_count: int
    observed_columns: tuple[str, ...]
    deleted_row_count: int | None
    inserted_row_count: int
    read_back_row_count: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class ProdCoreIndexDailyNineturnReadAudit:
    passed: bool
    expected_row_count: int
    read_back_row_count: int
    expected_content_hash: str
    observed_content_hash: str
    failed_rule_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProdCoreIndexDailyNineturnCheckpointAudit:
    passed: bool
    expected_partition_count: int
    observed_partition_count: int
    read_back_row_count: int
    failed_partition_keys: tuple[str, ...]


def replace_prod_core_index_daily_nineturn_partition(
    *,
    connection,
    rows: Sequence[Mapping[str, object]],
    partition_key: str,
    published_at: datetime | None = None,
) -> ProdCoreIndexDailyNineturnSyncAudit:
    trade_date = _normalize_trade_date(partition_key)
    normalized = _normalize_rows(
        rows,
        partition_key=trade_date,
        published_at=published_at or datetime.now(UTC),
    )
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"DELETE FROM {PROD_CORE_INDEX_DAILY_NINETURN_TABLE} WHERE trade_date = %s",
            (trade_date,),
        )
        deleted = cursor.rowcount if cursor.rowcount >= 0 else None
        execute_values(
            cursor,
            f"""
            INSERT INTO {PROD_CORE_INDEX_DAILY_NINETURN_TABLE} (
              ts_code, trade_date, close, up_count, down_count,
              nine_up_turn, nine_down_turn, formula_version, published_at
            ) VALUES %s
            """,
            [
                tuple(row[column] for column in PROD_CORE_INDEX_DAILY_NINETURN_COLUMNS)
                for row in normalized
            ],
            page_size=100,
        )
        observed = _select_partition(cursor, trade_date)
        expected_hash = _business_hash(normalized)
        observed_hash = _business_hash(observed)
        if len(observed) != len(normalized) or expected_hash != observed_hash:
            raise RuntimeError(
                "Index nine-turn serving read-back differs from Gold rows."
            )
        return ProdCoreIndexDailyNineturnSyncAudit(
            row_count=len(normalized),
            observed_columns=PROD_CORE_INDEX_DAILY_NINETURN_COLUMNS,
            deleted_row_count=deleted,
            inserted_row_count=len(normalized),
            read_back_row_count=len(observed),
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


def audit_prod_core_index_daily_nineturn_partition(
    *,
    connection,
    rows: Sequence[Mapping[str, object]],
    partition_key: str,
) -> ProdCoreIndexDailyNineturnReadAudit:
    trade_date = _normalize_trade_date(partition_key)
    expected = _normalize_rows(
        rows,
        partition_key=trade_date,
        published_at=datetime(1970, 1, 1, tzinfo=UTC),
    )
    cursor = connection.cursor()
    try:
        observed = _select_partition(cursor, trade_date)
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()
    expected_hash = _business_hash(expected)
    observed_hash = _business_hash(observed)
    failures: list[str] = []
    if len(expected) != len(observed):
        failures.append("row_count")
    if tuple(row["ts_code"] for row in expected) != tuple(
        row["ts_code"] for row in observed
    ):
        failures.append("keys")
    if expected_hash != observed_hash:
        failures.append("content")
    return ProdCoreIndexDailyNineturnReadAudit(
        passed=not failures,
        expected_row_count=len(expected),
        read_back_row_count=len(observed),
        expected_content_hash=expected_hash,
        observed_content_hash=observed_hash,
        failed_rule_names=tuple(failures),
    )


def audit_prod_core_index_daily_nineturn_checkpoint_partitions(
    *,
    connection,
    expected_content_hashes: Mapping[str, object],
    fetch_size: int = 1_000,
) -> ProdCoreIndexDailyNineturnCheckpointAudit:
    """Stream and hash all checkpointed dates without loading the table at once."""

    if isinstance(fetch_size, bool) or not isinstance(fetch_size, int) or fetch_size <= 0:
        raise ValueError("Checkpoint fetch size must be a positive integer.")
    normalized_expected = {
        _normalize_trade_date(partition_key): str(content_hash).strip().lower()
        for partition_key, content_hash in expected_content_hashes.items()
    }
    if len(normalized_expected) != len(expected_content_hashes) or any(
        not re.fullmatch(r"[0-9a-f]{64}", content_hash)
        for content_hash in normalized_expected.values()
    ):
        raise ValueError("Checkpoint partition/hash contract is invalid.")
    if not normalized_expected:
        return ProdCoreIndexDailyNineturnCheckpointAudit(True, 0, 0, 0, ())
    cursor = connection.cursor(name="index_nineturn_checkpoint_audit")
    observed_hashes: dict[date, str] = {}
    read_back_row_count = 0
    current_date: date | None = None
    current_rows: list[dict[str, object]] = []
    try:
        cursor.itersize = fetch_size
        cursor.execute(
            f"""
            SELECT ts_code, trade_date, close, up_count, down_count,
                   nine_up_turn, nine_down_turn, formula_version, published_at
            FROM {PROD_CORE_INDEX_DAILY_NINETURN_TABLE}
            WHERE trade_date = ANY(%s::date[])
            ORDER BY trade_date, ts_code
            """,
            (sorted(normalized_expected),),
        )
        while rows := cursor.fetchmany(fetch_size):
            for row in rows:
                normalized_row = dict(
                    zip(PROD_CORE_INDEX_DAILY_NINETURN_COLUMNS, row, strict=True)
                )
                row_date = _normalize_trade_date(normalized_row["trade_date"])
                if current_date is not None and row_date != current_date:
                    observed_hashes[current_date] = _business_hash(current_rows)
                    read_back_row_count += len(current_rows)
                    current_rows = []
                current_date = row_date
                current_rows.append(normalized_row)
        if current_date is not None:
            observed_hashes[current_date] = _business_hash(current_rows)
            read_back_row_count += len(current_rows)
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()
    failed = tuple(
        partition_key.isoformat()
        for partition_key, expected_hash in sorted(normalized_expected.items())
        if observed_hashes.get(partition_key) != expected_hash
    )
    return ProdCoreIndexDailyNineturnCheckpointAudit(
        passed=not failed,
        expected_partition_count=len(normalized_expected),
        observed_partition_count=len(observed_hashes),
        read_back_row_count=read_back_row_count,
        failed_partition_keys=failed,
    )


def _normalize_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    partition_key: date,
    published_at: datetime,
) -> tuple[dict[str, object], ...]:
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        code = str(row["ts_code"]).strip().upper()
        row_date = _normalize_trade_date(row["trade_date"])
        if row_date != partition_key or not code or code in seen:
            raise ValueError(
                "Index nine-turn serving rows violate partition/key contract."
            )
        seen.add(code)
        close = float(row["close"])
        up_count = _normalize_count(row["up_count"], "up_count")
        down_count = _normalize_count(row["down_count"], "down_count")
        nine_up_turn = row.get("nine_up_turn")
        nine_down_turn = row.get("nine_down_turn")
        if not math.isfinite(close) or close <= 0:
            raise ValueError("Index nine-turn serving close violates value contract.")
        if up_count > 0 and down_count > 0:
            raise ValueError("Index nine-turn serving row violates value contract.")
        if nine_up_turn not in {None, "+9"} or nine_down_turn not in {None, "-9"}:
            raise ValueError("Index nine-turn serving signal violates value contract.")
        if (nine_up_turn is not None and up_count < 9) or (
            nine_down_turn is not None and down_count < 9
        ):
            raise ValueError("Index nine-turn serving signal/count contract failed.")
        if nine_up_turn is not None and nine_down_turn is not None:
            raise ValueError("Index nine-turn serving row has two signals.")
        normalized.append(
            {
                "ts_code": code,
                "trade_date": row_date,
                "close": close,
                "up_count": up_count,
                "down_count": down_count,
                "nine_up_turn": nine_up_turn,
                "nine_down_turn": nine_down_turn,
                "formula_version": MAJOR_INDEX_NINETURN_VERSION,
                "published_at": published_at,
            }
        )
    if not normalized:
        raise ValueError("Index nine-turn serving partition cannot be empty.")
    return tuple(sorted(normalized, key=lambda row: str(row["ts_code"])))


def _select_partition(cursor, trade_date: date) -> tuple[dict[str, object], ...]:
    cursor.execute(
        f"""
        SELECT ts_code, trade_date, close, up_count, down_count,
               nine_up_turn, nine_down_turn, formula_version, published_at
        FROM {PROD_CORE_INDEX_DAILY_NINETURN_TABLE}
        WHERE trade_date = %s
        ORDER BY ts_code
        """,
        (trade_date,),
    )
    return tuple(
        dict(zip(PROD_CORE_INDEX_DAILY_NINETURN_COLUMNS, row, strict=True))
        for row in cursor.fetchall()
    )


def _business_hash(rows: Sequence[Mapping[str, object]]) -> str:
    payload = [
        {
            key: (value.isoformat() if isinstance(value, (date, datetime)) else value)
            for key, value in row.items()
            if key != "published_at"
        }
        for row in rows
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _normalize_trade_date(value: object) -> date:
    if isinstance(value, datetime):
        raise TypeError("trade_date must not include time.")
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


def _normalize_count(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be a non-negative integer.")
    normalized = int(value)
    if normalized < 0 or float(value) != normalized:
        raise ValueError(f"{field_name} must be a non-negative integer.")
    return normalized


__all__ = [
    "PROD_CORE_INDEX_DAILY_NINETURN_CHECK_NAME",
    "PROD_CORE_INDEX_DAILY_NINETURN_COLUMNS",
    "PROD_CORE_INDEX_DAILY_NINETURN_TABLE",
    "ProdCoreIndexDailyNineturnCheckpointAudit",
    "ProdCoreIndexDailyNineturnReadAudit",
    "ProdCoreIndexDailyNineturnSyncAudit",
    "audit_prod_core_index_daily_nineturn_checkpoint_partitions",
    "audit_prod_core_index_daily_nineturn_partition",
    "replace_prod_core_index_daily_nineturn_partition",
]
