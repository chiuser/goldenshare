"""Source projections for the index minute reading contracts."""

from .technical_indicator_stock_daily import DAILY_PRICE_FIELDS


# Canonical Gold windows in cn_a_derived_minute_bars.py, also used for on-demand DG aggregation.
_INDEX_MINUTE_WINDOWS = {
    "90m": (
        ("11:00:00", ("09:30:00", "10:00:00", "10:30:00", "11:00:00")),
        ("14:00:00", ("11:30:00", "13:30:00", "14:00:00")),
        ("15:00:00", ("14:30:00", "15:00:00")),
    ),
    "120m": (
        ("11:30:00", ("09:30:00", "10:30:00", "11:30:00")),
        ("15:00:00", ("14:00:00", "15:00:00")),
    ),
}


def index_minute_projection(fields):
    price_columns = tuple(
        ("vol" if field == "volume" else field, field) for field in DAILY_PRICE_FIELDS if field in fields
    )
    return (
        ("ts_code", "trade_date", "trade_time", "freq", *(column for column, _ in price_columns)),
        (
            ("trade_date", 'CAST(b."trade_date" AS DATE)'),
            ("trade_time", 'CAST(b."trade_time" AS TIMESTAMP)'),
            *((field, f'CAST(b."{column}" AS DOUBLE)') for column, field in price_columns),
        ),
    )


def dg_recent_index_minute_sql(period, columns):
    """One read for the selected files, returning business bars in descending order."""
    windows = _INDEX_MINUTE_WINDOWS.get(period)
    if windows is None:
        expressions = {"trade_date": "CAST(trade_time AS DATE)", "volume": "vol"}
        projection = ", ".join(f"{expressions[name]} AS {name}" if name in expressions else name for name in columns)
        return f"""
            SELECT {projection}, exchange
            FROM read_parquet(?, hive_partitioning=false)
            WHERE ts_code = ? AND trade_time <= ?
            ORDER BY trade_time DESC
            LIMIT ?
        """

    values = ", ".join(
        f"(TIME '{source}', TIME '{target}', {'TRUE' if source == '09:30:00' else 'FALSE'})"
        for target, sources in windows for source in sources
    )
    auction_close = "max(close) FILTER (WHERE auction)"
    regular_open = "arg_min(open, trade_time) FILTER (WHERE NOT auction)"
    regular_high = "max(high) FILTER (WHERE NOT auction)"
    regular_low = "min(low) FILTER (WHERE NOT auction)"
    expressions = {
        "trade_date": "CAST(trade_time AS DATE)",
        "trade_time": "CAST(trade_time AS DATE) + target_time",
        "open": f"coalesce({auction_close}, {regular_open})",
        "high": f"greatest({regular_high}, {auction_close})",
        "low": f"least({regular_low}, {auction_close})",
        "close": "arg_max(close, trade_time) FILTER (WHERE NOT auction)",
        "volume": "sum(vol)",
        "amount": "sum(amount)",
    }
    projection = ", ".join(f"{expressions[name]} AS {name}" for name in columns)
    return f"""
        WITH windows(source_time, target_time, auction) AS (VALUES {values}),
        bars AS (
            SELECT {projection}, exchange
            FROM read_parquet(?, hive_partitioning=false)
            JOIN windows ON CAST(trade_time AS TIME) = source_time
            WHERE ts_code = ?
            GROUP BY ts_code, CAST(trade_time AS DATE), target_time, exchange
            HAVING count(*) FILTER (WHERE NOT auction) > 0
        )
        SELECT * FROM bars
        WHERE trade_time <= ?
        ORDER BY trade_time DESC
        LIMIT ?
    """
