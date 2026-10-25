"""LLD 10/19.10: hand-calculable values, no production-generated expected.

The three canonical daily records are 10,12,11 with high=low=close. Input is
explicitly unadjusted; no factor is required. Timing alone is substituted.
"""

from dataclasses import replace
from datetime import date

from d3_support import assert_closed, close_enough, d3_data, request, values
from src.foundation.technical_indicators import CalculationInstance


def test_literal_formulas_initialization_and_period_edges(d3_data):
    state = d3_data
    with state.case("literal_formulas_and_period_edges"):
        calculations = tuple(CalculationInstance(identity, kind, parameters) for identity, kind, parameters in (
            ("price","price",{}),("ma2","ma",{"period":2}),("ma1","ma",{"period":1}),
            ("ma_large","ma",{"period":10001}),
            ("boll2","boll",{"period":2}),("boll0","boll",{"period":2,"multiplier":0}),
            ("boll11","boll",{"period":2,"multiplier":11}),("boll1","boll",{"period":1}),
            ("macd","macd",{"fast":2,"slow":3,"signal":2}),
            ("identity_macd","macd",{"fast":1,"slow":2,"signal":1}),
            ("kdj","kdj",{}),("flat_kdj","kdj",{"window":1,"k_period":1,"d_period":1}),
            ("same_ma2","ma",{"period":2}),
        ))
        config = replace(state.config, goldenshare_lake_root=str(state.literal_root))
        result, service, source = state.run(request(calculations, period="day", adjustment="none"), config=config)
        actual = values(result)
        assert result.times == (date(2026,1,5),date(2026,1,6),date(2026,1,7))
        assert result.range.count == 3 and source.batches == [3]
        assert result.msg == "" and result.source_as_of is None
        assert actual["ma2"]["value"] == actual["same_ma2"]["value"] == (None,11.0,11.5)
        assert actual["ma1"]["value"] == (10.0,12.0,11.0)
        assert actual["ma_large"]["value"] == (None,None,None)
        for identity, upper, lower in (("boll2",(None,13.0,12.5),(None,9.0,10.5)),
                                       ("boll0",(None,11.0,11.5),(None,11.0,11.5)),
                                       ("boll11",(None,22.0,17.0),(None,0.0,6.0))):
            assert actual[identity]["middle"] == (None,11.0,11.5)
            assert actual[identity]["upper"] == upper
            assert actual[identity]["lower"] == lower
        assert actual["boll1"]["upper"] == actual["boll1"]["lower"] == (10.0,12.0,11.0)
        close_enough(actual["macd"]["dif"], (0.0,0.3333333333333333,0.1111111111111111))
        close_enough(actual["macd"]["dea"], (0.0,0.2222222222222222,0.14814814814814814))
        close_enough(actual["macd"]["hist"], (0.0,0.2222222222222222,-0.07407407407407407))
        assert all(actual["macd"][name][0] == 0.0 for name in ("dif","dea","hist"))
        assert actual["identity_macd"]["dif"] == actual["identity_macd"]["dea"]
        assert actual["identity_macd"]["hist"] == (0.0,0.0,0.0)
        close_enough(actual["kdj"]["k"], (50.0,66.66666666666667,61.11111111111111))
        close_enough(actual["kdj"]["d"], (50.0,55.55555555555556,57.407407407407405))
        close_enough(actual["kdj"]["j"], (50.0,88.88888888888889,68.51851851851852))
        assert all(actual["flat_kdj"][name] == (50.0,50.0,50.0) for name in ("k","d","j"))
        # Two identical MA requests retain identities but use one dependency.
        assert sum(s.step_name=="rolling_mean" for s in service.observed_executor.statistics) == 3
        assert len(result.calculations) == 13
        assert_closed(service)
