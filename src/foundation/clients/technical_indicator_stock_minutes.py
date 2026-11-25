"""Selection and front-adjusted OHLC for DG stock minute bars."""

from datetime import date, time


STOCK_MINUTE_HISTORY_START = date(2014, 1, 1)
_STOCK_TRADING_SESSIONS = ((9 * 60 + 30, 11 * 60 + 30), (13 * 60, 15 * 60))
_AUCTION_TIME = time(9, 30)


def stock_minute_selection_sql(target_frequency: int, base_frequency: int) -> tuple[str, int]:
    """Select complete DG windows with their underlying unadjusted bars."""
    regular_times = tuple(
        time(minute // 60, minute % 60)
        for start, end in _STOCK_TRADING_SESSIONS
        for minute in range(start + base_frequency, end + 1, base_frequency)
    )
    if target_frequency == 1:
        regular_times = (_AUCTION_TIME, *regular_times)
    # Group trading time across lunch. The last 90-minute window uses the two
    # remaining 30-minute bars, and only the first window takes the auction.
    bars_per_window = target_frequency // base_frequency
    windows = tuple(
        regular_times[offset:offset + bars_per_window]
        for offset in range(0, len(regular_times), bars_per_window)
    )
    rows = []
    for index, clocks in enumerate(windows):
        includes_auction = target_frequency != 1 and index == 0
        source_count = len(clocks) + int(includes_auction)
        rows.extend((clock, clocks[-1], False, source_count) for clock in clocks)
        if includes_auction:
            rows.append((_AUCTION_TIME, clocks[-1], True, source_count))
    values = ", ".join(
        f"(TIME '{source}', TIME '{target}', {auction}, {source_count})"
        for source, target, auction, source_count in rows
    )
    return f"""
        WITH window_map(source_clock, target_clock, is_auction, source_count) AS (VALUES {values}),
        mapped AS (
            SELECT b.trade_date, b.trade_date + w.target_clock AS target_time,
                   b.trade_time, b.open, b.high, b.low, b.close, b.vol, b.amount, b.exchange,
                   w.is_auction, w.source_count
            FROM read_parquet(?, hive_partitioning=false) AS b
            JOIN window_map AS w ON CAST(b.trade_time AS TIME) = w.source_clock
            WHERE b.ts_code = ? AND b.freq = ?
        )
        SELECT trade_date, target_time AS trade_time, exchange,
               list(struct_pack(
                   trade_time := trade_time, open := open, high := high, low := low,
                   close := close, vol := vol, amount := amount, is_auction := is_auction
               ) ORDER BY trade_time) AS base_bars
        FROM mapped
        WHERE target_time <= ?
        GROUP BY trade_date, target_time, exchange, source_count
        HAVING count(*) = source_count AND count(DISTINCT trade_time) = source_count
        ORDER BY target_time DESC LIMIT ?
    """, len(windows)


STOCK_MINUTE_SELECTED_ROWS_SQL = """
    CREATE TEMP TABLE ti_stock_minute_selected_rows AS
    SELECT w.trade_date, w.trade_time AS target_time, w.exchange,
           bar.trade_time, bar.open, bar.high, bar.low, bar.close,
           bar.vol, bar.amount, bar.is_auction
    FROM ti_stock_minute_windows w, UNNEST(w.base_bars) AS input(bar)
"""


def adjusted_stock_minute_sql(columns: tuple[str, ...]) -> str:
    return f"""
        WITH adjusted_days AS MATERIALIZED (
            SELECT f.trade_date, f.adj_factor / a.basis_value AS multiplier
            FROM ti_stock_minute_factors f CROSS JOIN ti_stock_minute_basis a
        ),
        adjusted AS (
            SELECT b.trade_date, b.target_time, b.exchange, b.trade_time, b.is_auction,
                   b.open * d.multiplier AS open, b.high * d.multiplier AS high,
                   b.low * d.multiplier AS low, b.close * d.multiplier AS close,
                   b.vol, b.amount
            FROM ti_stock_minute_selected_rows b
            JOIN adjusted_days d USING (trade_date)
        ),
        bars AS (
            SELECT trade_date, target_time AS trade_time, exchange,
                   coalesce(max(close) FILTER (WHERE is_auction),
                            arg_min(open, trade_time) FILTER (WHERE NOT is_auction)) AS open,
                   greatest(max(high) FILTER (WHERE NOT is_auction),
                            max(close) FILTER (WHERE is_auction)) AS high,
                   least(min(low) FILTER (WHERE NOT is_auction),
                         max(close) FILTER (WHERE is_auction)) AS low,
                   arg_max(close, trade_time) FILTER (WHERE NOT is_auction) AS close,
                   sum(vol) AS volume, sum(amount) AS amount
            FROM adjusted
            GROUP BY trade_date, target_time, exchange
        )
        SELECT {', '.join(columns)} FROM bars ORDER BY trade_time
    """
