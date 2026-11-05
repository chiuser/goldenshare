from datetime import date

import duckdb
import pytest

from src.biz.queries.wealth.market.index_detail.index_detail_kline_query_service import (
    IndexDetailKlineQueryService,
)
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader


_CODE = "000001.SH"


@pytest.fixture
def chart_lake(tmp_path):
    # Project the DG producer's DATE/DOUBLE index factor columns, and its
    # separate index identity, SSE calendar and unadjusted daily facts.
    factor_projection = """
        SELECT ts_code, trade_date, close - 1 AS open, close + 2 AS high, close - 2 AS low,
               close, close - 0.5 AS pre_close, 0.5::DOUBLE AS change, 0.05::DOUBLE AS pct_change,
               111.0::DOUBLE AS vol, 222.0::DOUBLE AS amount, ma5 AS ma_bfq_5,
               100::DOUBLE AS ma_bfq_10, 100::DOUBLE AS ma_bfq_20, 100::DOUBLE AS ma_bfq_30,
               100::DOUBLE AS ma_bfq_60, 100::DOUBLE AS ma_bfq_90, 100::DOUBLE AS ma_bfq_250,
               107::DOUBLE AS boll_upper_bfq, 104::DOUBLE AS boll_mid_bfq, 101::DOUBLE AS boll_lower_bfq,
               1.1::DOUBLE AS macd_dif_bfq, 1.2::DOUBLE AS macd_dea_bfq, -0.2::DOUBLE AS macd_bfq,
               44::DOUBLE AS kdj_k_bfq, 55::DOUBLE AS kdj_d_bfq, 66::DOUBLE AS kdj_bfq
        FROM (SELECT ?::VARCHAR AS ts_code, ?::DATE AS trade_date, ?::DOUBLE AS close, ?::DOUBLE AS ma5)
    """

    with duckdb.connect(":memory:") as connection:
        def write(path, projection, params=()):
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            connection.execute(f"CREATE OR REPLACE TEMP TABLE chart_fixture AS {projection}", params)
            connection.execute("COPY chart_fixture TO ? (FORMAT PARQUET)", [str(target)])

        write(
            "silver/index_basic/full/part-000.parquet",
            "SELECT '000001.SH' AS ts_code, '上证指数' AS name, 'SSE' AS market, "
            "'SSE' AS publisher, '综合指数' AS category",
        )
        write(
            "silver/calendar/trade_calendar/full/part-000.parquet",
            """
            SELECT 'SSE' AS exchange, trade_date, is_open, pretrade_date
            FROM (VALUES
                (DATE '2009-12-28', true, DATE '2009-12-25'),
                (DATE '2009-12-29', true, DATE '2009-12-28'),
                (DATE '2009-12-30', true, DATE '2009-12-29'),
                (DATE '2009-12-31', true, DATE '2009-12-30'),
                (DATE '2010-01-01', false, DATE '2009-12-31'),
                (DATE '2010-01-02', false, DATE '2009-12-31'),
                (DATE '2010-01-03', false, DATE '2009-12-31'),
                (DATE '2010-01-04', true, DATE '2009-12-31'),
                (DATE '2010-01-05', true, DATE '2010-01-04'),
                (DATE '2010-01-06', true, DATE '2010-01-05')
            ) AS t(trade_date, is_open, pretrade_date)
            """,
        )
        write(
            "silver/index_daily/trade_date=2010-01-05/part-000.parquet",
            "SELECT '000001.SH' AS ts_code, DATE '2010-01-05' AS trade_date",
        )
        for day, code, close, ma5 in (
            ("2009-12-28", _CODE, 100, None),
            ("2009-12-29", _CODE, 101, 99),
            ("2009-12-30", _CODE, 102, 100),
            ("2009-12-31", _CODE, 103, 101),
            ("2010-01-04", _CODE, 104, 102),
            ("2010-01-05", "399001.SZ", 200, 197),
            ("2010-01-06", _CODE, 106, None),
        ):
            write(
                f"silver/index/index_factor_pro/trade_date={day}/part-000.parquet",
                factor_projection,
                (code, day, close, ma5),
            )
    return IndexDailyLakeReader(tmp_path)


def test_dg_chart_fills_original_window_without_warmup_for_complete_ma(chart_lake, monkeypatch):
    batches = []
    read_factors = chart_lake.factor_rows

    def record_factors(**kwargs):
        batches.append(kwargs["dates"])
        return read_factors(**kwargs)

    monkeypatch.setattr(chart_lake, "factor_rows", record_factors)
    service = IndexDetailKlineQueryService(daily_lake=chart_lake)
    result = service.build_kline(
        object(), ts_code=_CODE, period="day",
        start_date=date(2009, 12, 31), end_date=date(2010, 1, 5), limit=2, debug=True,
    )

    assert batches == [(date(2010, 1, 4), date(2010, 1, 5)), (date(2009, 12, 31),)]
    assert [bar.tradeDate for bar in result.bars] == [date(2009, 12, 31), date(2010, 1, 4)]
    latest = result.bars[-1]
    assert latest.close == 104.0
    assert latest.factors.macd.model_dump() == {"dif": 1.1, "dea": 1.2, "macd": -0.2}
    assert latest.factors.kdj.j == 66.0
    assert result.dataStatus.status == "PARTIAL"
    assert result.debugInfo.modules[0].missingCount == 1
    assert {error.code for error in result.debugInfo.exceptions} == {"ID_FACTOR_PARTIAL", "ID_SOURCE_DELAYED"}


@pytest.mark.parametrize(
    ("trade_date", "status", "missing_count"),
    [(date(2009, 12, 28), "READY", 0), (date(2010, 1, 6), "PARTIAL", 1)],
)
def test_dg_chart_checks_ma_against_earlier_effective_bars(chart_lake, trade_date, status, missing_count):
    result = IndexDetailKlineQueryService(daily_lake=chart_lake).build_kline(
        object(), ts_code=_CODE, period="day", start_date=trade_date, end_date=trade_date, limit=1, debug=True,
    )

    assert len(result.bars) == 1
    assert result.bars[0].factors.ma.ma5 is None
    assert result.dataStatus.status == status
    assert result.debugInfo.modules[0].missingCount == missing_count
