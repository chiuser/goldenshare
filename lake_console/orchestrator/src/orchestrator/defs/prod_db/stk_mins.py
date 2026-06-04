"""Read-only prod DB extraction contract for stock minute raw assets."""

from collections.abc import Sequence

from orchestrator.defs.duckdb_sql import duckdb_string


PROD_STK_MINS_DUCKDB_ATTACHED_DATABASE = "prod_raw_pg"
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
