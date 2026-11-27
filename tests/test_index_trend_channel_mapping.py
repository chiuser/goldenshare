"""Literal contracts: CalculationValues and index Serving field names, no expected values from mappers."""

from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from goldenshare_technical_indicators.contracts import CalculationValues
from pydantic import ValidationError

from src.biz.queries.wealth.market.index_detail.index_detail_kline_query_service import (
    IndexDetailKlineQueryService,
)
from src.biz.services.wealth.market.index_detail import (
    index_detail_field_mapper as mapper,
)
from src.biz.services.wealth.market.index_detail.compose import common as compose_common
from src.biz.services.wealth.market.index_detail.compose.trend_channel import build_index_trend_channel_factors
from src.biz.services.wealth.market.index_detail.index_daily_kline_service import (
    IndexDailyKlineService, _split_daily_results,
)
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailQueryError,
)
from src.biz.services.wealth.market.index_detail.index_kline_calculations import (
    index_daily_calculations, index_period_calculations,
)
from src.biz.services.wealth.market.index_detail.index_kline_result import (
    count_calculated_kline_missing, validate_index_common_calculation_fields,
)


COMMON = (
    *(
        {"calculation_id": "ma", "parameters": {"period": n}}
        for n in (5, 10, 20, 30, 60, 90, 250)
    ),
    {"calculation_id": "boll", "parameters": {"period": 20, "multiplier": 2}},
    {"calculation_id": "macd", "parameters": {"fast": 12, "slow": 26, "signal": 9}},
    {
        "calculation_id": "kdj",
        "parameters": {"window": 9, "k_period": 3, "d_period": 3},
    },
)
RAILS = (
    ("short_upper", (13.5, 14.5)),
    ("short_lower", (8.5, 9.5)),
    ("long_upper", (15.5, 16.5)),
    ("long_lower", (6.5, 7.5)),
)
DAYS = (date(2026, 8, 6), date(2026, 8, 7))


def outputs(*, local):
    specs = (
        *COMMON,
        *(
            (
                {"calculation_id": "price", "parameters": {}},
                {"calculation_id": "nineturn", "parameters": {}},
            )
            if local
            else ()
        ),
    )
    return (
        *tuple(
            CalculationValues(
                s["calculation_id"],
                "2.0.0" if s["calculation_id"] in {"macd", "kdj"} else "1.0.0",
                tuple(s["parameters"].items()),
                (),
            )
            for s in specs
        ),
        CalculationValues("trend_channel", "1.0.0", (), RAILS),
    )


@pytest.mark.parametrize("local", [False, True])
def test_daily_list_preserves_common_order_and_appends_sse_only(local):
    aux = (
        (
            {"calculation_id": "price", "parameters": {}},
            {"calculation_id": "nineturn", "parameters": {}},
        )
        if local
        else ()
    )
    assert index_daily_calculations("000001.SH", include_price_and_nine_turn=local) == (
        *COMMON,
        *aux,
        {"calculation_id": "trend_channel", "parameters": {}},
    )
    for code in ("399001.SZ", "899050.BJ", "000510.SH"):
        assert index_daily_calculations(code, include_price_and_nine_turn=local) == (
            *COMMON,
            *aux,
        )
    result = SimpleNamespace(
        calculations=outputs(local=local), times=(date(2026, 8, 6), date(2026, 8, 7))
    )
    common, direct, fields = _split_daily_results(
        "000001.SH", result, include_price_and_nine_turn=local
    )
    assert [item.calculation_id for item in common] == ["ma"] * 7 + [
        "boll",
        "macd",
        "kdj",
    ]
    assert set(direct) == ({"price", "nineturn"} if local else set())
    assert fields["short_upper"] is result.calculations[-1].fields[0][1]


def test_period_list_starts_with_prices_and_keeps_common_order():
    assert index_period_calculations() == ({"calculation_id": "price", "parameters": {}}, *COMMON)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "parameters",
        "version",
        "field",
        "extra",
        "duplicate_field",
        "length",
        "null",
        "nan",
        "inf",
    ],
)
def test_complete_daily_contract_rejects_wrong_or_incomplete_results(fault):
    items = outputs(local=True)
    last = items[-1]
    if fault == "missing":
        items = items[:-1]
    elif fault == "duplicate":
        items = (*items, last)
    else:
        if fault == "parameters":
            last = replace(last, parameters=(("period", 90),))
        elif fault == "version":
            last = replace(last, algorithm_version="2")
        elif fault == "field":
            last = replace(last, fields=last.fields[:-1])
        elif fault == "extra":
            last = replace(last, fields=(*last.fields, ("state", (1.0, 1.0))))
        elif fault == "duplicate_field":
            last = replace(last, fields=(*last.fields, last.fields[0]))
        else:
            value = {
                "length": (1.0,),
                "null": (None, 2.0),
                "nan": (float("nan"), 2.0),
                "inf": (float("inf"), 2.0),
            }[fault]
            last = replace(last, fields=(("short_upper", value), *last.fields[1:]))
        items = (*items[:-1], last)
    with pytest.raises(IndexDetailQueryError):
        _split_daily_results(
            "000001.SH",
            SimpleNamespace(calculations=items, times=(1, 2)),
            include_price_and_nine_turn=True,
        )


def calculation_values(*, ma=None, boll=None, macd=None, kdj=None):
    columns = {
        "ma": {"value": (0.0, 0.0)},
        "boll": dict.fromkeys(("upper", "middle", "lower"), (0.0, 0.0)),
        "macd": dict.fromkeys(("dif", "dea", "hist"), (0.0, 0.0)),
        "kdj": dict.fromkeys(("k", "d", "j"), (0.0, 0.0)),
    }
    values = []
    for item in outputs(local=False)[:-1]:
        calculation_id = item.calculation_id
        if calculation_id == "ma":
            period = dict(item.parameters)["period"]
            fields = {**columns["ma"], **((ma or {}).get(period, {}))}
        else:
            fields = {**columns[calculation_id], **({"boll": boll, "macd": macd, "kdj": kdj}[calculation_id] or {})}
        values.append(replace(item, fields=tuple(fields.items())))
    return tuple(values)


def price_row(day):
    return {
        "trade_date": day,
        "high": 17,
        "low": 7,
        "pre_close": 10,
        "open": 12,
        "close": 14,
        "vol": 1234,
        "amount": 2345,
        "change": 4,
        "pct_change": 40,
    }


def test_per_indicator_mapping_and_typed_sse_serialization():
    row = price_row(DAYS[-1])
    precomputed_row = {
        **row,
        **{
            f"ma_bfq_{period}": value
            for period, value in zip(
                (5, 10, 20, 30, 60, 90, 250), (1, 2, 3, 4, 5, 6, None)
            )
        },
        "boll_upper_bfq": 18,
        "boll_mid_bfq": 12,
        "boll_lower_bfq": 6,
        "macd_dif_bfq": 1.2,
        "macd_dea_bfq": 0.7,
        "macd_bfq": 1,
        "kdj_k_bfq": 40,
        "kdj_d_bfq": 50,
        "kdj_bfq": 20,
    }
    values = calculation_values(
        ma={period: {"value": (-1.0, value)} for period, value in zip((5, 10, 20, 30, 60, 90, 250),
                                                                   (1, 2, 3, 4, 5, 6, None), strict=True)},
        boll={"upper": (-1, 18), "middle": (-1, 12), "lower": (-1, 6)},
        macd={"dif": (-1, 1.2), "dea": (-1, 0.7), "hist": (-1, 1)},
        kdj={"k": (-1, 40), "d": (-1, 50), "j": (-1, 20)},
    )
    calculated = SimpleNamespace(
        calculations=(*values, CalculationValues("trend_channel", "1.0.0", (), RAILS)),
        times=DAYS, range=SimpleNamespace(count=2),
    )
    page = IndexDailyKlineService.prepare_prod_result("000001.SH", [price_row(DAYS[0]), row], calculated, 0)
    context = SimpleNamespace(
        trade_date=DAYS[-1], prev_trade_date=DAYS[0], is_trading_day=True, session_status="CLOSED",
        generated_at=datetime(2026, 8, 7, 20, tzinfo=ZoneInfo("Asia/Shanghai")), source="explicit",
    )
    response, missing_count = IndexDailyKlineService.assemble(
        context=context, identity=SimpleNamespace(tsCode="000001.SH", name="上证指数"),
        page=page, start_date=None, limit=2, next_end=None, include_nine_turn=False,
    )
    assert missing_count == 0
    assert row == price_row(DAYS[-1])
    common = mapper.build_kline_bar(precomputed_row).model_dump(mode="json")
    sse = response.model_dump(mode="json")["bars"][1]
    assert sse.pop("factors") == {
        "ma": {
            "ma5": 1.0,
            "ma10": 2.0,
            "ma20": 3.0,
            "ma30": 4.0,
            "ma60": 5.0,
            "ma90": 6.0,
            "ma250": None,
        },
        "boll": {"upper": 18.0, "middle": 12.0, "lower": 6.0},
        "macd": {"dif": 1.2, "dea": 0.7, "macd": 1.0},
        "kdj": {"k": 40.0, "d": 50.0, "j": 20.0},
        "trendChannel": {
            "shortUpper": 14.5,
            "shortLower": 9.5,
            "longUpper": 16.5,
            "longLower": 7.5,
        },
    }
    common.pop("factors")
    assert sse == common
    assert sse["amplitude"] == 100 and sse["volDisplay"] == "0.12万"
    channel = build_index_trend_channel_factors(dict(RAILS), 1)
    with pytest.raises(ValidationError):
        type(channel).model_validate({"shortUpper": 1})


def test_common_builder_calls_only_named_common_indicators(monkeypatch):
    fields = validate_index_common_calculation_fields("000001.SH", calculation_values(), 2)
    for field in ("ma", "boll", "macd", "kdj"):
        monkeypatch.setattr(
            compose_common,
            f"build_index_{field}_factors",
            lambda _columns, index, field=field: (field, index),
        )
    assert compose_common.build_index_common_factors(fields, 1) == {
        name: (name, 1) for name in ("ma", "boll", "macd", "kdj")
    }


@pytest.mark.parametrize(("preceding_rows", "expected"), [(3, 3), (4, 4), (18, 6), (19, 8)])
def test_missing_count_preserves_ma_and_boll_thresholds(preceding_rows, expected):
    rows = [price_row(DAYS[0]), {**price_row(DAYS[1]), "vol": None}]
    values = calculation_values(
        ma={5: {"value": (None, None)}},
        boll={"upper": (None, None), "lower": (None, None)},
        macd={"dif": (0.0, None)},
    )
    fields = validate_index_common_calculation_fields("000001.SH", values, 2)
    assert count_calculated_kline_missing(rows, fields, preceding_rows) == expected


def test_complete_rows_with_zero_indicator_values_have_no_missing_fields():
    rows = [price_row(day) for day in DAYS]
    fields = validate_index_common_calculation_fields("000001.SH", calculation_values(), 2)
    assert count_calculated_kline_missing(rows, fields, 250) == 0


@pytest.mark.parametrize("hist_fields", [(), (("hist", (1.0,)),)])
def test_common_fields_reject_missing_or_short_hist(hist_fields):
    values = list(calculation_values())
    macd = values[-2]
    values[-2] = replace(macd, fields=(*macd.fields[:2], *hist_fields))
    with pytest.raises(IndexDetailQueryError, match=r"指标结果字段不完整：macd\.hist"):
        validate_index_common_calculation_fields("000001.SH", tuple(values), 2)


def test_common_fields_preserve_columns_and_allow_existing_extra_output():
    values = list(calculation_values())
    macd = values[-2]
    values[-2] = replace(macd, fields=(*macd.fields, ("extra", (1.0,))))
    fields = validate_index_common_calculation_fields("000001.SH", tuple(values), 2)
    macd_fields = fields[("macd", (("fast", 12), ("signal", 9), ("slow", 26)))]
    assert macd_fields["hist"] is values[-2].fields[2][1]
    assert macd_fields["extra"] == (1.0,)


@pytest.mark.parametrize(("times", "ohlc"), [(DAYS[:1], ((1, 2, 0, 1),) * 2), (DAYS, None)])
def test_prod_daily_checks_alignment_before_reading_auxiliary_prices(monkeypatch, times, ohlc):
    query = IndexDetailKlineQueryService()
    monkeypatch.setattr(query._query, "load_identity", lambda *_a, **_kw: {"ts_code": "000001.SH", "name": "上证指数"})
    monkeypatch.setattr(query._context_query, "resolve_sse_kline_context",
                        lambda *_a, **_kw: (None, tuple((day,) for day in DAYS)))
    monkeypatch.setattr(query, "_read_sse_auxiliary", lambda *_a: pytest.fail("辅助行情必须在对齐校验后读取"))
    with pytest.raises(IndexDetailQueryError, match="指标结果日期或根数与本页行情不一致"):
        query.query_kline(
            None, ts_code="000001.SH", period="day", start_date=None, end_date=DAYS[-1], limit=2,
            calculate=lambda _: (SimpleNamespace(times=times), 0, ohlc),
            source_origin=DAYS[0], check_active=lambda: None,
        )


def test_local_daily_checks_nine_turn_before_resolving_later_context(monkeypatch):
    query = IndexDetailKlineQueryService(daily_lake=SimpleNamespace(
        index_identity=lambda code: {"ts_code": code, "name": "上证指数"},
    ))
    monkeypatch.setattr(query._context_query, "resolve_local_context",
                        lambda *_a, **_kw: pytest.fail("无效九转必须在解析后续上下文之前拒绝"))
    items = list(outputs(local=True))
    items[-2] = replace(items[-2], fields=(("up_count", (14.0, 0.0)), ("down_count", (0.0, 0.0))))
    calculated = SimpleNamespace(
        result=SimpleNamespace(times=DAYS, range=SimpleNamespace(count=2), calculations=tuple(items)),
        source_facts=SimpleNamespace(calendar_days=(), target_bars=tuple(SimpleNamespace(trade_date=day) for day in DAYS)),
    )
    with pytest.raises(IndexDetailQueryError, match="九转计数无效"):
        query.query_kline(
            None, ts_code="000001.SH", period="day", start_date=None, end_date=DAYS[-1], limit=2,
            calculate_recent=lambda _end, _lower, _limit: calculated, check_active=lambda: None,
        )
