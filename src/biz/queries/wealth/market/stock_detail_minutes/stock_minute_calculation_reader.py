"""Translate the stock minute HTTP window to one indicator calculation."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from time import perf_counter
from typing import Literal
from zoneinfo import ZoneInfo

from goldenshare_technical_indicators.contracts import CalculationRequest
from goldenshare_technical_indicators.sources.contracts import CalculationWithSource

from src.biz.queries.wealth.market.stock_detail_minutes.stock_detail_minutes_query import (
    StockMinuteQueryWindow,
    resolve_stock_minute_query_window,
)
from src.foundation.clients.local_lake.nine_turn_minute_contract import decode_nine_turn_minute_cursor
from src.foundation.clients.local_lake.stock_mins_reader import (
    MAX_YEAR_FILE_COUNT,
    MinuteReadPage,
    MinuteReadRequest,
    MinuteRequestError,
    decode_stock_minute_cursor,
    encode_stock_minute_cursor,
    normalize_stock_minute_code,
    validate_stock_minute_frequency,
)
from src.foundation.clients.local_lake.stock_nine_turn_contract import SUPPORTED_STOCK_NINE_TURN_FREQS


StockMinuteOutput = Literal["chart", "indicators", "nine_turn"]
SHANGHAI = ZoneInfo("Asia/Shanghai")
NINE_TURN_DATASET = "stock_minute_nine_turn"
STOCK_MINUTE_SOURCES = ("silver/quote/stk_mins", "silver/quote/adj_factor")
PARAMS_KEY = "macd_12_26_9__kdj_9_3_3"
INDICATOR_VERSION = 1

_PRICE = {"calculation_id": "price", "parameters": {}}
_INDICATORS = (
    {"calculation_id": "macd", "parameters": {"fast": 12, "slow": 26, "signal": 9}},
    {"calculation_id": "kdj", "parameters": {"window": 9, "k_period": 3, "d_period": 3}},
)
_NINE_TURN = {"calculation_id": "nineturn", "parameters": {}}
_RESULT_FIELDS = {
    "price": {
        "open": "open", "high": "high", "low": "low", "close": "close", "volume": "vol", "amount": "amount",
    },
    "macd": {"dif": "macd_dif_qfq", "dea": "macd_dea_qfq", "hist": "macd_qfq"},
    "kdj": {"k": "kdj_k_qfq", "d": "kdj_d_qfq", "j": "kdj_qfq"},
    "nineturn": {"up_count": "up_count", "down_count": "down_count"},
}


class StockMinuteCalculationReader:
    def __init__(self, calculate: Callable[[CalculationRequest], CalculationWithSource]) -> None:
        self._calculate = calculate

    def read(
        self, request: MinuteReadRequest, *, output: StockMinuteOutput,
    ) -> tuple[MinuteReadPage, StockMinuteQueryWindow]:
        try:
            window = resolve_stock_minute_query_window(
                start_date=request.start_date, end_date=request.end_date, today=datetime.now(SHANGHAI).date(),
            )
        except ValueError as exc:
            raise MinuteRequestError(str(exc)) from exc

        request = replace(
            request, ts_code=normalize_stock_minute_code(request.ts_code),
            freq=validate_stock_minute_frequency(request.freq),
        )
        first_day = window.start_date or date(window.query_end_date.year - MAX_YEAR_FILE_COUNT + 1, 1, 1)
        if first_day > window.query_end_date or window.query_end_date.year - first_day.year >= MAX_YEAR_FILE_COUNT:
            raise MinuteRequestError("分钟查询最多允许涉及 3 个自然年，且起日不能晚于截止日。")
        if output != "nine_turn" and (first_day.year < 2000 or window.query_end_date.year > 2100):
            raise MinuteRequestError("分钟查询年份不合法。")
        start = datetime.combine(first_day, time.min, SHANGHAI)
        end = datetime.combine(window.query_end_date, time.max, SHANGHAI)
        dataset = "bars" if output == "chart" else "indicators"
        cursor_request = replace(request, end_date=window.query_end_date)
        if output == "nine_turn":
            cursor = decode_nine_turn_minute_cursor(
                request.cursor, dataset=NINE_TURN_DATASET, subject_type="stock",
                ts_code=request.ts_code, freq=request.freq, start_date=request.start_date, end_date=request.end_date,
            )
        else:
            cursor = _read_bars_cursor(cursor_request, dataset)
        if cursor is not None:
            before = datetime.combine(
                date.fromisoformat(cursor["beforeTradeDate"]), time.fromisoformat(cursor["beforeTradeTime"]), SHANGHAI,
            )
            if before <= start:
                return _empty_page(), window
            # The existing cursor is exclusive. The calculation end is inclusive.
            end = min(end, before - timedelta(microseconds=1))

        started = perf_counter()
        calculated = self._calculate(CalculationRequest(
            security_type="stock", ts_code=request.ts_code, period=f"{request.freq}m", adjustment="qfq",
            start=start, end=end, latest_rows=request.limit, calculations=stock_minute_calculations(request.freq, output),
        ))
        result = calculated.result
        if result is None:
            return _empty_page(
                scanned_file_count=calculated.source_facts.scanned_file_count, elapsed_ms=(perf_counter() - started) * 1000,
            ), window

        columns = {
            _RESULT_FIELDS[item.calculation_id][field]: values
            for item in result.calculations
            for field, values in item.fields
        }
        common = {"ts_code": request.ts_code, "freq": request.freq}
        if output == "chart":
            columns["exchange"] = calculated.source_facts.target_exchanges
        if output != "nine_turn":
            common.update(params_key=PARAMS_KEY, indicator_version=INDICATOR_VERSION)
        # Counts in the response policy are integers. The operator returns DOUBLE for all indicators.
        for name in ("up_count", "down_count"):
            if name in columns:
                columns[name] = tuple(map(int, columns[name]))
        if "up_count" in columns:
            common["nine_turn_matched"] = True
        rows = tuple(
            {**common, "trade_time": stamp, "trade_date": stamp.date(), **dict(zip(columns, values, strict=True))}
            for stamp, *values in zip(result.times, *columns.values(), strict=True)
        )
        has_more = calculated.source_facts.has_more
        first, last = result.times[0], result.times[-1]
        next_cursor = None
        if has_more and output != "nine_turn":
            next_cursor = encode_stock_minute_cursor(
                dataset=dataset, request=cursor_request, before_trade_date=first.date(), before_trade_time=first,
            )
        return MinuteReadPage(
            rows=rows, count=len(rows), has_more=has_more, next_cursor=next_cursor,
            observed_start_date=first.date(), observed_end_date=last.date(),
            scanned_file_count=result.statistics.source_files, elapsed_ms=result.statistics.elapsed_ms,
        ), window


def stock_minute_calculations(freq: int, output: StockMinuteOutput) -> tuple[dict, ...]:
    if output == "nine_turn":
        return (_NINE_TURN,)
    if output == "indicators":
        return _INDICATORS
    if freq in SUPPORTED_STOCK_NINE_TURN_FREQS:
        return (_PRICE, *_INDICATORS, _NINE_TURN)
    return (_PRICE, *_INDICATORS)


def _read_bars_cursor(request: MinuteReadRequest, dataset: str) -> dict | None:
    if not request.cursor:
        return None
    cursor = decode_stock_minute_cursor(request.cursor)
    expected = {
        "dataset": dataset, "tsCode": request.ts_code, "freq": request.freq,
        "startDate": request.start_date.isoformat() if request.start_date else None,
        "endDate": request.end_date.isoformat(),
    }
    for key, value in expected.items():
        if cursor[key] != value:
            raise MinuteRequestError(f"cursor 与当前 {key} 不匹配。")
    return cursor


def _empty_page(*, scanned_file_count: int = 0, elapsed_ms: float = 0) -> MinuteReadPage:
    return MinuteReadPage(
        rows=(), count=0, has_more=False, next_cursor=None,
        observed_start_date=None, observed_end_date=None, scanned_file_count=scanned_file_count, elapsed_ms=elapsed_ms,
    )
