"""Stock daily integration LLD §04–06, §16.2; A contracts only in this stage.

Dates, parameter tuples and errors below are independent LLD literals. No DB,
source, calculation, Control or Web app is opened; C will cover prepare/assemble.
"""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.biz.api.wealth.market.stock_detail_dependencies import get_stock_daily_kline_backend
from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContext
from src.biz.services.wealth.market.stock_detail.stock_daily_kline_calculations import (
    STOCK_DAILY_ALGORITHM_VERSIONS, STOCK_DAILY_CALCULATIONS, STOCK_DAILY_OUTPUT_FIELDS,
    build_calculation_request, validate_stock_daily_request,
)
from src.biz.services.wealth.market.stock_detail.stock_daily_kline_contracts import (
    StockDailyKlineInput, StockDailyKlinePage, StockDailyKlineRequest, StockDailyKlineRow,
)
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry


def _request(**overrides):
    return replace(StockDailyKlineRequest(
        "600000.SH", "day", "forward", None, None, None, 300, False,
    ), **overrides)


def _row(day):
    return StockDailyKlineRow(day, 10.0, 11.0, 9.0, 10.0, 10.0, 0.0, 0.0,
                             100.0, 1000.0, None, None)


def _source(bars, request=None):
    context = MarketPageContext(
        "CN_A", date(2026, 1, 9), date(2026, 1, 8), True, "CLOSED",
        datetime(2026, 1, 9, 16, tzinfo=ZoneInfo("Asia/Shanghai")), "explicit",
    )
    return StockDailyKlineInput(
        request or _request(), context, "600000.SH", "浦发银行", date(2026, 1, 9), bars,
    )


def test_request_and_fixed_calculations():
    expected = (
        ("ma5", "ma", {"period": 5}), ("ma10", "ma", {"period": 10}),
        ("ma20", "ma", {"period": 20}), ("ma30", "ma", {"period": 30}),
        ("ma60", "ma", {"period": 60}), ("ma90", "ma", {"period": 90}),
        ("ma250", "ma", {"period": 250}),
        ("boll", "boll", {"period": 20, "multiplier": 2}),
        ("macd", "macd", {"fast": 12, "slow": 26, "signal": 9}),
        ("kdj", "kdj", {"window": 9, "k_period": 3, "d_period": 3}),
        ("price", "price", {}), ("trend_channel", "trend_channel", {}),
    )
    assert tuple((item["calculation_id"], dict(item["parameters"])) for item in STOCK_DAILY_CALCULATIONS
                 ) == tuple((kind, params) for _, kind, params in expected)
    assert dict(STOCK_DAILY_ALGORITHM_VERSIONS) == {
        "ma": "1.0.0", "boll": "1.0.0", "macd": "2.0.0", "kdj": "2.0.0", "price": "1.0.0",
        "nineturn": "1.0.0", "trend_channel": "1.0.0",
    }
    assert dict(STOCK_DAILY_OUTPUT_FIELDS) == {
        "ma": ("value",), "boll": ("middle", "upper", "lower"),
        "macd": ("dif", "dea", "hist"), "kdj": ("k", "d", "j"),
        "price": ("open", "high", "low", "close", "volume", "amount"),
        "nineturn": ("up_count", "down_count"),
        "trend_channel": ("short_upper", "short_lower", "long_upper", "long_lower"),
    }
    registry = create_builtin_registry()
    for item in STOCK_DAILY_CALCULATIONS:
        definition = registry.resolve(item["calculation_id"])
        definition.validate_parameters(item["parameters"])
        assert "day" in definition.supported_periods
        assert definition.algorithm_version == STOCK_DAILY_ALGORITHM_VERSIONS[item["calculation_id"]]
        assert tuple(field.name for field in definition.output_fields) == STOCK_DAILY_OUTPUT_FIELDS[item["calculation_id"]]
    for changed, message in (
        ({"period": "week", "adjustment": "qfq", "limit": 0}, "股票详情首期只支持 period=day"),
        ({"adjustment": "qfq", "limit": 0}, "股票详情首期只支持 adjustment=forward"),
        ({"limit": 0}, "limit 必须在 1 到 500 之间"),
        ({"limit": 501}, "limit 必须在 1 到 500 之间"),
        ({"start_date": date(2026, 1, 9), "end_date": date(2026, 1, 8)}, "startDate 不能晚于 endDate"),
    ):
        with pytest.raises(ValueError) as caught:
            validate_stock_daily_request(_request(**changed))
        assert str(caught.value) == message
    for limit in (1, 300, 500):
        validate_stock_daily_request(_request(ts_code="UNKNOWN", limit=limit))
    # The old rule compares explicit start/end only, not the eventual context.
    validate_stock_daily_request(_request(start_date=date(2026, 1, 12)))
    source = _source((_row(date(2026, 1, 5)), _row(date(2026, 1, 6))))
    calculation = build_calculation_request(source)
    assert (calculation.security_type, calculation.ts_code, calculation.period,
            calculation.adjustment, calculation.start, calculation.end) == (
        "stock", "600000.SH", "day", "qfq",
        datetime(2026, 1, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
        datetime(2026, 1, 6, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert calculation.calculations == STOCK_DAILY_CALCULATIONS
    local = build_calculation_request(source, include_nine_turn=True)
    assert local.calculations == (*STOCK_DAILY_CALCULATIONS[:-1],
                                  {"calculation_id": "nineturn", "parameters": {}}, STOCK_DAILY_CALCULATIONS[-1])
    assert source.request.limit == 300 and source.query_end_date == date(2026, 1, 9)
    assert build_calculation_request(_source(())) is None


def test_input_is_detached_and_immutable():
    row = _row(date(2026, 1, 5))
    original = [row]
    source = _source(original)
    original.append(_row(date(2026, 1, 6)))
    assert source.bars == (row,) and isinstance(source.bars, tuple)
    assert source.bars[0].turnover_rate is None
    for target, attribute, replacement in (
        (source, "bars", ()), (source.request, "limit", 1),
        (row, "close_qfq", 12.0), (source.context, "source", "default"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(target, attribute, replacement)
    with pytest.raises(TypeError):
        STOCK_DAILY_CALCULATIONS[0]["parameters"]["period"] = 30
    with pytest.raises(TypeError):
        STOCK_DAILY_ALGORITHM_VERSIONS["ma"] = "other"
    with pytest.raises(TypeError):
        STOCK_DAILY_OUTPUT_FIELDS["ma"] = ("other",)
    with pytest.raises(TypeError):
        _source([{"trade_date": date(2026, 1, 5)}])
    with pytest.raises(TypeError):
        replace(source, context={})
    with pytest.raises(TypeError):
        replace(row, close_qfq=[])
    with pytest.raises(TypeError):
        _request(trade_date=datetime(2026, 1, 5))
    with pytest.raises(RuntimeError, match="Stock daily kline backend is not installed"):
        get_stock_daily_kline_backend()


def test_mapping_and_legal_nulls(monkeypatch):
    from dataclasses import asdict
    from decimal import Decimal
    from types import SimpleNamespace
    from src.biz.services.wealth.market.stock_detail.stock_daily_kline_service import StockDailyKlineService
    from tests.stock_daily_kline_helpers import result_for

    service = StockDailyKlineService()
    source_tables = ("core_serving.security_serving", "core_serving.equity_factor_pro")
    source = _source((_row(date(2026, 1, 5)), _row(date(2026, 1, 6))), _request(debug=True))
    order = []
    query = service._query
    monkeypatch.setattr(query._context_query, "resolve_context", lambda session, **kw: (
        order.append(("context", kw)) or source.context))
    monkeypatch.setattr(query._query, "load_security", lambda session, **kw: (
        order.append(("security", kw)) or SimpleNamespace(ts_code="600000.SH", name="浦发银行")))
    rows = [asdict(row) | {"ts_code": "600000.SH"} for row in source.bars]
    rows[0]["pre_close"] = Decimal("10.00000000001")
    monkeypatch.setattr(query._query, "load_kline_rows", lambda session, **kw: (
        order.append(("bars", kw)) or rows))
    load_rows = lambda code, end, start, count: StockDailyKlinePage(query._query.load_kline_rows(
        object(), ts_code=code, end_date=end, start_date=start, limit=count,
    ))
    prepared = service.prepare(object(), source.request, load_rows=load_rows)
    assert [name for name, _ in order] == ["context", "security", "bars"]
    assert order[-1][1] == {"ts_code": "600000.SH", "end_date": date(2026, 1, 9),
                            "start_date": None, "limit": 300}
    assert type(prepared.bars[0].pre_close) is float
    assert prepared.bars[0].pre_close == 10.00000000001  # no early rounding
    rows[0]["pre_close"] = 999
    assert prepared.bars[0].pre_close == 10.00000000001
    del rows[0]["change"]
    with pytest.raises(KeyError, match="change"):
        service.prepare(object(), source.request, load_rows=load_rows)

    result = result_for(source.ts_code, (date(2026, 1, 5), date(2026, 1, 6)), {
        ("ma250", "value"): None, ("boll", "middle"): None,
        ("macd", "hist"): 0.3333333333333, ("kdj", "j"): 77.7,
    })
    payload = service.assemble(source, result, source_tables=source_tables).model_dump(mode="json")
    assert payload["meta"] == {"count": 2, "limit": 300, "startDate": None, "endDate": "2026-01-09"}
    assert payload["dataStatus"]["status"] == "DELAYED"
    bar = payload["bars"][0]
    assert (bar["open"], bar["high"], bar["low"], bar["close"], bar["amplitude"]) == (10, 11, 9, 10, 20)
    assert (bar["vol"], bar["volDisplay"], bar["amount"], bar["turnoverRate"]) == (100, "0.01万", 1000, None)
    assert bar["factors"]["ma"]["ma250"] is None and bar["factors"]["boll"]["middle"] is None
    assert bar["factors"]["macd"]["macd"] == 0.3333333333
    assert bar["factors"]["kdj"]["j"] == 77.7
    assert payload["debugInfo"]["sourceTables"] == list(source_tables)
    assert "msg" not in payload
    empty = service.assemble(replace(source, bars=()), None, source_tables=source_tables).model_dump(mode="json")
    assert empty["bars"] == [] and empty["meta"]["count"] == 0 and empty["dataStatus"]["status"] == "EMPTY"
    assert len(empty["debugInfo"]["sourceTables"]) == 2
    assert service.assemble(replace(source, request=_request()), result, source_tables=source_tables).debugInfo is None


def test_result_contract_errors():
    from src.biz.services.wealth.market.stock_detail.stock_daily_kline_service import StockDailyKlineService
    from goldenshare_technical_indicators.errors import OutputContractError
    from tests.stock_daily_kline_helpers import result_for

    source = _source((_row(date(2026, 1, 5)), _row(date(2026, 1, 6))))
    result = result_for(source.ts_code, (date(2026, 1, 5), date(2026, 1, 6)))
    service = StockDailyKlineService()
    source_tables = ("core_serving.security_serving", "core_serving.equity_factor_pro")
    assert len(service.assemble(source, result, source_tables=source_tables).bars) == 2
    calculations = result.calculations
    missing_field = replace(calculations[-1], fields=calculations[-1].fields[:-1])
    wrong_version = replace(calculations[-1], algorithm_version="other")
    missing_value = replace(calculations[-1], fields=(("short_upper", (None, 10.0)),) + calculations[-1].fields[1:])
    for broken, reason in (
        (replace(result, times=result.times[:-1]), "time_mismatch"),
        (replace(result, calculations=calculations[:-1] + (missing_field,)), "fields_mismatch"),
        (replace(result, calculations=calculations[:-1] + (wrong_version,)), "definition_mismatch"),
        (replace(result, calculations=calculations[:-1] + (missing_value,)), "unexpected_null"),
    ):
        with pytest.raises(OutputContractError) as caught:
            service.assemble(source, broken, source_tables=source_tables)
        assert caught.value.reason == reason and caught.value.stage == "stock_daily_assemble"
        assert not any(isinstance(value, type(result)) for value in caught.value.diagnostics.values())


def test_local_nine_turn_marks_only_one_through_nine_in_date_order():
    from datetime import timedelta
    from goldenshare_technical_indicators.contracts import CalculationValues
    from src.biz.services.wealth.market.stock_detail.stock_daily_kline_service import StockDailyKlineService
    from tests.stock_daily_kline_helpers import result_for

    days = tuple(date(2026, 1, 5) + timedelta(days=index) for index in range(6))
    source = _source(tuple(map(_row, days)))
    baseline = result_for(source.ts_code, days)
    counts = CalculationValues("nineturn", "1.0.0", (), (
        ("up_count", (0.0, 1.0, 0.0, 10.0, 13.0, 0.0)),
        ("down_count", (0.0, 0.0, 9.0, 0.0, 0.0, 8.0)),
    ))
    result = replace(baseline, calculations=(*baseline.calculations, counts))
    service = StockDailyKlineService()
    payload = service.assemble(source, result, paginated=True, source_tables=()).model_dump(mode="json")
    assert "nineTurnMarkers" not in service.assemble(source, baseline, source_tables=()).model_dump()
    assert payload["nineTurnMarkers"] == [
        {"tradeDate": days[1].isoformat(), "tradeTime": None, "direction": "UP", "sequenceNumber": 1, "completed": False},
        {"tradeDate": days[2].isoformat(), "tradeTime": None, "direction": "DOWN", "sequenceNumber": 9, "completed": True},
        {"tradeDate": days[5].isoformat(), "tradeTime": None, "direction": "DOWN", "sequenceNumber": 8, "completed": False},
    ]


@pytest.mark.parametrize(("fields", "reason"), [
    ((("up_count", (None,)), ("down_count", (0,))), "invalid_value"),
    ((("up_count", (1.5,)), ("down_count", (0,))), "invalid_value"),
    ((("up_count", (14,)), ("down_count", (0,))), "invalid_value"),
    ((("up_count", (1,)), ("down_count", (1,))), "invalid_value"),
    ((("up_count", (1,)),), "fields_mismatch"),
    ((("up_count", ()), ("down_count", (0,))), "value_count_mismatch"),
])
def test_local_nine_turn_rejects_invalid_results(fields, reason):
    from goldenshare_technical_indicators.contracts import CalculationValues
    from goldenshare_technical_indicators.errors import OutputContractError
    from src.biz.services.wealth.market.stock_detail.stock_daily_kline_service import StockDailyKlineService
    from tests.stock_daily_kline_helpers import result_for

    day = date(2026, 1, 5)
    source = _source((_row(day),))
    result = result_for(source.ts_code, (day,))
    broken = replace(result, calculations=(*result.calculations, CalculationValues("nineturn", "1.0.0", (), fields)))
    with pytest.raises(OutputContractError) as error:
        StockDailyKlineService().assemble(source, broken, paginated=True, source_tables=())
    assert error.value.reason == reason


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True])
def test_trend_channel_rejects_invalid_rails(value):
    from src.biz.services.wealth.market.stock_detail.stock_daily_kline_service import StockDailyKlineService
    from goldenshare_technical_indicators.errors import OutputContractError
    from tests.stock_daily_kline_helpers import result_for

    source = _source((_row(date(2026, 1, 5)),))
    result = result_for(source.ts_code, (date(2026, 1, 5),), {("trend_channel", "long_upper"): value})
    with pytest.raises(OutputContractError):
        StockDailyKlineService().assemble(source, result, source_tables=())


def test_daily_trend_mapping_keeps_all_four_distinct_values_and_schema():
    from src.biz.services.wealth.market.stock_detail.stock_daily_kline_service import StockDailyKlineService
    from src.biz.schemas.wealth.market.stock_detail import StockDetailKlineResponseDto, StockDetailPeriodKlineResponseDto
    from tests.stock_daily_kline_helpers import result_for

    source = _source((_row(date(2026, 1, 5)),))
    # Independent mapping literals, not indicator arithmetic or a builder-derived expected.
    rails = {"short_upper": 11.25, "short_lower": 9.5, "long_upper": 10.75, "long_lower": 9.25}
    result = result_for(source.ts_code, (date(2026, 1, 5),), {("trend_channel", k): v for k, v in rails.items()})
    payload = StockDailyKlineService().assemble(source, result, source_tables=()).model_dump(mode="json")
    assert payload["bars"][0]["factors"]["trendChannel"] == {
        "shortUpper": 11.25, "shortLower": 9.5, "longUpper": 10.75, "longLower": 9.25,
    }
    schema = StockDetailKlineResponseDto.model_json_schema()
    assert "trendChannel" in schema["$defs"]["StockDailyKlineFactorDto"]["required"]
    assert schema["$defs"]["StockTrendChannelFactorsDto"]["required"] == [
        "shortUpper", "shortLower", "longUpper", "longLower",
    ]
    period_schema = StockDetailPeriodKlineResponseDto.model_json_schema()
    assert "trendChannel" not in period_schema["$defs"]["StockKlineFactorDto"]["properties"]


@pytest.mark.parametrize("mode", ["missing", "duplicate", "wrong parameters"])
def test_daily_requires_exactly_one_parameterless_trend_result(mode):
    from src.biz.services.wealth.market.stock_detail.stock_daily_kline_service import StockDailyKlineService
    from goldenshare_technical_indicators.errors import OutputContractError
    from tests.stock_daily_kline_helpers import result_for

    source = _source((_row(date(2026, 1, 5)),))
    result = result_for(source.ts_code, (date(2026, 1, 5),))
    channel = result.calculations[-1]
    if mode == "missing":
        calculations = result.calculations[:-1]
    elif mode == "duplicate":
        calculations = (*result.calculations, channel)
    else:
        calculations = (*result.calculations[:-1], replace(channel, parameters=(("period", 25),)))
    with pytest.raises(OutputContractError) as caught:
        StockDailyKlineService().assemble(source, replace(result, calculations=calculations), source_tables=())
    assert caught.value.reason == "instances_mismatch"
