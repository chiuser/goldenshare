"""Build the monitored ETF turnover and closing quotes from the same DG daily rows."""

from datetime import date
import logging
from time import monotonic

from src.biz.queries.wealth.market.date_windows import months_before
from src.biz.schemas.wealth.market.major_etf_monitor import (
    MajorEtfMonitorResponseDto,
    MajorEtfQuoteDto,
    MajorEtfTrendPointDto,
)
from src.foundation.clients.local_lake.etf_daily_reader import (
    EtfDailyLakeReader,
    EtfDailyReadError,
    remaining_etf_read_seconds,
)

_logger = logging.getLogger(__name__)
_REQUEST_SECONDS = 5
_DAILY_COLUMNS = {"trade_date": "DATE", "ts_code": "VARCHAR", "amount": "DOUBLE", "close": "DOUBLE", "pct_chg": "DOUBLE"}
_BASIC_COLUMNS = {"ts_code": "VARCHAR", "csname": "VARCHAR", "extname": "VARCHAR", "cname": "VARCHAR"}
_WATCH_CODES = (
    "510300.SH", "510310.SH", "510330.SH", "159919.SZ", "510050.SH",
    "510500.SH", "512500.SH", "512100.SH", "159845.SZ", "560010.SH",
    "159629.SZ", "159915.SZ", "159977.SZ", "588000.SH",
)

_MONITOR_SQL = """
WITH watchlist AS (
    SELECT unnest(?::VARCHAR[]) AS ts_code, unnest(?::INTEGER[]) AS ordinal
), files AS (
    SELECT unnest(?::VARCHAR[]) AS filename, unnest(?::DATE[]) AS file_day
), daily AS MATERIALIZED (
    SELECT file_day, trade_date, ts_code, amount, close, pct_chg
    FROM read_parquet(?, filename=true, hive_partitioning=false)
    JOIN files USING (filename)
    SEMI JOIN watchlist USING (ts_code)
), latest AS (
    SELECT * FROM daily WHERE file_day = (SELECT max(file_day) FROM files)
), totals AS (
    SELECT file_day,
           CASE
             WHEN count(*) <> count(DISTINCT ts_code)
               OR count(*) FILTER (WHERE trade_date IS DISTINCT FROM file_day
                                      OR amount IS NULL OR NOT isfinite(amount) OR amount < 0) > 0
             THEN error('invalid monitored ETF daily partition')
             WHEN count(*) = (SELECT count(*) FROM watchlist) THEN fsum(amount) * 1000
           END AS amount_yuan
    FROM daily
    GROUP BY file_day
), names AS MATERIALIZED (
    SELECT ts_code, count(*) AS matched,
           min(coalesce(nullif(trim(csname), ''), nullif(trim(extname), ''), nullif(trim(cname), ''))) AS name
    FROM read_parquet(?, hive_partitioning=false)
    SEMI JOIN watchlist USING (ts_code)
    GROUP BY ts_code
)
SELECT (
    SELECT list(struct_pack(tradeDate := file_day, amountYuan := amount_yuan) ORDER BY file_day)
    FROM files LEFT JOIN totals USING (file_day)
), CASE
    WHEN EXISTS (SELECT 1 FROM names WHERE matched > 1) THEN error('duplicate monitored ETF basic code')
    WHEN EXISTS (
        SELECT 1 FROM latest
        WHERE close IS NULL OR NOT isfinite(close) OR close <= 0
           OR pct_chg IS NULL OR NOT isfinite(pct_chg)
    ) THEN error('invalid monitored ETF closing quote')
    ELSE (
        SELECT list(struct_pack(tsCode := ts_code, name := name, closePrice := close,
                                priceChangePct := pct_chg, amountYuan := amount * 1000) ORDER BY ordinal)
        FROM watchlist
        LEFT JOIN latest USING (ts_code)
        LEFT JOIN names USING (ts_code)
        WHERE EXISTS (SELECT 1 FROM latest)
    )
END
"""


def query_major_etf_monitor(
    reader: EtfDailyLakeReader, *, today: date, request_id: str | None,
) -> MajorEtfMonitorResponseDto:
    started_at = monotonic()
    deadline = started_at + _REQUEST_SECONDS
    stage = "ETF 日线分区枚举"
    trade_date = None
    try:
        files = reader.daily_files(through=today, deadline=deadline, require_directory=True)
        remaining_etf_read_seconds(deadline)
        if not files:
            return MajorEtfMonitorResponseDto(status="empty")
        trade_date = max(files)
        start = months_before(trade_date, 3)
        days = sorted(day for day in files if day >= start)
        paths = [str(files[day]) for day in days]

        stage = "同日 ETF 基础信息引用"
        basic_file = reader.basic_file(day=trade_date, daily_file=files[trade_date], deadline=deadline)
        stage = "DG Parquet 核对与计算"
        [(trend, quotes)] = reader.query_parquet(
            _MONITOR_SQL,
            [list(_WATCH_CODES), list(range(len(_WATCH_CODES))), paths, days, paths, str(basic_file)],
            columns_by_file={**{files[day]: _DAILY_COLUMNS for day in days}, basic_file: _BASIC_COLUMNS},
            deadline=deadline,
        )
    except (EtfDailyReadError, TimeoutError) as exc:
        _logger.warning(
            "主要ETF（国家队）监测读取失败 request_id=%s 阶段=%s 交易日=%s 耗时_ms=%.1f: %s",
            request_id, stage, trade_date, (monotonic() - started_at) * 1000, exc,
        )
        raise

    if not quotes and not any(point["amountYuan"] is not None for point in trend):
        return MajorEtfMonitorResponseDto(status="empty")
    return MajorEtfMonitorResponseDto(
        status="ready",
        tradeDate=trade_date,
        oneMonthStartDate=months_before(trade_date, 1),
        trend=[MajorEtfTrendPointDto(**point) for point in trend],
        quotes=[MajorEtfQuoteDto(**quote) for quote in (quotes or [])],
    )
