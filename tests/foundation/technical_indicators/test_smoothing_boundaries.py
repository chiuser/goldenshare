"""Three actual video parameter sets, using the original reference's first 500 rows.

Stop/clock control is substituted explicitly. Algorithm SQL and source reading
are real. Expected values are independent original-price HUGEINT recursion.
"""

from d3_support import (
    assert_closed, assert_templates_once, close_enough, d3_data,
    request, template_io, values,
)
from goldenshare_technical_indicators import CalculationInstance


def test_three_video_macd_parameter_sets_share_input_not_state(d3_data, monkeypatch):
    state = d3_data
    with state.case("three_video_macd_parameter_sets"):
        calculations = tuple(CalculationInstance(identity, "macd", parameters) for identity, parameters in (
            ("default",{}),("macd9",{"fast":9,"slow":65,"signal":9}),
            ("macd10",{"fast":10,"slow":69,"signal":10}),
        ))
        with template_io(state, monkeypatch):
            result, service, source = state.run(request(calculations, end=state.times[499], limit=500))
        assert source.batches == [500] and source.open_calls == 1
        assert result.times == state.times[:500] and result.statistics.source_rows == 500
        assert result.source.read_start == state.times[0] and result.source.read_end == state.times[499]
        actual = values(result)
        for identity, reference_key in (("default","macd"),("macd9","macd9"),("macd10","macd10")):
            reference = state.references[reference_key][:500]
            for column, name in enumerate(("dif","dea","hist"),1):
                close_enough(actual[identity][name], tuple(row[column] for row in reference))
                assert actual[identity][name][0] == 0.0
                for got, row in zip(actual[identity][name], reference):
                    if abs(row[column])>1e-8:
                        assert (got>0)==(row[column]>0)
        assert dict(result.calculations[1].parameters) == {"fast":9,"slow":65,"signal":9}
        assert dict(result.calculations[2].parameters) == {"fast":10,"slow":69,"signal":10}
        assert len({tuple(actual[identity]["dif"]) for identity in actual}) == 3
        assert_templates_once(state.calls[-1], {
            "smoothing_parameters.sql","macd_first.sql","macd_segment.sql","macd_warmup.sql",
            "merge_batch.sql","select_result.sql",
        })
        assert_closed(service)
