"""Read-only prod DB extraction contract for stock minute raw assets."""

from collections.abc import Mapping, Sequence
from typing import Any

from psycopg2.extras import RealDictCursor


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

PROD_STK_MINS_SELECT_SQL = """
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
WHERE freq = %(freq)s
  AND trade_time >= %(start_datetime)s
  AND trade_time < %(end_datetime)s
  AND ts_code = ANY(%(stock_codes)s)
ORDER BY ts_code, trade_time
"""


def fetch_prod_stk_mins_rows_for_stock_codes(
    connection: Any,
    *,
    stock_codes: Sequence[str],
    freq: int,
    start_datetime: str,
    end_datetime: str,
) -> list[dict[str, Any]]:
    if not stock_codes:
        return []
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            PROD_STK_MINS_SELECT_SQL,
            {
                "stock_codes": list(stock_codes),
                "freq": freq,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
            },
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def assert_prod_stk_mins_source_columns(row: Mapping[str, Any]) -> None:
    unexpected_columns = set(row) - set(PROD_STK_MINS_SOURCE_COLUMNS)
    missing_columns = set(PROD_STK_MINS_SOURCE_COLUMNS) - set(row)
    if unexpected_columns or missing_columns:
        raise RuntimeError(
            "Prod DB stk_mins row does not match the field whitelist: "
            f"missing={sorted(missing_columns)}, unexpected={sorted(unexpected_columns)}."
        )


def validate_prod_stk_mins_select_contract() -> None:
    normalized_sql = " ".join(PROD_STK_MINS_SELECT_SQL.lower().split())
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
