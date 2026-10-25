"""LLD 19.10: 21 producer-shaped daily files coalesce before indicators run.

Input contract and independent qfq values match the already approved D2 literal
factors: raw close10, ten factors1 followed by eleven factors2, latest basis2.
This request substitutes timing only, with real files, Arrow, adjustment SQL,
calculation, result collection, and cleanup.
"""

from datetime import date

from d3_reference import DAILY_DATES
from d3_support import assert_closed, close_enough, d3_data, request, values
from src.foundation.technical_indicators import CalculationInstance


def test_daily_21_files_deliver_one_indicator_batch_and_nulls(d3_data):
    state = d3_data
    with state.case("daily_short"):
        result, service, source = state.run(request((
            CalculationInstance("price","price",{}),CalculationInstance("ma20","ma",{}),
        ),period="day"))
        actual = values(result)
        assert result.times == tuple(date.fromisoformat(day) for day in DAILY_DATES)
        assert result.range.count == 21 and result.msg == ""
        assert source.batches == [21] and source.open_calls == 1
        assert result.statistics.source_rows == 21
        assert result.statistics.price_conversion_batches == 1
        assert result.price_adjustment.basis_date == date(2026,2,2)
        assert result.price_adjustment.basis_value == 2.0
        assert result.source.read_start == result.times[0] and result.source.read_end == result.times[-1]
        assert actual["price"]["close"] == (5.0,)*10+(10.0,)*11
        assert actual["price"]["volume"] == (100.0,)*21
        assert actual["price"]["amount"] == (1000.0,)*21
        close_enough(actual["ma20"]["value"], (None,)*19+(7.5,7.75))
        assert sum(s.step_name=="rolling_mean" for s in service.observed_executor.statistics) == 1
        assert_closed(service)
