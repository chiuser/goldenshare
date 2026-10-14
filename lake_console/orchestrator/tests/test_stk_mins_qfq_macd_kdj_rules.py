"""Literal counts prove extraction retains ordinary check semantics in batch form."""

import duckdb
import pytest

from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.stk_mins_qfq_macd_kdj_rules import (
    macd_kdj_source_coverage_sql,
    macd_kdj_state_coverage_sql,
)


def test_single_day_parquet_checks_exclude_other_dates_before_frequency_cast(tmp_path):
    with duckdb.connect() as c:
        c.execute("""CREATE TABLE rows AS
          SELECT 'A' ts_code,'1' freq,DATE '2026-06-29' trade_date,
                 TIMESTAMP '2026-06-29 15:00:00' trade_time
          UNION ALL SELECT 'B','invalid',DATE '2025-01-02',TIMESTAMP '2025-01-02 15:00:00'""")
        result = tmp_path / 'result.parquet'
        state = tmp_path / 'state.parquet'
        c.execute(f"COPY rows TO {duckdb_string(result)} (FORMAT PARQUET)")
        c.execute(f"COPY (SELECT ts_code,freq,trade_date,trade_time last_trade_time FROM rows) TO {duckdb_string(state)} (FORMAT PARQUET)")
        result_sql = read_parquet(result, hive_partitioning=False)
        state_sql = read_parquet(state, hive_partitioning=False)
        assert c.execute(macd_kdj_source_coverage_sql(source=result_sql,indicator=result_sql,freq=1,dates=('2026-06-29',))).fetchall() == [('2026-06-29',1,1)]
        assert c.execute(macd_kdj_state_coverage_sql(indicator=result_sql,state=state_sql,freq=1,dates=('2026-06-29',))).fetchall() == [('2026-06-29',1,1,0,0)]
        with pytest.raises(duckdb.ConversionException):
            c.execute(macd_kdj_source_coverage_sql(source=result_sql,indicator=result_sql,freq=1,dates=('2025-01-02',))).fetchall()


def test_source_counts_are_per_day_and_do_not_mix_frequency():
    with duckdb.connect() as c:
        c.execute(
            "CREATE TABLE source AS SELECT 'A' ts_code,1 freq,DATE '2026-06-29' trade_date UNION ALL SELECT 'B',5,DATE '2026-06-29' UNION ALL SELECT 'A',1,DATE '2026-06-30'"
        )
        c.execute(
            "CREATE TABLE result AS SELECT * FROM source WHERE trade_date=DATE '2026-06-29'"
        )
        assert c.execute(
            macd_kdj_source_coverage_sql(
                source="source",
                indicator="result",
                freq=1,
                dates=("2026-06-29", "2026-06-30"),
            )
        ).fetchall() == [("2026-06-29", 1, 1), ("2026-06-30", 1, 0)]


@pytest.mark.parametrize(
    "last,extra,expected",
    [
        ("2026-06-29 15:00:00", False, ("2026-06-29", 1, 1, 0, 0)),
        ("2026-06-29 14:00:00", False, ("2026-06-29", 1, 1, 1, 0)),
        ("2026-06-30 15:00:00", False, ("2026-06-29", 1, 1, 1, 1)),
        ("2026-06-29 15:00:00", True, ("2026-06-29", 1, 2, 0, 0)),
    ],
)
def test_state_counts_preserve_current_future_and_carry_rules(last, extra, expected):
    with duckdb.connect() as c:
        c.execute(
            "CREATE TABLE result AS SELECT 'A' ts_code,1 freq,DATE '2026-06-29' trade_date,TIMESTAMP '2026-06-29 15:00:00' trade_time"
        )
        c.execute(
            "CREATE TABLE state AS SELECT ts_code,freq,trade_date,?::TIMESTAMP last_trade_time FROM result",
            [last],
        )
        if extra:
            c.execute(
                "INSERT INTO state VALUES ('B',1,DATE '2026-06-29',TIMESTAMP '2026-06-26 15:00:00')"
            )
        assert (
            c.execute(
                macd_kdj_state_coverage_sql(
                    indicator="result", state="state", freq=1, dates=("2026-06-29",)
                )
            ).fetchone()
            == expected
        )
