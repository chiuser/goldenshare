"""Read-only prod core DB extraction contract for index daily raw assets."""

import hashlib
from collections.abc import Sequence

from orchestrator.defs.duckdb_sql import duckdb_string
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
