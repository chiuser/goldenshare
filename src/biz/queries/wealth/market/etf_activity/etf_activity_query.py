"""Query a bounded set of DG ETF daily partitions for the Wealth ETF module."""

from calendar import monthrange
from datetime import date
import logging
from pathlib import Path
from time import monotonic

from src.biz.schemas.wealth.market.etf_activity import (
    EtfActivityRankErrorDto,
    EtfActivityRankRowDto,
    EtfActivityRankingDto,
    EtfActivityResponseDto,
    EtfActivityTrendPointDto,
)
from src.foundation.clients.local_lake.etf_daily_reader import (
    EtfDailyLakeReader,
    EtfDailyReadError,
    remaining_etf_read_seconds,
)

_logger = logging.getLogger(__name__)
_REQUEST_SECONDS = 5
_EXCHANGE = "SSE"
_DAILY_COLUMNS = {"trade_date": "DATE", "ts_code": "VARCHAR", "amount": "DOUBLE"}
_CURRENT_RANK_COLUMNS = {**_DAILY_COLUMNS, "close": "DOUBLE", "pct_chg": "DOUBLE"}
_BASIC_COLUMNS = {"ts_code": "VARCHAR", "csname": "VARCHAR", "extname": "VARCHAR", "cname": "VARCHAR"}

_INVALID_DAILY_ROW = """
    ts_code IS NULL OR trim(ts_code) = ''
    OR amount IS NULL OR NOT isfinite(amount) OR amount < 0
"""
_TREND_SQL = f"""
WITH files AS (
    SELECT unnest(?::VARCHAR[]) AS filename, unnest(?::DATE[]) AS file_day
), totals AS (
    SELECT file_day,
           CASE WHEN count(DISTINCT ts_code) <> count(*)
                     OR count(*) FILTER (WHERE trade_date IS DISTINCT FROM file_day
                                               OR ({_INVALID_DAILY_ROW})) > 0
                THEN error('invalid ETF daily partition')
                ELSE fsum(amount) * 1000 END AS amount_yuan
    FROM files
    LEFT JOIN read_parquet(?, filename=true, hive_partitioning=false) USING (filename)
    GROUP BY file_day
), open_dates AS (
    SELECT unnest(?::DATE[]) AS day
), rolling AS (
    SELECT day, amount_yuan,
           CASE WHEN count(amount_yuan) OVER ma5 = 5 THEN avg(amount_yuan) OVER ma5 END AS ma5_yuan,
           CASE WHEN count(amount_yuan) OVER ma20 = 20 THEN avg(amount_yuan) OVER ma20 END AS ma20_yuan
    FROM open_dates
    LEFT JOIN totals ON open_dates.day = totals.file_day
    WINDOW ma5 AS (ORDER BY day ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
           ma20 AS (ORDER BY day ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
)
SELECT day, amount_yuan, ma5_yuan, ma20_yuan FROM rolling WHERE day >= ? ORDER BY day
"""

_PRIOR_ROWS_SQL = "SELECT trade_date, ts_code, amount FROM read_parquet(?, hive_partitioning=false)"
_NO_PRIOR_ROWS_SQL = "SELECT NULL::DATE AS trade_date, NULL::VARCHAR AS ts_code, NULL::DOUBLE AS amount WHERE false"
_PRIOR_INVALID_SQL = f"""
    SELECT count(*) = 0 OR count(*) <> count(DISTINCT ts_code)
           OR count(*) FILTER (WHERE trade_date IS DISTINCT FROM ? OR ({_INVALID_DAILY_ROW})) > 0
    FROM previous_day
"""
_RANK_SQL = f"""
WITH current_day AS MATERIALIZED (
    SELECT trade_date, ts_code, close, pct_chg, amount FROM read_parquet(?, hive_partitioning=false)
), previous_day AS MATERIALIZED (
    {{prior_rows}}
), current_top AS MATERIALIZED (
    SELECT ts_code, close, pct_chg, amount,
           row_number() OVER (ORDER BY amount DESC, ts_code ASC) AS rank
    FROM current_day ORDER BY rank LIMIT 50
), previous_ranks AS (
    SELECT ts_code, row_number() OVER (ORDER BY amount DESC, ts_code ASC) AS rank
    FROM previous_day
), names AS MATERIALIZED (
    SELECT ts_code, coalesce(nullif(trim(csname), ''), nullif(trim(extname), ''),
                             nullif(trim(cname), '')) AS name
    FROM read_parquet(?, hive_partitioning=false)
    SEMI JOIN current_top USING (ts_code)
), invalid AS (
    SELECT (SELECT count(*) = 0 OR count(*) <> count(DISTINCT ts_code)
                   OR count(*) FILTER (
                       WHERE trade_date IS DISTINCT FROM ? OR ({_INVALID_DAILY_ROW})
                          OR close IS NULL OR NOT isfinite(close) OR close <= 0
                          OR pct_chg IS NULL OR NOT isfinite(pct_chg)
                   ) > 0 FROM current_day)
           OR ({{prior_invalid}})
           OR (SELECT count(*) <> count(DISTINCT ts_code) FROM names) AS failed
)
SELECT t.rank, t.ts_code, n.name, t.close, t.pct_chg, t.amount * 1000 AS amount_yuan,
       p.rank - t.rank AS rank_change
FROM current_top t
LEFT JOIN previous_ranks p ON t.ts_code = p.ts_code
LEFT JOIN names n ON t.ts_code = n.ts_code
UNION ALL
SELECT NULL, error('invalid DG ETF ranking input')::VARCHAR, NULL, NULL, NULL, NULL, NULL
FROM invalid WHERE failed
ORDER BY rank
"""


def _months_before(day: date, months: int) -> date:
    year, zero_based_month = divmod(day.year * 12 + day.month - 1 - months, 12)
    month = zero_based_month + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _rank(
    reader: EtfDailyLakeReader,
    files: dict[date, Path],
    trade_date: date,
    previous_date: date | None,
    deadline: float,
) -> EtfActivityRankingDto:
    current_file = files[trade_date]
    previous_file = files.get(previous_date) if previous_date is not None else None
    basic_file = reader.basic_file(day=trade_date, daily_file=current_file, deadline=deadline)
    columns = {current_file: _CURRENT_RANK_COLUMNS, basic_file: _BASIC_COLUMNS}
    parameters: list = [str(current_file)]
    if previous_file is not None:
        columns[previous_file] = _DAILY_COLUMNS
        parameters.append(str(previous_file))
    parameters.extend((str(basic_file), trade_date))
    if previous_file is not None:
        parameters.append(previous_date)
    rows = reader.query_parquet(
        _RANK_SQL.format(
            prior_rows=_PRIOR_ROWS_SQL if previous_file is not None else _NO_PRIOR_ROWS_SQL,
            prior_invalid=_PRIOR_INVALID_SQL if previous_file is not None else "SELECT false",
        ),
        parameters,
        columns_by_file=columns,
        deadline=deadline,
    )
    return EtfActivityRankingDto(
        status="ready" if previous_file is not None else "partial",
        rows=[
            EtfActivityRankRowDto(
                rank=rank, tsCode=code, name=name, closePrice=close, priceChangePct=pct,
                amountYuan=amount, rankChange=rank_change,
            )
            for rank, code, name, close, pct, amount, rank_change in rows
        ],
    )


def query_etf_activity(reader: EtfDailyLakeReader, *, today: date) -> EtfActivityResponseDto:
    deadline = monotonic() + _REQUEST_SECONDS
    files = reader.daily_files(through=today, deadline=deadline)
    latest = reader.calendar.latest_open_among(
        exchange=_EXCHANGE, days=tuple(files), timeout_seconds=remaining_etf_read_seconds(deadline),
    )
    if latest is None:
        return EtfActivityResponseDto(ranking=EtfActivityRankingDto(status="empty"))

    trade_date = latest.trade_date
    three_month_start = _months_before(trade_date, 3)
    warmup = reader.calendar.recent_open_rows(
        exchange=_EXCHANGE, bound=three_month_start, include_bound=False, limit=19,
        timeout_seconds=remaining_etf_read_seconds(deadline),
    )
    calendar_start = warmup[0].trade_date if warmup else three_month_start
    calendar = reader.calendar.range_rows(
        exchange=_EXCHANGE, start=calendar_start, end=trade_date,
        timeout_seconds=remaining_etf_read_seconds(deadline),
    )
    if len(calendar) != (trade_date - calendar_start).days + 1:
        raise EtfDailyReadError("DG 交易日历在 ETF 成交额计算区间内不连续")
    open_days = [row.trade_date for row in calendar if row.is_open]
    trend_files = {day: files[day] for day in open_days if day in files}
    paths = [str(path) for path in trend_files.values()]
    rows = reader.query_parquet(
        _TREND_SQL,
        [paths, list(trend_files), paths, open_days, three_month_start],
        columns_by_file={path: _DAILY_COLUMNS for path in trend_files.values()},
        deadline=deadline,
    )
    previous_date = open_days[-2] if len(open_days) > 1 else None
    try:
        ranking = _rank(reader, files, trade_date, previous_date, deadline)
    except (EtfDailyReadError, TimeoutError) as exc:
        _logger.warning("ETF 动态榜单读取失败，交易日 %s: %s", trade_date, exc)
        ranking = EtfActivityRankingDto(status="error", error=EtfActivityRankErrorDto())

    return EtfActivityResponseDto(
        tradeDate=trade_date,
        previousTradeDate=previous_date,
        oneMonthStartDate=_months_before(trade_date, 1),
        trend=[
            EtfActivityTrendPointDto(tradeDate=day, amountYuan=amount, ma5Yuan=ma5, ma20Yuan=ma20)
            for day, amount, ma5, ma20 in rows
        ],
        ranking=ranking,
    )
