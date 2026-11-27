"""Independent field literals for LLD §4.3.1; no source or algorithm is substituted."""

from goldenshare_technical_indicators.contracts import CalculationValues
from src.biz.services.wealth.market.stock_detail import stock_kline_factor_mapper as mapper


def test_ma_parameters_and_result_arrays_are_preserved():
    values = tuple(CalculationValues("ma", "1.0.0", (("period", period),), (("value", (value,)),))
                   for period, value in ((5, 5.1), (10, 10.2), (20, None), (30, 30.3),
                                         (60, 60.4), (90, 90.5), (250, 250.6)))
    results = mapper.build_stock_calculation_field_map(reversed(values))
    assert results[("ma", (("period", 5),))]["value"] is values[0].fields[0][1]
    assert mapper.build_stock_ma_factors(results, 0).model_dump() == {
        "ma5": 5.1, "ma10": 10.2, "ma20": None, "ma30": 30.3,
        "ma60": 60.4, "ma90": 90.5, "ma250": 250.6,
    }
    assert mapper.stock_calculation_key("macd", (("slow", 26), ("fast", 12))) == (
        "macd", (("fast", 12), ("slow", 26)),
    )


def test_individual_builders_use_the_correct_fields_and_current_row():
    assert mapper.build_stock_boll_factors({"upper": (1, 12.5), "middle": (2, 10.5), "lower": (3, None)}, 1).model_dump() == {
        "upper": 12.5, "middle": 10.5, "lower": None,
    }
    assert mapper.build_stock_macd_factors({"dif": (1, .3), "dea": (2, .4), "hist": (3, -.2)}, 1).model_dump() == {
        "dif": .3, "dea": .4, "macd": -.2,
    }
    assert mapper.build_stock_kdj_factors({"k": (1, 40), "d": (2, 50), "j": (3, 20)}, 1).model_dump() == {
        "k": 40, "d": 50, "j": 20,
    }
    assert mapper.build_stock_trend_channel_factors({
        "short_upper": (1, 12.25), "short_lower": (2, 9.5),
        "long_upper": (3, 11.75), "long_lower": (4, 8.25),
    }, 1).model_dump() == {
        "shortUpper": 12.25, "shortLower": 9.5, "longUpper": 11.75, "longLower": 8.25,
    }


def test_common_composition_calls_each_indicator_without_requiring_trend(monkeypatch):
    results = {("boll", ()): {"upper": (None,)}, ("macd", ()): {}, ("kdj", ()): {}}
    called = []
    for name in ("ma", "boll", "macd", "kdj"):
        def build(fields, index, name=name):
            called.append((name, fields, index))
            return name
        monkeypatch.setattr(mapper, f"build_stock_{name}_factors", build)
    assert mapper.build_stock_common_factors(results, 7) == {"ma": "ma", "boll": "boll", "macd": "macd", "kdj": "kdj"}
    assert [name for name, _, _ in called] == ["ma", "boll", "macd", "kdj"]
    assert called[0][1] is results and called[1][1] is results[("boll", ())]
