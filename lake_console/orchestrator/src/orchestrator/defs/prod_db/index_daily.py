"""Read-only prod core DB extraction contract for index daily raw assets."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource
from orchestrator.defs.run_contracts.configs import normalize_iso_trade_date


PROD_INDEX_DAILY_DUCKDB_ATTACHED_DATABASE = "prod_core_pg"
PROD_INDEX_DAILY_DUCKDB_ATTACH_OPTIONS = "TYPE POSTGRES, READ_ONLY"
PROD_INDEX_DAILY_SOURCE_TABLE = "core_serving.index_daily_serving"
PROD_INDEX_DAILY_FORBIDDEN_COLUMNS = ("source", "created_at", "updated_at")
PROD_INDEX_DAILY_SOURCE_COLUMNS = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)

PROD_INDEX_DAILY_SELECT_TEMPLATE = """
SELECT
  ts_code,
  to_char(trade_date, 'YYYYMMDD') AS trade_date,
  open,
  high,
  low,
  close,
  pre_close,
  change_amount AS change,
  pct_chg,
  vol,
  amount
FROM core_serving.index_daily_serving
WHERE trade_date = DATE {trade_date}
  AND ts_code = ANY(ARRAY[{index_codes}]::text[])
ORDER BY ts_code
"""


@dataclass(frozen=True)
class ProdIndexDailySourceReadiness:
    trade_date: str
    expected_code_count: int
    expected_code_set_hash: str | None
    returned_code_count: int
    source_row_count: int
    missing_code_count: int
    extra_code_count: int
    duplicate_key_count: int
    null_key_count: int
    date_mismatch_count: int
    missing_code_samples: tuple[str, ...] = ()
    extra_code_samples: tuple[str, ...] = ()
    elapsed_ms: int = 0
    scan_error_code: str | None = None
    scan_error: str | None = None

    @property
    def ready(self) -> bool:
        return (
            self.scan_error is None
            and self.expected_code_count > 0
            and self.source_row_count > 0
            and self.returned_code_count == self.expected_code_count
            and self.missing_code_count == 0
            and self.extra_code_count == 0
            and self.duplicate_key_count == 0
            and self.null_key_count == 0
            and self.date_mismatch_count == 0
        )

    @property
    def reason(self) -> str:
        if self.ready:
            return "ready"
        if self.scan_error:
            return "scan_error"
        if self.source_row_count <= 0:
            return "source_empty"
        if self.null_key_count:
            return "null_key"
        if self.date_mismatch_count:
            return "date_mismatch"
        if self.duplicate_key_count:
            return "duplicate_key"
        if self.missing_code_count or self.extra_code_count:
            return "code_coverage"
        return "not_ready"

    def to_metadata(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "ready": self.ready,
            "reason": self.reason,
            "expected_code_count": self.expected_code_count,
            "expected_code_set_hash": self.expected_code_set_hash,
            "returned_code_count": self.returned_code_count,
            "source_row_count": self.source_row_count,
            "missing_code_count": self.missing_code_count,
            "extra_code_count": self.extra_code_count,
            "duplicate_key_count": self.duplicate_key_count,
            "null_key_count": self.null_key_count,
            "date_mismatch_count": self.date_mismatch_count,
            "missing_code_samples": list(self.missing_code_samples),
            "extra_code_samples": list(self.extra_code_samples),
            "elapsed_ms": self.elapsed_ms,
            "scan_error_code": self.scan_error_code,
            "scan_error": self.scan_error,
        }


def normalize_index_codes(index_codes: Sequence[str]) -> tuple[str, ...]:
    normalized_codes = tuple(
        dict.fromkeys(str(index_code).strip() for index_code in index_codes)
    )
    if not normalized_codes:
        raise ValueError("index_codes must not be empty for prod index_daily query.")
    if any(not index_code for index_code in normalized_codes):
        raise ValueError("index_codes must not contain blank values.")
    return normalized_codes


def index_code_set_hash(index_codes: Sequence[str]) -> str:
    normalized_codes = tuple(sorted(normalize_index_codes(index_codes)))
    return hashlib.md5("\n".join(normalized_codes).encode("utf-8")).hexdigest()


def build_prod_index_daily_remote_query(
    *,
    trade_date: str,
    index_codes: Sequence[str],
) -> str:
    normalized_trade_date = normalize_iso_trade_date(trade_date)
    normalized_codes = normalize_index_codes(index_codes)
    index_code_literals = ", ".join(
        _postgres_literal(index_code) for index_code in normalized_codes
    )
    return PROD_INDEX_DAILY_SELECT_TEMPLATE.format(
        trade_date=_postgres_literal(normalized_trade_date),
        index_codes=index_code_literals,
    )


def build_prod_index_daily_duckdb_source_sql(
    *,
    attached_database: str = PROD_INDEX_DAILY_DUCKDB_ATTACHED_DATABASE,
    trade_date: str,
    index_codes: Sequence[str],
) -> str:
    remote_query = build_prod_index_daily_remote_query(
        trade_date=trade_date,
        index_codes=index_codes,
    )
    return (
        "SELECT "
        + ", ".join(PROD_INDEX_DAILY_SOURCE_COLUMNS)
        + " FROM postgres_query("
        + duckdb_string(attached_database)
        + ", "
        + duckdb_string(remote_query)
        + ")"
    )


def _postgres_literal(value: object) -> str:
    text = str(value).replace("'", "''")
    return f"'{text}'"


def validate_prod_index_daily_select_contract() -> None:
    sample_sql = build_prod_index_daily_remote_query(
        trade_date="2026-05-29",
        index_codes=("000001.SH", "399001.SZ"),
    )
    normalized_sql = " ".join(sample_sql.lower().split())
    if "select *" in normalized_sql:
        raise RuntimeError("Prod index_daily select must not use SELECT *.")
    for forbidden_column in PROD_INDEX_DAILY_FORBIDDEN_COLUMNS:
        if forbidden_column in normalized_sql:
            raise RuntimeError(
                f"Prod index_daily select must not export {forbidden_column}."
            )
    for required_text in (
        "ts_code",
        "to_char(trade_date, 'yyyymmdd') as trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change_amount as change",
        "pct_chg",
        "vol",
        "amount",
    ):
        if required_text not in normalized_sql:
            raise RuntimeError(
                "Prod index_daily select is missing required projection "
                f"{required_text}."
            )
    for clause in (
        "from core_serving.index_daily_serving",
        "where trade_date = date",
        "ts_code = any(array[",
        "order by ts_code",
    ):
        if clause not in normalized_sql:
            raise RuntimeError(
                f"Prod index_daily select is missing required clause: {clause}."
            )


def validate_prod_index_daily_duckdb_source_contract() -> None:
    sample_sql = build_prod_index_daily_duckdb_source_sql(
        trade_date="2026-05-29",
        index_codes=("000001.SH",),
    )
    normalized_sql = " ".join(sample_sql.lower().split())
    if "postgres_query(" not in normalized_sql:
        raise RuntimeError("Prod index_daily DuckDB source must use postgres_query.")
    if PROD_INDEX_DAILY_DUCKDB_ATTACHED_DATABASE not in sample_sql:
        raise RuntimeError(
            "Prod index_daily DuckDB source must query an attached database alias."
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
                "Prod index_daily DuckDB source must not embed Postgres conninfo."
            )
    for required_column in PROD_INDEX_DAILY_SOURCE_COLUMNS:
        if required_column not in normalized_sql:
            raise RuntimeError(
                "Prod index_daily DuckDB source is missing required column "
                f"{required_column}."
            )


def validate_prod_index_daily_duckdb_attach_options_contract() -> None:
    normalized_options = " ".join(
        PROD_INDEX_DAILY_DUCKDB_ATTACH_OPTIONS.lower().replace(",", " ").split()
    )
    if "type postgres" not in normalized_options:
        raise RuntimeError(
            "Prod index_daily DuckDB attach options must use TYPE POSTGRES."
        )
    if "read_only" not in normalized_options:
        raise RuntimeError(
            "Prod index_daily DuckDB attach options must force READ_ONLY."
        )


def load_duckdb_postgres_extension_for_index_daily(connection) -> None:
    try:
        connection.execute("LOAD postgres")
        return
    except Exception:  # noqa: BLE001 - retry with INSTALL for local envs.
        try:
            connection.execute("INSTALL postgres")
            connection.execute("LOAD postgres")
            return
        except Exception as install_error:  # noqa: BLE001
            raise RuntimeError(
                "DuckDB postgres extension is required for prod DB index_daily "
                "readiness/extraction."
            ) from install_error


def attach_prod_index_daily_postgres_database(
    connection,
    *,
    postgres_connection_string: str,
) -> None:
    attach_sql = (
        "ATTACH "
        + duckdb_string(postgres_connection_string)
        + (
            f" AS {PROD_INDEX_DAILY_DUCKDB_ATTACHED_DATABASE} "
            f"({PROD_INDEX_DAILY_DUCKDB_ATTACH_OPTIONS})"
        )
    )
    try:
        connection.execute(attach_sql)
    except Exception:  # noqa: BLE001 - avoid leaking conninfo through DuckDB errors.
        raise RuntimeError(
            "DuckDB failed to attach prod Postgres for index_daily readiness. "
            "Connection details are omitted."
        ) from None


def check_prod_index_daily_source_readiness(
    *,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    index_codes: Sequence[str],
    sample_limit: int = 10,
) -> ProdIndexDailySourceReadiness:
    started_at = perf_counter()
    normalized_trade_date = normalize_iso_trade_date(trade_date)
    try:
        normalized_codes = normalize_index_codes(index_codes)
        validate_prod_index_daily_select_contract()
        validate_prod_index_daily_duckdb_source_contract()
        validate_prod_index_daily_duckdb_attach_options_contract()
        source_sql = build_prod_index_daily_duckdb_source_sql(
            trade_date=normalized_trade_date,
            index_codes=normalized_codes,
        )
        return check_prod_index_daily_source_readiness_from_duckdb_source(
            duckdb=duckdb,
            postgres_connection_string=prod_postgres.duckdb_connection_string(),
            source_sql=source_sql,
            trade_date=normalized_trade_date,
            index_codes=normalized_codes,
            sample_limit=sample_limit,
            load_postgres_extension=True,
            started_at=started_at,
        )
    except Exception as error:  # noqa: BLE001 - sensor source probe must fail closed.
        return ProdIndexDailySourceReadiness(
            trade_date=normalized_trade_date,
            expected_code_count=0,
            expected_code_set_hash=None,
            returned_code_count=0,
            source_row_count=0,
            missing_code_count=0,
            extra_code_count=0,
            duplicate_key_count=0,
            null_key_count=0,
            date_mismatch_count=0,
            elapsed_ms=_elapsed_ms(started_at),
            scan_error_code=type(error).__name__,
            scan_error=str(error),
        )


def check_prod_index_daily_source_readiness_from_duckdb_source(
    *,
    duckdb: DuckDBResource,
    source_sql: str,
    trade_date: str,
    index_codes: Sequence[str],
    postgres_connection_string: str | None = None,
    sample_limit: int = 10,
    load_postgres_extension: bool = False,
    started_at: float | None = None,
) -> ProdIndexDailySourceReadiness:
    started_at = perf_counter() if started_at is None else started_at
    normalized_trade_date = normalize_iso_trade_date(trade_date)
    expected_codes = normalize_index_codes(index_codes)
    expected_codes_sql = _index_daily_expected_codes_sql(expected_codes)
    source_trade_date = normalized_trade_date.replace("-", "")
    sample_limit = max(1, int(sample_limit))
    duckdb_resource = duckdb
    try:
        with duckdb_resource.connect() as connection:
            if load_postgres_extension:
                load_duckdb_postgres_extension_for_index_daily(connection)
                if postgres_connection_string is None:
                    raise RuntimeError(
                        "Prod DB index_daily readiness requires a Postgres connection string."
                    )
                attach_prod_index_daily_postgres_database(
                    connection,
                    postgres_connection_string=postgres_connection_string,
                )
            connection.execute(
                "CREATE TEMP TABLE prod_index_daily_source_probe AS "
                f"SELECT {', '.join(PROD_INDEX_DAILY_SOURCE_COLUMNS)} "
                f"FROM ({source_sql}) AS source_rows"
            )
            source_row_count = int(
                connection.execute(
                    "SELECT count(*) FROM prod_index_daily_source_probe"
                ).fetchone()[0]
            )
            null_key_count = int(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM prod_index_daily_source_probe
                    WHERE ts_code IS NULL
                       OR trim(CAST(ts_code AS VARCHAR)) = ''
                       OR trade_date IS NULL
                       OR trim(CAST(trade_date AS VARCHAR)) = ''
                    """
                ).fetchone()[0]
            )
            date_mismatch_count = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM prod_index_daily_source_probe
                    WHERE CAST(trade_date AS VARCHAR) != {duckdb_string(source_trade_date)}
                    """
                ).fetchone()[0]
            )
            duplicate_key_count = int(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM (
                      SELECT ts_code, trade_date
                      FROM prod_index_daily_source_probe
                      GROUP BY ts_code, trade_date
                      HAVING count(*) > 1
                    ) duplicate_keys
                    """
                ).fetchone()[0]
            )
            observed_codes_sql = """
                SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
                FROM prod_index_daily_source_probe
            """
            coverage_row = connection.execute(
                f"""
                WITH expected AS (
                  SELECT ts_code FROM {expected_codes_sql}
                ),
                observed AS (
                  {observed_codes_sql}
                )
                SELECT
                  (SELECT count(*) FROM observed) AS returned_code_count,
                  (
                    SELECT count(*)
                    FROM expected
                    LEFT JOIN observed USING (ts_code)
                    WHERE observed.ts_code IS NULL
                  ) AS missing_code_count,
                  (
                    SELECT count(*)
                    FROM observed
                    LEFT JOIN expected USING (ts_code)
                    WHERE expected.ts_code IS NULL
                  ) AS extra_code_count
                """
            ).fetchone()
            missing_samples = _index_daily_code_diff_samples(
                connection,
                expected_code_set_sql=expected_codes_sql,
                observed_codes_sql=observed_codes_sql,
                direction="missing",
                sample_limit=sample_limit,
            )
            extra_samples = _index_daily_code_diff_samples(
                connection,
                expected_code_set_sql=expected_codes_sql,
                observed_codes_sql=observed_codes_sql,
                direction="extra",
                sample_limit=sample_limit,
            )
        return ProdIndexDailySourceReadiness(
            trade_date=normalized_trade_date,
            expected_code_count=len(expected_codes),
            expected_code_set_hash=index_code_set_hash(expected_codes),
            returned_code_count=int(coverage_row[0]),
            source_row_count=source_row_count,
            missing_code_count=int(coverage_row[1]),
            extra_code_count=int(coverage_row[2]),
            duplicate_key_count=duplicate_key_count,
            null_key_count=null_key_count,
            date_mismatch_count=date_mismatch_count,
            missing_code_samples=tuple(missing_samples),
            extra_code_samples=tuple(extra_samples),
            elapsed_ms=_elapsed_ms(started_at),
        )
    except Exception as error:  # noqa: BLE001 - sensor source probe must fail closed.
        return ProdIndexDailySourceReadiness(
            trade_date=normalized_trade_date,
            expected_code_count=len(expected_codes),
            expected_code_set_hash=index_code_set_hash(expected_codes),
            returned_code_count=0,
            source_row_count=0,
            missing_code_count=0,
            extra_code_count=0,
            duplicate_key_count=0,
            null_key_count=0,
            date_mismatch_count=0,
            elapsed_ms=_elapsed_ms(started_at),
            scan_error_code=type(error).__name__,
            scan_error=str(error),
        )


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def _index_daily_expected_codes_sql(index_codes: Sequence[str]) -> str:
    rows = ", ".join(f"({duckdb_string(index_code)})" for index_code in index_codes)
    return f"(VALUES {rows}) AS expected(ts_code)"


def _index_daily_code_diff_samples(
    connection,
    *,
    expected_code_set_sql: str,
    observed_codes_sql: str,
    direction: str,
    sample_limit: int,
) -> list[str]:
    if direction == "missing":
        sql = f"""
        SELECT expected.ts_code
        FROM {expected_code_set_sql}
        LEFT JOIN ({observed_codes_sql}) observed USING (ts_code)
        WHERE observed.ts_code IS NULL
        ORDER BY expected.ts_code
        LIMIT {int(sample_limit)}
        """
    elif direction == "extra":
        sql = f"""
        SELECT observed.ts_code
        FROM ({observed_codes_sql}) observed
        LEFT JOIN (SELECT ts_code FROM {expected_code_set_sql}) expected USING (ts_code)
        WHERE expected.ts_code IS NULL
        ORDER BY observed.ts_code
        LIMIT {int(sample_limit)}
        """
    else:
        raise ValueError("direction must be missing or extra.")
    return [str(row[0]) for row in connection.execute(sql).fetchall()]
