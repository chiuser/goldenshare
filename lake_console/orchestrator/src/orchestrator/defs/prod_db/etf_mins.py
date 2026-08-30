"""Read-only Prod Raw SQL and bounded code coverage for ETF minutes."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.resources import ProdPostgresResource
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
    ETF_MINS_SENSOR_WINDOW_LIMIT,
    ETF_MINS_SOURCE_COLUMNS,
    ETF_MINS_SOURCE_FREQS,
    EtfMinsRequestableTarget,
    normalize_etf_mins_requestable_targets,
    normalize_etf_mins_source_freq,
    normalize_etf_mins_trade_date,
)

PROD_ETF_MINS_SOURCE_TABLE = "raw_tushare.etf_minute_bar"
PROD_ETF_MINS_DUCKDB_ATTACHED_DATABASE = "prod_raw_pg"
PROD_ETF_MINS_DUCKDB_ATTACH_OPTIONS = "TYPE POSTGRES, READ_ONLY"

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_POSTGRES_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_POSTGRES_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


@dataclass(frozen=True, slots=True)
class ProdEtfMinsFrequencyCoverage:
    trade_date: str
    source_freq: str
    expected_code_count: int
    present_code_count: int
    missing_code_count: int
    missing_code_samples: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return (
            self.expected_code_count > 0
            and self.present_code_count == self.expected_code_count
            and self.missing_code_count == 0
        )


@dataclass(frozen=True, slots=True)
class ProdEtfMinsCodeCoverageProbe:
    ready: bool
    reason_code: str
    frequency_coverages: tuple[ProdEtfMinsFrequencyCoverage, ...]
    first_incomplete_trade_date: str | None
    first_incomplete_source_freq: str | None
    elapsed_ms: int
    error_type: str | None = None

    def coverage_by_key(self) -> dict[tuple[str, str], ProdEtfMinsFrequencyCoverage]:
        return {
            (coverage.trade_date, coverage.source_freq): coverage
            for coverage in self.frequency_coverages
        }


PROD_ETF_MINS_SELECT_TEMPLATE = """
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
  vwap,
  exchange
FROM raw_tushare.etf_minute_bar
WHERE freq = {source_freq}
  AND trade_time >= TIMESTAMP {start_datetime}
  AND trade_time < TIMESTAMP {end_datetime}
ORDER BY ts_code, trade_time
"""


PROD_ETF_MINS_COVERAGE_SQL = """
WITH requested_dates AS (
  SELECT trade_date
  FROM unnest(%s::date[]) AS source(trade_date)
),
requested_targets AS (
  SELECT ts_code, list_date
  FROM unnest(%s::text[], %s::date[]) AS source(ts_code, list_date)
),
requested_freqs AS (
  SELECT freq, freq_order
  FROM unnest(%s::text[]) WITH ORDINALITY AS source(freq, freq_order)
),
date_freqs AS (
  SELECT dates.trade_date, freqs.freq, freqs.freq_order
  FROM requested_dates AS dates
  CROSS JOIN requested_freqs AS freqs
),
expected_pairs AS (
  SELECT
    date_freqs.trade_date,
    date_freqs.freq,
    date_freqs.freq_order,
    targets.ts_code
  FROM date_freqs
  JOIN requested_targets AS targets
    ON targets.list_date <= date_freqs.trade_date
),
coverage AS MATERIALIZED (
  SELECT
    expected.trade_date,
    expected.freq,
    expected.freq_order,
    expected.ts_code,
    EXISTS (
      SELECT 1
      FROM raw_tushare.etf_minute_bar AS source
      WHERE source.ts_code = expected.ts_code
        AND source.freq = expected.freq
        AND source.trade_time >= expected.trade_date::timestamp
        AND source.trade_time < (expected.trade_date + 1)::timestamp
      LIMIT 1
    ) AS present
  FROM expected_pairs AS expected
),
coverage_counts AS (
  SELECT
    trade_date,
    freq,
    freq_order,
    count(*) AS expected_code_count,
    count(*) FILTER (WHERE present) AS present_code_count,
    count(*) FILTER (WHERE NOT present) AS missing_code_count
  FROM coverage
  GROUP BY trade_date, freq, freq_order
),
missing_ranked AS (
  SELECT
    trade_date,
    freq,
    ts_code,
    row_number() OVER (
      PARTITION BY trade_date, freq ORDER BY ts_code
    ) AS sample_rank
  FROM coverage
  WHERE NOT present
)
SELECT
  date_freqs.trade_date,
  date_freqs.freq,
  COALESCE(counts.expected_code_count, 0) AS expected_code_count,
  COALESCE(counts.present_code_count, 0) AS present_code_count,
  COALESCE(counts.missing_code_count, 0) AS missing_code_count,
  COALESCE(
    (
      SELECT array_agg(sample.ts_code ORDER BY sample.ts_code)
      FROM missing_ranked AS sample
      WHERE sample.trade_date = date_freqs.trade_date
        AND sample.freq = date_freqs.freq
        AND sample.sample_rank <= %s
    ),
    ARRAY[]::text[]
  ) AS missing_code_samples
FROM date_freqs
LEFT JOIN coverage_counts AS counts
  ON counts.trade_date = date_freqs.trade_date
  AND counts.freq = date_freqs.freq
ORDER BY date_freqs.trade_date, date_freqs.freq_order
"""


def build_prod_etf_mins_remote_query(
    *,
    source_freq: str,
    start_datetime: str,
    end_datetime: str,
) -> str:
    normalized_freq = normalize_etf_mins_source_freq(source_freq)
    normalized_start = _normalize_postgres_timestamp(start_datetime)
    normalized_end = _normalize_postgres_timestamp(end_datetime)
    if normalized_end <= normalized_start:
        raise ValueError("ETF minute end_datetime must be after start_datetime.")
    return PROD_ETF_MINS_SELECT_TEMPLATE.format(
        source_freq=_postgres_literal(normalized_freq),
        start_datetime=_postgres_literal(normalized_start),
        end_datetime=_postgres_literal(normalized_end),
    )


def build_prod_etf_mins_duckdb_source_sql(
    *,
    source_freq: str,
    start_datetime: str,
    end_datetime: str,
    attached_database: str = PROD_ETF_MINS_DUCKDB_ATTACHED_DATABASE,
) -> str:
    normalized_database = _normalize_sql_identifier(
        attached_database,
        field_name="attached_database",
    )
    remote_query = build_prod_etf_mins_remote_query(
        source_freq=source_freq,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
    )
    return (
        "SELECT "
        + ", ".join(ETF_MINS_SOURCE_COLUMNS)
        + " FROM postgres_query("
        + duckdb_string(normalized_database)
        + ", "
        + duckdb_string(remote_query)
        + ")"
    )


def build_prod_etf_mins_duckdb_attach_sql(
    *,
    conninfo: str,
    attached_database: str = PROD_ETF_MINS_DUCKDB_ATTACHED_DATABASE,
) -> str:
    normalized_conninfo = str(conninfo).strip()
    if not normalized_conninfo:
        raise ValueError("Prod Postgres conninfo must not be empty.")
    normalized_database = _normalize_sql_identifier(
        attached_database,
        field_name="attached_database",
    )
    return (
        "ATTACH "
        + duckdb_string(normalized_conninfo)
        + f" AS {normalized_database} ({PROD_ETF_MINS_DUCKDB_ATTACH_OPTIONS})"
    )


def probe_prod_etf_mins_code_coverage(
    *,
    prod_postgres: ProdPostgresResource,
    trade_dates: Iterable[str],
    requestable_targets: Iterable[
        EtfMinsRequestableTarget | Mapping[str, object]
    ],
) -> ProdEtfMinsCodeCoverageProbe:
    """Run one fail-closed coverage query for one to ten trade dates."""

    started = perf_counter()
    try:
        frequency_coverages = load_prod_etf_mins_code_coverage(
            prod_postgres=prod_postgres,
            trade_dates=trade_dates,
            requestable_targets=requestable_targets,
        )
    except Exception as error:  # noqa: BLE001
        return ProdEtfMinsCodeCoverageProbe(
            ready=False,
            reason_code="prod_etf_mins_source_query_error",
            frequency_coverages=(),
            first_incomplete_trade_date=None,
            first_incomplete_source_freq=None,
            elapsed_ms=int((perf_counter() - started) * 1000),
            error_type=type(error).__name__,
        )

    first_incomplete = next(
        (coverage for coverage in frequency_coverages if not coverage.ready),
        None,
    )
    return ProdEtfMinsCodeCoverageProbe(
        ready=first_incomplete is None,
        reason_code=(
            "prod_etf_mins_code_coverage_ready"
            if first_incomplete is None
            else "prod_etf_mins_code_coverage_incomplete"
        ),
        frequency_coverages=frequency_coverages,
        first_incomplete_trade_date=(
            None if first_incomplete is None else first_incomplete.trade_date
        ),
        first_incomplete_source_freq=(
            None if first_incomplete is None else first_incomplete.source_freq
        ),
        elapsed_ms=int((perf_counter() - started) * 1000),
    )


def load_prod_etf_mins_code_coverage(
    *,
    prod_postgres: ProdPostgresResource,
    trade_dates: Iterable[str],
    requestable_targets: Iterable[
        EtfMinsRequestableTarget | Mapping[str, object]
    ],
) -> tuple[ProdEtfMinsFrequencyCoverage, ...]:
    """Read all date/frequency code-presence groups with one bound SQL call."""

    normalized_dates = _normalize_coverage_trade_dates(trade_dates)
    normalized_targets = normalize_etf_mins_requestable_targets(requestable_targets)
    params = (
        list(normalized_dates),
        [target.ts_code for target in normalized_targets],
        [target.list_date for target in normalized_targets],
        list(ETF_MINS_SOURCE_FREQS),
        ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
    )
    with (
        prod_postgres.connect_readonly_transaction() as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(PROD_ETF_MINS_COVERAGE_SQL, params)
        rows = cursor.fetchall()

    observed = tuple(
        ProdEtfMinsFrequencyCoverage(
            trade_date=normalize_etf_mins_trade_date(row[0]),
            source_freq=normalize_etf_mins_source_freq(row[1]),
            expected_code_count=int(row[2]),
            present_code_count=int(row[3]),
            missing_code_count=int(row[4]),
            missing_code_samples=tuple(str(code) for code in (row[5] or ())),
        )
        for row in rows
    )
    expected_keys = tuple(
        (trade_date, source_freq)
        for trade_date in normalized_dates
        for source_freq in ETF_MINS_SOURCE_FREQS
    )
    observed_keys = tuple(
        (coverage.trade_date, coverage.source_freq) for coverage in observed
    )
    if observed_keys != expected_keys:
        raise RuntimeError(
            "Prod ETF minute coverage returned an incomplete or reordered result set."
        )
    for coverage in observed:
        if (
            coverage.expected_code_count < 0
            or coverage.present_code_count < 0
            or coverage.missing_code_count < 0
            or coverage.present_code_count > coverage.expected_code_count
            or coverage.missing_code_count
            != coverage.expected_code_count - coverage.present_code_count
            or len(coverage.missing_code_samples)
            > ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT
        ):
            raise RuntimeError("Prod ETF minute coverage returned invalid counts.")
    return observed


def validate_prod_etf_mins_select_contract() -> None:
    sample_sql = build_prod_etf_mins_remote_query(
        source_freq="1min",
        start_datetime="2026-08-28 00:00:00",
        end_datetime="2026-08-29 00:00:00",
    )
    normalized_sql = " ".join(sample_sql.lower().split())
    forbidden = (
        "select *",
        " join ",
        " ts_code in ",
        " ts_code = any",
        "api_name",
        "fetched_at",
        "raw_payload",
    )
    if any(token in normalized_sql for token in forbidden):
        raise RuntimeError("Prod ETF minute detail SQL violates its allowlist contract.")
    if f"from {PROD_ETF_MINS_SOURCE_TABLE}" not in normalized_sql:
        raise RuntimeError("Prod ETF minute detail SQL uses an unapproved source table.")
    for column in ETF_MINS_SOURCE_COLUMNS:
        if column not in normalized_sql:
            raise RuntimeError(
                f"Prod ETF minute detail SQL is missing required column {column}."
            )


def validate_prod_etf_mins_duckdb_contract() -> None:
    fake_conninfo = "host=fake.invalid user=fake password=fake"
    source_sql = build_prod_etf_mins_duckdb_source_sql(
        source_freq="1min",
        start_datetime="2026-08-28 00:00:00",
        end_datetime="2026-08-29 00:00:00",
    )
    attach_sql = build_prod_etf_mins_duckdb_attach_sql(conninfo=fake_conninfo)
    if "postgres_query(" not in source_sql.lower():
        raise RuntimeError("Prod ETF minute detail source must use postgres_query.")
    if fake_conninfo in source_sql:
        raise RuntimeError("Prod ETF minute detail query must not contain conninfo.")
    normalized_attach = " ".join(attach_sql.lower().replace(",", " ").split())
    if "type postgres" not in normalized_attach or "read_only" not in normalized_attach:
        raise RuntimeError("Prod ETF minute DuckDB attach must be read-only Postgres.")


def _normalize_coverage_trade_dates(values: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(sorted(normalize_etf_mins_trade_date(value) for value in values))
    if not normalized:
        raise ValueError("ETF minute coverage requires at least one trade date.")
    if len(normalized) > ETF_MINS_SENSOR_WINDOW_LIMIT:
        raise ValueError(
            "ETF minute coverage accepts at most ten trade dates per query."
        )
    if len(set(normalized)) != len(normalized):
        raise ValueError("ETF minute coverage trade dates must be unique.")
    return normalized


def _normalize_postgres_timestamp(value: object) -> str:
    normalized = str(value).strip()
    if not _POSTGRES_TIMESTAMP_RE.fullmatch(normalized):
        raise ValueError("ETF minute timestamp must use YYYY-MM-DD HH:MM:SS.")
    try:
        parsed = datetime.fromisoformat(normalized).replace(tzinfo=UTC)
    except ValueError as error:
        raise ValueError(
            "ETF minute timestamp must use YYYY-MM-DD HH:MM:SS."
        ) from error
    canonical = parsed.astimezone(UTC).strftime(_POSTGRES_TIMESTAMP_FORMAT)
    if normalized != canonical:
        raise ValueError("ETF minute timestamp must be canonical.")
    return canonical


def _normalize_sql_identifier(value: object, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not _SQL_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a simple SQL identifier.")
    return normalized


def _postgres_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


__all__ = [
    "PROD_ETF_MINS_COVERAGE_SQL",
    "PROD_ETF_MINS_DUCKDB_ATTACHED_DATABASE",
    "PROD_ETF_MINS_DUCKDB_ATTACH_OPTIONS",
    "PROD_ETF_MINS_SELECT_TEMPLATE",
    "PROD_ETF_MINS_SOURCE_TABLE",
    "ProdEtfMinsCodeCoverageProbe",
    "ProdEtfMinsFrequencyCoverage",
    "build_prod_etf_mins_duckdb_attach_sql",
    "build_prod_etf_mins_duckdb_source_sql",
    "build_prod_etf_mins_remote_query",
    "load_prod_etf_mins_code_coverage",
    "probe_prod_etf_mins_code_coverage",
    "validate_prod_etf_mins_duckdb_contract",
    "validate_prod_etf_mins_select_contract",
]
