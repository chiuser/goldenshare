"""Read-only Prod DB contracts for index minute source coverage."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any

from orchestrator.defs.resources import ProdPostgresResource
from orchestrator.defs.run_contracts.configs import normalize_iso_trade_date
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_ACTIVE_POOL_FETCH_SIZE,
    INDEX_MINS_ACTIVE_POOL_MAX_CODES,
    INDEX_MINS_ACTIVE_POOL_RESOURCE,
    INDEX_MINS_SOURCE_COLUMNS,
    INDEX_MINS_SOURCE_FREQS,
    index_mins_code_set_hash,
    index_mins_trade_date_window,
    normalize_index_mins_codes,
    normalize_index_mins_datetime,
    normalize_index_mins_source_freq,
)


PROD_INDEX_MINS_SOURCE_TABLE = "raw_tushare.index_mins"
PROD_INDEX_MINS_ACTIVE_TABLE = "ops.index_series_active"
PROD_INDEX_MINS_DUCKDB_ATTACHED_DATABASE = "prod_index_mins_db"
PROD_INDEX_MINS_DUCKDB_ATTACH_OPTIONS = "TYPE POSTGRES, READ_ONLY"

PROD_INDEX_MINS_ACTIVE_POOL_QUERY = """
SELECT ts_code
FROM ops.index_series_active
WHERE resource = %s
ORDER BY ts_code
"""

PROD_INDEX_MINS_RANGE_QUERY = """
SELECT
  ts_code,
  freq,
  trade_time,
  open,
  close,
  high,
  low,
  vol,
  amount,
  exchange,
  vwap
FROM raw_tushare.index_mins
WHERE freq = %s
  AND trade_time >= %s::timestamp
  AND trade_time < %s::timestamp
  AND ts_code = ANY(%s::text[])
ORDER BY ts_code, trade_time
"""

PROD_INDEX_MINS_SOURCE_PROBE_QUERY = """
SELECT
  COUNT(*) AS source_row_count,
  COUNT(DISTINCT ts_code) AS returned_code_count,
  COUNT(DISTINCT (ts_code, trade_time)) AS distinct_key_count,
  MIN(trade_time) AS min_trade_time,
  MAX(trade_time) AS max_trade_time
FROM raw_tushare.index_mins
WHERE freq = %s
  AND trade_time >= %s::timestamp
  AND trade_time < %s::timestamp
  AND ts_code = ANY(%s::text[])
"""

_SOURCE_QUERY_EXPECTED_COLUMNS = tuple(INDEX_MINS_SOURCE_COLUMNS)


@dataclass(frozen=True, slots=True)
class IndexMinsActivePool:
    codes: tuple[str, ...]
    code_set_hash: str

    @property
    def code_count(self) -> int:
        return len(self.codes)


@dataclass(frozen=True, slots=True)
class ProdIndexMinsFrequencyReadiness:
    source_freq: str
    expected_code_count: int
    returned_code_count: int
    source_row_count: int
    distinct_key_count: int
    min_trade_time: datetime | None
    max_trade_time: datetime | None

    @property
    def duplicate_key_count(self) -> int:
        return max(self.source_row_count - self.distinct_key_count, 0)

    def ready_for_window(self, *, start_datetime: datetime, end_datetime: datetime) -> bool:
        return (
            self.expected_code_count > 0
            and self.source_row_count > 0
            and self.returned_code_count == self.expected_code_count
            and self.distinct_key_count == self.source_row_count
            and self.min_trade_time is not None
            and self.max_trade_time is not None
            and start_datetime <= self.min_trade_time < end_datetime
            and start_datetime <= self.max_trade_time < end_datetime
        )


@dataclass(frozen=True, slots=True)
class ProdIndexMinsSourceReadiness:
    trade_date: str
    expected_code_count: int
    expected_code_set_hash: str | None
    frequency_coverages: tuple[ProdIndexMinsFrequencyReadiness, ...]
    elapsed_ms: int
    scan_error_code: str | None = None
    scan_error: str | None = None

    @property
    def ready(self) -> bool:
        if self.scan_error is not None:
            return False
        if tuple(item.source_freq for item in self.frequency_coverages) != INDEX_MINS_SOURCE_FREQS:
            return False
        start_datetime, end_datetime = index_mins_trade_date_window(self.trade_date)
        return all(
            item.ready_for_window(
                start_datetime=start_datetime,
                end_datetime=end_datetime,
            )
            for item in self.frequency_coverages
        )

    @property
    def reason_code(self) -> str:
        if self.ready:
            return "prod_index_mins_source_ready"
        if self.scan_error is not None:
            return "prod_index_mins_source_query_error"
        for coverage in self.frequency_coverages:
            if coverage.source_row_count <= 0:
                return "prod_index_mins_source_empty"
            if coverage.duplicate_key_count > 0:
                return "prod_index_mins_source_duplicate_key"
            if coverage.returned_code_count != coverage.expected_code_count:
                return "prod_index_mins_source_code_coverage_incomplete"
        return "prod_index_mins_source_date_window_invalid"

    def to_metadata(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "ready": self.ready,
            "reason_code": self.reason_code,
            "expected_code_count": self.expected_code_count,
            "expected_code_set_hash": self.expected_code_set_hash,
            "frequency_coverages": [
                {
                    "source_freq": item.source_freq,
                    "expected_code_count": item.expected_code_count,
                    "returned_code_count": item.returned_code_count,
                    "source_row_count": item.source_row_count,
                    "distinct_key_count": item.distinct_key_count,
                    "duplicate_key_count": item.duplicate_key_count,
                    "min_trade_time": _datetime_text(item.min_trade_time),
                    "max_trade_time": _datetime_text(item.max_trade_time),
                }
                for item in self.frequency_coverages
            ],
            "elapsed_ms": self.elapsed_ms,
            "scan_error_code": self.scan_error_code,
        }


def load_prod_index_mins_active_pool(
    *,
    prod_postgres: ProdPostgresResource,
    max_codes: int = INDEX_MINS_ACTIVE_POOL_MAX_CODES,
) -> IndexMinsActivePool:
    """Load and validate the bounded index_mins active code contract."""

    if max_codes <= 0:
        raise ValueError("max_codes must be positive.")
    codes: list[str] = []
    with prod_postgres.connect_readonly_transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                PROD_INDEX_MINS_ACTIVE_POOL_QUERY,
                (INDEX_MINS_ACTIVE_POOL_RESOURCE,),
            )
            while True:
                rows = cursor.fetchmany(INDEX_MINS_ACTIVE_POOL_FETCH_SIZE)
                if not rows:
                    break
                codes.extend(_code_from_row(row) for row in rows)
                if len(codes) > max_codes:
                    raise ValueError(
                        "index_mins active pool exceeds bounded code limit: "
                        f"max={max_codes}."
                    )
    normalized_codes = normalize_index_mins_codes(codes, reject_duplicates=True)
    return IndexMinsActivePool(
        codes=normalized_codes,
        code_set_hash=index_mins_code_set_hash(normalized_codes),
    )


def build_prod_index_mins_range_query(
    *,
    source_freq: str,
    start_datetime: object,
    end_datetime: object,
    effective_codes: Sequence[object],
) -> tuple[str, tuple[object, ...]]:
    """Build the parameterized, explicit-column Prod range query."""

    normalized_freq = normalize_index_mins_source_freq(source_freq)
    normalized_start = normalize_index_mins_datetime(
        start_datetime,
        field_name="start_datetime",
    )
    normalized_end = normalize_index_mins_datetime(
        end_datetime,
        field_name="end_datetime",
    )
    if normalized_end <= normalized_start:
        raise ValueError("end_datetime must be later than start_datetime.")
    normalized_codes = normalize_index_mins_codes(effective_codes)
    return PROD_INDEX_MINS_RANGE_QUERY, (
        normalized_freq,
        normalized_start,
        normalized_end,
        list(normalized_codes),
    )


def build_prod_index_mins_duckdb_source_sql(
    *,
    source_freq: str,
    start_datetime: object,
    end_datetime: object,
    effective_codes: Sequence[object],
) -> str:
    """Build the set-based query used against an attached read-only Postgres DB."""

    normalized_freq = normalize_index_mins_source_freq(source_freq)
    normalized_start = normalize_index_mins_datetime(
        start_datetime,
        field_name="start_datetime",
    )
    normalized_end = normalize_index_mins_datetime(
        end_datetime,
        field_name="end_datetime",
    )
    if normalized_end <= normalized_start:
        raise ValueError("end_datetime must be later than start_datetime.")
    normalized_codes = normalize_index_mins_codes(effective_codes)
    code_sql = ", ".join(_sql_literal(code) for code in normalized_codes)
    columns_sql = ",\n  ".join(INDEX_MINS_SOURCE_COLUMNS)
    return f"""
SELECT
  {columns_sql}
FROM {PROD_INDEX_MINS_DUCKDB_ATTACHED_DATABASE}.raw_tushare.index_mins
WHERE freq = {_sql_literal(normalized_freq)}
  AND trade_time >= TIMESTAMP {_sql_literal(normalized_start.isoformat(sep=' '))}
  AND trade_time < TIMESTAMP {_sql_literal(normalized_end.isoformat(sep=' '))}
  AND CAST(ts_code AS VARCHAR) IN ({code_sql})
ORDER BY ts_code, trade_time
"""


def validate_prod_index_mins_query_contract() -> None:
    normalized_sql = " ".join(PROD_INDEX_MINS_RANGE_QUERY.lower().split())
    if "select *" in normalized_sql:
        raise RuntimeError("Prod index_mins query must not use SELECT *.")
    if "from raw_tushare.index_mins" not in normalized_sql:
        raise RuntimeError("Prod index_mins query must use the approved source table.")
    for column in _SOURCE_QUERY_EXPECTED_COLUMNS:
        if column not in normalized_sql:
            raise RuntimeError(f"Prod index_mins query is missing column {column}.")
    for clause in (
        "where freq =",
        "trade_time >=",
        "trade_time <",
        "ts_code = any(",
        "order by ts_code, trade_time",
    ):
        if clause not in normalized_sql:
            raise RuntimeError(f"Prod index_mins query is missing clause {clause}.")


def probe_prod_index_mins_source(
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    effective_codes: Sequence[object],
    source_freqs: Sequence[object] = INDEX_MINS_SOURCE_FREQS,
) -> ProdIndexMinsSourceReadiness:
    """Probe five frequency aggregates through one read-only Prod connection."""

    started_at = perf_counter()
    normalized_codes = normalize_index_mins_codes(effective_codes)
    normalized_freqs = _normalize_source_freqs(source_freqs)
    normalized_trade_date = normalize_iso_trade_date(
        trade_date,
        field_name="trade_date",
    )
    start_datetime, end_datetime = index_mins_trade_date_window(normalized_trade_date)
    try:
        validate_prod_index_mins_query_contract()
        coverages: list[ProdIndexMinsFrequencyReadiness] = []
        with prod_postgres.connect_readonly_transaction() as connection:
            with connection.cursor() as cursor:
                for source_freq in normalized_freqs:
                    cursor.execute(
                        PROD_INDEX_MINS_SOURCE_PROBE_QUERY,
                        (
                            source_freq,
                            start_datetime,
                            end_datetime,
                            list(normalized_codes),
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeError(
                            f"source probe returned no aggregate row for freq={source_freq}."
                        )
                    source_row_count = int(_row_value(row, "source_row_count", 0) or 0)
                    returned_code_count = int(
                        _row_value(row, "returned_code_count", 1) or 0
                    )
                    distinct_key_count = int(
                        _row_value(row, "distinct_key_count", 2) or 0
                    )
                    coverages.append(
                        ProdIndexMinsFrequencyReadiness(
                            source_freq=source_freq,
                            expected_code_count=len(normalized_codes),
                            returned_code_count=returned_code_count,
                            source_row_count=source_row_count,
                            distinct_key_count=distinct_key_count,
                            min_trade_time=_coerce_datetime(
                                _row_value(row, "min_trade_time", 3)
                            ),
                            max_trade_time=_coerce_datetime(
                                _row_value(row, "max_trade_time", 4)
                            ),
                        )
                    )
        return ProdIndexMinsSourceReadiness(
            trade_date=normalized_trade_date,
            expected_code_count=len(normalized_codes),
            expected_code_set_hash=index_mins_code_set_hash(normalized_codes),
            frequency_coverages=tuple(coverages),
            elapsed_ms=_elapsed_ms(started_at),
        )
    except Exception as error:  # noqa: BLE001 - source probe must fail closed.
        return ProdIndexMinsSourceReadiness(
            trade_date=normalized_trade_date,
            expected_code_count=len(normalized_codes),
            expected_code_set_hash=index_mins_code_set_hash(normalized_codes),
            frequency_coverages=(),
            elapsed_ms=_elapsed_ms(started_at),
            scan_error_code=type(error).__name__,
            scan_error=str(error),
        )


def _normalize_source_freqs(values: Sequence[object]) -> tuple[str, ...]:
    normalized = tuple(normalize_index_mins_source_freq(value) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("index_mins source frequencies must not be duplicated.")
    if set(normalized) != set(INDEX_MINS_SOURCE_FREQS):
        raise ValueError("index_mins source probe must cover all five frequencies.")
    return tuple(freq for freq in INDEX_MINS_SOURCE_FREQS if freq in normalized)


def _sql_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _code_from_row(row: object) -> object:
    if isinstance(row, Mapping):
        return row.get("ts_code")
    return row[0]  # type: ignore[index]


def _row_value(row: object, key: str, position: int) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return row[position]  # type: ignore[index]


def _coerce_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return normalize_index_mins_datetime(value, field_name="source timestamp")


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat(sep=" ") if value is not None else None


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)
