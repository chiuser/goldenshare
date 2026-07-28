"""Read-only prod DB extraction and readiness contracts for stock minutes."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter

from orchestrator.defs.asset_guards.stk_mins_stock_universe import (
    normalize_stk_mins_stock_codes,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.resources import ProdPostgresResource
from orchestrator.defs.run_contracts.stk_mins import normalize_stk_mins_freq


PROD_STK_MINS_DUCKDB_ATTACHED_DATABASE = "prod_raw_pg"
PROD_STK_MINS_DUCKDB_ATTACH_OPTIONS = "TYPE POSTGRES, READ_ONLY"
PROD_STK_MINS_SOURCE_COLUMNS = (
    "ts_code",
    "freq",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
)
PROD_STK_MINS_COVERAGE_SAMPLE_LIMIT = 3


@dataclass(frozen=True, slots=True)
class ProdStkMinsFrequencyCoverage:
    freq: int
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
class ProdStkMinsCodeCoverageProbe:
    ready: bool
    reason_code: str
    frequency_coverages: tuple[ProdStkMinsFrequencyCoverage, ...]
    first_missing_freq: int | None
    elapsed_ms: int
    error_type: str | None = None

    def coverage_by_freq(self) -> dict[int, ProdStkMinsFrequencyCoverage]:
        return {coverage.freq: coverage for coverage in self.frequency_coverages}

PROD_STK_MINS_SELECT_TEMPLATE = """
SELECT
  ts_code,
  freq,
  trade_time,
  open,
  close,
  high,
  low,
  vol,
  amount
FROM raw_tushare.stk_mins
WHERE freq = {freq}
  AND trade_time >= TIMESTAMP {start_datetime}
  AND trade_time < TIMESTAMP {end_datetime}
  AND ts_code = ANY(ARRAY[{stock_codes}]::text[])
ORDER BY ts_code, trade_time
"""


def build_prod_stk_mins_remote_query(
    *,
    stock_codes: Sequence[str],
    freq: int,
    start_datetime: str,
    end_datetime: str,
) -> str:
    if not stock_codes:
        raise ValueError("stock_codes must not be empty for prod stk_mins query.")
    normalized_codes = tuple(dict.fromkeys(str(code).strip() for code in stock_codes))
    blank_codes = [code for code in normalized_codes if not code]
    if blank_codes:
        raise ValueError("stock_codes must not contain blank values.")
    stock_code_literals = ", ".join(_postgres_literal(code) for code in normalized_codes)
    return PROD_STK_MINS_SELECT_TEMPLATE.format(
        freq=int(freq),
        start_datetime=_postgres_literal(start_datetime),
        end_datetime=_postgres_literal(end_datetime),
        stock_codes=stock_code_literals,
    )


def build_prod_stk_mins_duckdb_source_sql(
    *,
    attached_database: str = PROD_STK_MINS_DUCKDB_ATTACHED_DATABASE,
    stock_codes: Sequence[str],
    freq: int,
    start_datetime: str,
    end_datetime: str,
) -> str:
    remote_query = build_prod_stk_mins_remote_query(
        stock_codes=stock_codes,
        freq=freq,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
    )
    return (
        "SELECT "
        + ", ".join(PROD_STK_MINS_SOURCE_COLUMNS)
        + " FROM postgres_query("
        + duckdb_string(attached_database)
        + ", "
        + duckdb_string(remote_query)
        + ")"
    )


def probe_prod_stk_mins_code_coverage(
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    stock_codes: Sequence[str],
    freqs: Sequence[int] = (1, 5, 15, 30, 60),
) -> ProdStkMinsCodeCoverageProbe:
    """Return a fail-closed, bounded source-coverage result for one trade date."""

    started = perf_counter()
    try:
        frequency_coverages = load_prod_stk_mins_code_coverage(
            prod_postgres=prod_postgres,
            trade_date=trade_date,
            stock_codes=stock_codes,
            freqs=freqs,
        )
    except Exception as error:
        return ProdStkMinsCodeCoverageProbe(
            ready=False,
            reason_code="prod_source_code_coverage_query_error",
            frequency_coverages=(),
            first_missing_freq=None,
            elapsed_ms=int((perf_counter() - started) * 1000),
            error_type=type(error).__name__,
        )

    first_missing_freq = next(
        (coverage.freq for coverage in frequency_coverages if not coverage.ready),
        None,
    )
    return ProdStkMinsCodeCoverageProbe(
        ready=first_missing_freq is None,
        reason_code=(
            "prod_source_code_coverage_ready"
            if first_missing_freq is None
            else "prod_source_code_coverage_incomplete"
        ),
        frequency_coverages=frequency_coverages,
        first_missing_freq=first_missing_freq,
        elapsed_ms=int((perf_counter() - started) * 1000),
    )


def load_prod_stk_mins_code_coverage(
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    stock_codes: Sequence[str],
    freqs: Sequence[int],
) -> tuple[ProdStkMinsFrequencyCoverage, ...]:
    """Read code presence through the source primary-key index without row scans."""

    normalized_codes = normalize_stk_mins_stock_codes(stock_codes)
    normalized_freqs = tuple(sorted({normalize_stk_mins_freq(freq) for freq in freqs}))
    if not normalized_freqs:
        raise ValueError("freqs must not be empty for prod stk_mins coverage.")
    start_datetime, end_datetime = _trade_day_window(trade_date)
    sql = """
    WITH expected_codes AS (
      SELECT DISTINCT btrim(candidate_code) AS ts_code
      FROM unnest(%s::text[]) AS source(candidate_code)
      WHERE btrim(candidate_code) <> ''
    ),
    expected_pairs AS (
      SELECT freq, ts_code
      FROM unnest(%s::smallint[]) AS source(freq)
      CROSS JOIN expected_codes
    ),
    coverage AS MATERIALIZED (
      SELECT
        pair.freq,
        pair.ts_code,
        EXISTS (
          SELECT 1
          FROM raw_tushare.stk_mins AS source
          WHERE source.ts_code = pair.ts_code
            AND source.freq = pair.freq
            AND source.trade_time >= %s::timestamp
            AND source.trade_time < %s::timestamp
          LIMIT 1
        ) AS present
      FROM expected_pairs AS pair
    ),
    missing_ranked AS (
      SELECT
        freq,
        ts_code,
        row_number() OVER (PARTITION BY freq ORDER BY ts_code) AS sample_rank
      FROM coverage
      WHERE NOT present
    )
    SELECT
      coverage.freq,
      count(*) AS expected_code_count,
      count(*) FILTER (WHERE coverage.present) AS present_code_count,
      count(*) FILTER (WHERE NOT coverage.present) AS missing_code_count,
      COALESCE(
        array_agg(missing_ranked.ts_code ORDER BY missing_ranked.ts_code)
          FILTER (WHERE missing_ranked.sample_rank <= %s),
        ARRAY[]::text[]
      ) AS missing_code_samples
    FROM coverage
    LEFT JOIN missing_ranked
      ON missing_ranked.freq = coverage.freq
      AND missing_ranked.ts_code = coverage.ts_code
    GROUP BY coverage.freq
    ORDER BY coverage.freq
    """
    with prod_postgres.connect_readonly_transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    list(normalized_codes),
                    list(normalized_freqs),
                    start_datetime,
                    end_datetime,
                    PROD_STK_MINS_COVERAGE_SAMPLE_LIMIT,
                ),
            )
            rows = cursor.fetchall()

    observed = tuple(
        ProdStkMinsFrequencyCoverage(
            freq=int(row[0]),
            expected_code_count=int(row[1]),
            present_code_count=int(row[2]),
            missing_code_count=int(row[3]),
            missing_code_samples=tuple(str(code) for code in (row[4] or ())),
        )
        for row in rows
    )
    observed_freqs = tuple(coverage.freq for coverage in observed)
    if observed_freqs != normalized_freqs:
        raise RuntimeError(
            "Prod stk_mins coverage query returned unexpected frequencies: "
            f"expected={normalized_freqs}, observed={observed_freqs}."
        )
    return observed


def _trade_day_window(trade_date: str) -> tuple[str, str]:
    try:
        normalized = datetime.strptime(trade_date, "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        raise ValueError("trade_date must use YYYY-MM-DD format.") from error
    return f"{normalized} 09:00:00", f"{normalized} 19:00:00"


def _postgres_literal(value: object) -> str:
    text = str(value).replace("'", "''")
    return f"'{text}'"


def validate_prod_stk_mins_select_contract() -> None:
    sample_sql = build_prod_stk_mins_remote_query(
        stock_codes=("600000.SH", "000001.SZ"),
        freq=1,
        start_datetime="2026-05-29 09:00:00",
        end_datetime="2026-05-29 19:00:00",
    )
    normalized_sql = " ".join(sample_sql.lower().split())
    if "select *" in normalized_sql:
        raise RuntimeError("Prod stk_mins select must not use SELECT *.")
    for forbidden_column in ("api_name", "fetched_at", "raw_payload"):
        if forbidden_column in normalized_sql:
            raise RuntimeError(
                f"Prod stk_mins select must not export {forbidden_column}."
            )
    for required_column in PROD_STK_MINS_SOURCE_COLUMNS:
        if required_column not in normalized_sql:
            raise RuntimeError(
                f"Prod stk_mins select is missing required column {required_column}."
            )
    required_clauses = (
        "where freq =",
        "trade_time >=",
        "trade_time <",
        "ts_code = any(array[",
    )
    for clause in required_clauses:
        if clause not in normalized_sql:
            raise RuntimeError(
                f"Prod stk_mins select is missing required filter clause: {clause}."
            )


def validate_prod_stk_mins_duckdb_source_contract() -> None:
    sample_sql = build_prod_stk_mins_duckdb_source_sql(
        stock_codes=("600000.SH",),
        freq=1,
        start_datetime="2026-05-29 09:00:00",
        end_datetime="2026-05-29 19:00:00",
    )
    normalized_sql = " ".join(sample_sql.lower().split())
    if "postgres_query(" not in normalized_sql:
        raise RuntimeError("Prod stk_mins DuckDB source must use postgres_query.")
    if PROD_STK_MINS_DUCKDB_ATTACHED_DATABASE not in sample_sql:
        raise RuntimeError(
            "Prod stk_mins DuckDB source must query an attached database alias."
        )
    for forbidden_text in (
        "host=",
        "user=",
        "password=",
        "dbname=",
        "connect_timeout=",
    ):
        if forbidden_text in normalized_sql:
            raise RuntimeError(
                "Prod stk_mins DuckDB source must not embed Postgres conninfo."
            )
    for required_column in PROD_STK_MINS_SOURCE_COLUMNS:
        if required_column not in normalized_sql:
            raise RuntimeError(
                "Prod stk_mins DuckDB source is missing required column "
                f"{required_column}."
            )


def validate_prod_stk_mins_duckdb_attach_options_contract() -> None:
    normalized_options = " ".join(
        PROD_STK_MINS_DUCKDB_ATTACH_OPTIONS.lower().replace(",", " ").split()
    )
    if "type postgres" not in normalized_options:
        raise RuntimeError(
            "Prod stk_mins DuckDB attach options must use TYPE POSTGRES."
        )
    if "read_only" not in normalized_options:
        raise RuntimeError(
            "Prod stk_mins DuckDB attach options must force READ_ONLY."
        )
