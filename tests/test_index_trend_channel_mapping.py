"""Literal contracts: CalculationValues and index Serving field names, no expected values from mappers."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest
from goldenshare_technical_indicators.contracts import CalculationValues
from pydantic import ValidationError

from src.biz.queries.wealth.market.index_detail.index_detail_kline_query_service import (
    _split_daily_results,
    index_daily_calculations,
)
from src.biz.services.wealth.market.index_detail import (
    index_detail_field_mapper as mapper,
)
from src.biz.services.wealth.market.index_detail.index_detail_universe import (
    IndexDetailQueryError,
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


def test_per_indicator_mapping_and_typed_sse_serialization():
    row = {
        "trade_date": date(2026, 8, 7),
        "high": 17,
        "low": 7,
        "pre_close": 10,
        "open": 12,
        "close": 14,
        "vol": 1234,
        "amount": 2345,
        "change": 4,
        "pct_change": 40,
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
    common = mapper.build_kline_bar(row).model_dump(mode="json")
    channel = mapper.build_index_trend_channel_factors(dict(RAILS), 1)
    sse = mapper.build_index_sse_daily_kline_bar(row, channel).model_dump(mode="json")
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
    with pytest.raises(ValidationError):
        type(channel).model_validate({"shortUpper": 1})


def test_common_builder_calls_only_named_common_indicators(monkeypatch):
    for field in ("ma", "boll", "macd", "kdj"):
        monkeypatch.setattr(
            mapper,
            f"build_index_{field}_factors",
            lambda row, field=field: (field, row),
        )
    monkeypatch.setattr(
        mapper,
        "build_index_trend_channel_factors",
        lambda *args: pytest.fail("common factors must not request trend"),
    )
    assert mapper.build_index_common_factors("row") == {
        name: (name, "row") for name in ("ma", "boll", "macd", "kdj")
    }
