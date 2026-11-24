"""Adapt a local HTTP minute window to one calculation request."""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from goldenshare_technical_indicators.contracts import CalculationRequest, CalculationResult
from goldenshare_technical_indicators.sources.contracts import CalculationWithSource

from src.biz.queries.wealth.market.index_detail_minutes.index_detail_minutes_query_service import (
    SHANGHAI,
    empty_index_minute_page,
)
from src.foundation.clients.local_lake.major_index_mins_contract import (
    GOLD_INDICATOR_VERSION,
    GOLD_PARAMS_KEY,
    IndexMinuteDataset,
)
from src.foundation.clients.local_lake.major_index_mins_reader import (
    IndexMinuteReadPage,
    IndexMinuteReadRequest,
    encode_index_minute_cursor,
    normalize_index_minute_read_request,
)


_MA_PERIODS = (5, 10, 20, 30, 60, 90, 250)
_INDICATOR_CALCULATIONS = (
    *({"calculation_id": "ma", "parameters": {"period": period}} for period in _MA_PERIODS),
    {"calculation_id": "boll", "parameters": {"period": 20, "multiplier": 2}},
    {"calculation_id": "macd", "parameters": {"fast": 12, "slow": 26, "signal": 9}},
    {"calculation_id": "kdj", "parameters": {"window": 9, "k_period": 3, "d_period": 3}},
)
_PRICE_CALCULATION = ({"calculation_id": "price", "parameters": {}},)
_PRICE_FIELDS = {
    "open": "open", "high": "high", "low": "low", "close": "close", "volume": "vol", "amount": "amount",
}
_INDICATOR_FIELDS = {
    "boll": {"middle": "boll_mid", "upper": "boll_upper", "lower": "boll_lower"},
    "macd": {"dif": "macd_dif", "dea": "macd_dea", "hist": "macd"},
    "kdj": {"k": "kdj_k", "d": "kdj_d", "j": "kdj_j"},
}


class IndexMinuteCalculationReader:
    def __init__(self, calculate: Callable[[CalculationRequest], CalculationWithSource]) -> None:
        self._calculate = calculate

    def read_bars(self, request: IndexMinuteReadRequest) -> IndexMinuteReadPage:
        return self._read(request, dataset="bars")

    def read_indicators(self, request: IndexMinuteReadRequest) -> IndexMinuteReadPage:
        return self._read(request, dataset="indicators")

    def _read(self, request: IndexMinuteReadRequest, *, dataset: IndexMinuteDataset) -> IndexMinuteReadPage:
        request, cursor = normalize_index_minute_read_request(request, dataset=dataset)
        start = datetime.combine(request.start_date, time.min, SHANGHAI) if request.start_date else None
        # Without an HTTP endDate, let the source find the latest available partition.
        end = datetime.combine(request.end_date or date.max, time.max, SHANGHAI)
        if cursor is not None:
            before = datetime.combine(
                date.fromisoformat(cursor["beforeTradeDate"]),
                time.fromisoformat(cursor["beforeTradeTime"]),
                SHANGHAI,
            )
            if before <= (start or datetime.min.replace(tzinfo=SHANGHAI)):
                return empty_index_minute_page()
            # The v1 cursor excludes its boundary; the calculation end includes it.
            end = min(end, before - timedelta(microseconds=1))

        calculated = self._calculate(CalculationRequest(
            security_type="index",
            ts_code=request.ts_code,
            period=f"{request.freq}m",
            adjustment="none",
            start=start,
            end=end,
            latest_rows=request.limit,
            calculations=_PRICE_CALCULATION if dataset == "bars" else _INDICATOR_CALCULATIONS,
        ))
        result = calculated.result
        if result is None:
            return empty_index_minute_page()

        columns = _result_columns(result)
        common = {"ts_code": request.ts_code, "freq": request.freq}
        if dataset == "bars":
            columns["exchange"] = calculated.source_facts.target_exchanges
        else:
            common.update(params_key=GOLD_PARAMS_KEY, indicator_version=GOLD_INDICATOR_VERSION)
        rows = tuple(
            {
                **common,
                "trade_time": timestamp,
                "trade_date": timestamp.date(),
                **dict(zip(columns, values, strict=True)),
            }
            for timestamp, *values in zip(result.times, *columns.values(), strict=True)
        )

        has_more = calculated.source_facts.has_more
        first, last = result.times[0], result.times[-1]
        return IndexMinuteReadPage(
            rows=rows,
            count=len(rows),
            has_more=has_more,
            next_cursor=encode_index_minute_cursor(
                dataset=dataset, request=request, before_trade_date=first.date(), before_trade_time=first,
            ) if has_more else None,
            observed_start_date=first.date(),
            observed_end_date=last.date(),
            scanned_file_count=result.statistics.source_files,
            elapsed_ms=result.statistics.elapsed_ms,
        )


def _result_columns(result: CalculationResult) -> dict:
    columns = {}
    for item in result.calculations:
        if item.calculation_id == "ma":
            names = {"value": f"ma_{dict(item.parameters)['period']}"}
        elif item.calculation_id == "price":
            names = _PRICE_FIELDS
        else:
            names = _INDICATOR_FIELDS[item.calculation_id]
        columns.update((names[field], values) for field, values in item.fields)
    return columns
