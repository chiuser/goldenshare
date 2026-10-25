"""LLD 18.1/19.10: exactly two real requests, one finite source/reference.

Canonical minute schema follows the actual producer's MINUTE_SCHEMA. The
read-range and page boundaries are independently specified; no formal lake is
used. Default/reference SQL is generated once by the shared finite fixture.
"""

from collections import Counter

from d3_support import (
    assert_closed, assert_templates_once, close_enough, d3_data,
    default_calculations, request, template_io, values,
)


CALCULATION_FILES = {
    "smoothing_parameters.sql", "rolling_mean.sql", "bollinger_bands.sql",
    "macd_first.sql", "macd_segment.sql", "kdj_window.sql", "kdj_segment.sql",
}
OUTPUT_FILES = {"merge_batch.sql", "retain_tail.sql", "select_result.sql"}


def _compare_page(result, state, start, end):
    assert result.times == state.times[start:end]
    assert result.range.count == len(result.times) == 1000
    assert result.range.actual_start == result.times[0]
    assert result.range.actual_end == result.times[-1]
    assert result.source.read_start == state.times[0]
    assert result.source.read_end == state.times[end-1]
    assert result.source.read_start != result.range.actual_start
    assert result.msg == "" and result.source_as_of is None
    actual = values(result)
    for identity in ("macd", "kdj"):
        reference = state.references[identity][start:end]
        for column, name in enumerate(("dif", "dea", "hist") if identity=="macd" else ("k", "d", "j"), 1):
            close_enough(actual[identity][name], tuple(row[column] for row in reference))
            if identity == "macd":
                for got, row in zip(actual[identity][name], reference):
                    want = row[column]
                    if abs(want)>1e-8:
                        assert (got>0) == (want>0)
    reference = state.references["windows"][start:end]
    for column, period in enumerate((5,10,20,30,60,90,250), 4):
        close_enough(actual["ma"+str(period)]["value"], tuple(row[column] for row in reference))
    for name, column in (("middle",11),("upper",13),("lower",14)):
        close_enough(actual["boll"][name], tuple(row[column] for row in reference))
    for name, column in (("open",1),("close",1),("high",2),("low",3)):
        close_enough(actual["price"][name], tuple(row[column] for row in reference))
    assert actual["price"]["volume"] == (100.0,)*1000
    assert actual["price"]["amount"] == (1000.0,)*1000
    assert len(result.calculations) == 11
    assert dict(result.calculations[0].parameters) == {"fast":12,"slow":26,"signal":9}
    assert all(item.algorithm_version == "1.0.0" for item in result.calculations)


def test_complete_service_initial_and_before(d3_data, monkeypatch):
    state = d3_data
    with state.case("initial_and_before"):
        with template_io(state, monkeypatch):
            initial, service, source = state.run(request(default_calculations()), real=True)
            assert initial.statistics.source_rows == 10001
            assert initial.statistics.source_data_passes == 1
            assert initial.statistics.price_conversion_batches == 0
            assert source.batches == [8192,1809] and source.open_calls == 1
            _compare_page(initial, state, 9001, 10001)
            assert_closed(service)
            assert_templates_once(state.calls[-1], CALCULATION_FILES|OUTPUT_FILES)
            # One unique MA20/BOLL20 mean is executed once for each real batch.
            steps = service.observed_executor.statistics
            assert sum(s.step_name == "rolling_mean" for s in steps) == 14
            # The second batch includes 249 prior rows; neither replay nor a
            # reset at 8193 can match this independently computed prefix.
            segment_rows = [s.logical_input_rows for s in steps if s.step_name == "macd_segment"]
            assert segment_rows[-2:] == [2060,2060]
            assert all(s.output_rows>0 for s in steps if s.step_name == "macd_segment")
            earlier, second, previous_source = state.run(request(default_calculations(), before=state.times[9001]), real=True)
            assert earlier.statistics.source_rows == 9001
            assert previous_source.batches == [8192,809]
            _compare_page(earlier, state, 8001, 9001)
            assert earlier.times[-1] < initial.times[0]
            assert not set(earlier.times).intersection(initial.times)
            assert_closed(second)
            assert_templates_once(state.calls[-1], CALCULATION_FILES|OUTPUT_FILES)
        # Each separate request reads its own files once; no cross-request text cache.
        counts = Counter(state.calls[-1]["template_reads"] + state.calls[-2]["template_reads"])
        assert set(counts.values()) == {2}
