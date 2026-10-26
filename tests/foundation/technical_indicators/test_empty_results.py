"""LLD 04.5/14/18.1: two real empty-result requests, not empty failures.

Other tests in this file use explicit timing substitutes and canonical temporary
period files. Weekly source dates and DECIMAL columns follow PERIOD_SCHEMA.
"""

from dataclasses import replace
from datetime import date

from d3_reference import DAILY_DATES
from d3_support import assert_closed, d3_data, request, values
from src.foundation.technical_indicators import CalculationInstance


def test_complete_service_empty_before(d3_data):
    state = d3_data
    with state.case("empty_before"):
        result, service, source = state.run(request(
            (CalculationInstance("macd", "macd", {}),), before=state.times[0]), real=True)
        assert result.times == () and result.range.count == 0
        assert result.range.actual_start is result.range.actual_end is None
        assert result.source.read_start is result.source.read_end is None
        assert result.statistics.source_rows == 0 and source.batches == []
        assert result.msg == "已经加载全部数据了"
        assert values(result) == {"macd":{"dif":(),"dea":(),"hist":()}}
        assert dict(result.calculations[0].parameters) == {"fast":12,"slow":26,"signal":9}
        assert result.calculations[0].algorithm_version == "2.0.0"
        assert_closed(service)


def test_complete_service_empty_range_does_not_read_price_history(d3_data):
    state = d3_data
    with state.case("empty_range"):
        result, service, source = state.run(request(
            (CalculationInstance("macd", "macd", {}),), period="day", start=date(2026,2,3)), real=True)
        assert result.times == () and result.range.count == 0
        assert result.range.actual_start is result.range.actual_end is None
        assert result.statistics.source_rows == 0 and source.batches == []
        assert source.open_calls == 0
        assert result.source.read_start is None
        assert result.source.read_end is None
        assert result.price_adjustment.basis_date is None
        assert result.price_adjustment.basis_value is None
        assert result.msg == "" and result.source_as_of is None
        assert values(result) == {"macd":{"dif":(),"dea":(),"hist":()}}
        assert_closed(service)


def test_current_week_updates_keep_one_bar_and_actual_cutoff(d3_data):
    import duckdb

    state = d3_data
    with state.case("current_week_updates"):
        root = state.root / "weekly"
        # The partition uses ISO dates; source columns below retain YYYYMMDD.
        # Contract: LLD 06.1 and producer paths.silver_stock_weekly_path.
        path = root / "silver/quote/stock_weekly/week_end=2026-10-23/part-000.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        config = replace(state.config, goldenshare_lake_root=str(root))
        con = duckdb.connect(":memory:", config={"threads":1,"max_temp_directory_size":"0B"})
        try:
            for as_of, close in (("20261020",5.0),("20261021",6.0)):
                replacement = root / "current_week_replacement.parquet"
                state.query(con, "fixture_current_week", """COPY (SELECT '600000.SH'::VARCHAR AS ts_code,
                    '20261023'::VARCHAR AS trade_date,$as_of::VARCHAR AS end_date,
                    10::DECIMAL(18,4) AS open,14::DECIMAL(18,4) AS high,
                    8::DECIMAL(18,4) AS low,12::DECIMAL(18,4) AS close,
                    5::DECIMAL(18,4) AS open_qfq,7::DECIMAL(18,4) AS high_qfq,
                    4::DECIMAL(18,4) AS low_qfq,$close::DECIMAL(18,4) AS close_qfq,
                    20::DECIMAL(18,4) AS open_hfq,28::DECIMAL(18,4) AS high_hfq,
                    16::DECIMAL(18,4) AS low_hfq,24::DECIMAL(18,4) AS close_hfq,
                    12::DECIMAL(20,4) AS vol,34::DECIMAL(20,4) AS amount)
                    TO $target (FORMAT PARQUET)""", rows=1,
                    bindings={"as_of":as_of,"close":close,"target":str(replacement)})
                replacement.replace(path)
                state.fixture_rows += 1
                cutoff = date(2026,10,20) if as_of=="20261020" else date(2026,10,21)
                result, service, source = state.run(request(period="week", end=cutoff), config=config)
                assert source.batches == [1] and result.statistics.source_rows == 1
                assert result.times == (date(2026,10,19),)
                assert result.source_as_of == (cutoff,)
                assert result.source.read_start == result.source.read_end == date(2026,10,19)
                assert values(result)["price"]["close"] == (close,)
                assert result.statistics.price_conversion_batches == 0
                assert_closed(service)
        finally:
            con.close()
