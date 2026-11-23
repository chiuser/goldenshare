"""Stock period reads against the audited Parquet schema and Serving model."""

from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from time import monotonic
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from goldenshare_technical_indicators import CalculationRequest
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.discovery import describe_calculation
from goldenshare_technical_indicators.errors import (
    CalculationCancelledError, RequestInvalidError, ResourceLimitError, SourceUnsupportedError,
)
from goldenshare_technical_indicators.execution_control import ExecutionControl
from goldenshare_technical_indicators.output.encoding import encode_response_utf8
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from src.app.runtime.technical_indicators.composition import build_runtime_config
from src.foundation.clients.local_lake.technical_indicator_price_locator import LakePriceLocator
from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.clients.technical_indicator_postgres import PostgresTechnicalIndicatorPriceSource
from src.foundation.config.settings import Settings
from src.foundation.models.core_serving.stk_period_bar_adj import StkPeriodBarAdj
from tests.wealth_watchlist_postgres_support import isolated_postgres


TZ = ZoneInfo("Asia/Shanghai")
CODE = "000001.SZ"
PRICE = {"calculation_id": "price", "parameters": {}}
MA2 = {"calculation_id": "ma", "parameters": {"period": 2}}
MACD = {"calculation_id": "macd", "parameters": {}}
KDJ = {"calculation_id": "kdj", "parameters": {}}
NINE = {"calculation_id": "nineturn", "parameters": {}}
SCHEMA = pa.schema([
    ("ts_code", pa.string()), ("trade_date", pa.string()), ("end_date", pa.string()),
    *((column, pa.decimal128(18, 4)) for column in ("open_qfq", "high_qfq", "low_qfq", "close_qfq")),
    ("vol", pa.decimal128(20, 4)), ("amount", pa.decimal128(20, 4)), ("pct_chg", pa.decimal128(10, 4)),
])


@pytest.fixture
def stock_postgres(tmp_path_factory):
    with isolated_postgres(tmp_path_factory.mktemp("stock-period-pg")) as engine:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA core_serving")
            StkPeriodBarAdj.__table__.create(connection)
        yield engine


@pytest.fixture(params=("dg", "prod_pg"))
def warehouse(request, tmp_path, monkeypatch):
    backend = request.param
    engine = request.getfixturevalue("stock_postgres") if backend == "prod_pg" else None
    opened, queries = Counter(), []
    parquet_file = pq.ParquetFile

    def open_file(path, *args, **kwargs):
        opened[path] += 1
        return parquet_file(path, *args, **kwargs)

    def trace(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().startswith("SELECT") and "stk_period_bar_adj" in statement:
            queries.append((statement, params))

    monkeypatch.setattr(pq, "ParquetFile", open_file)
    if engine is not None:
        event.listen(engine, "before_cursor_execute", trace)

    def seed(freq, values):
        for day, end, close in values:
            row = dict(ts_code=CODE, freq=freq, trade_date=day, end_date=end,
                       open_qfq=Decimal(close - 1), high_qfq=Decimal(close + 2),
                       low_qfq=Decimal(close - 2), close_qfq=Decimal(close),
                       vol=Decimal("12.25"), amount=Decimal("36.125"), pct_chg=Decimal("1.25"))
            other = dict(row, ts_code="000002.SZ", close_qfq=Decimal(99))
            if engine is None:
                if freq == "week":
                    friday = day + timedelta(days=4 - day.weekday())
                    path = tmp_path / f"silver/quote/stock_weekly/week_end={friday}/part-000.parquet"
                else:
                    path = tmp_path / f"silver/quote/stock_monthly/month={day:%Y-%m}/part-000.parquet"
                path.parent.mkdir(parents=True, exist_ok=True)
                rows = [{**record, "trade_date": day.strftime("%Y%m%d"),
                         "end_date": end.strftime("%Y%m%d") if end else None} for record in (row, other)]
                pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path)
            else:
                with engine.begin() as connection:
                    connection.execute(StkPeriodBarAdj.__table__.insert(), (row, other))

    def service(*, limit=500, control_factory=None):
        config = build_runtime_config(Settings(
            _env_file=None, APP_ENV="local" if engine is None else "prod", GOLDENSHARE_LAKE_ROOT=str(tmp_path),
            TECHNICAL_INDICATOR_BATCH_ROWS=25, TECHNICAL_INDICATOR_MAX_OUTPUT_ROWS=limit,
        ))
        source = (LakeTechnicalIndicatorPriceSource(config) if engine is None
                  else PostgresTechnicalIndicatorPriceSource(config, sessionmaker(engine)))
        control = control_factory(config) if control_factory is not None else None
        return TechnicalIndicatorService(source=source, config=config, registry=create_builtin_registry(), control=control)

    try:
        yield seed, service, backend, opened, queries, engine
    finally:
        if engine is not None:
            event.remove(engine, "before_cursor_execute", trace)


def request_for(period, start, end, calculations=(PRICE, MA2, NINE), *, adjustment="qfq"):
    return CalculationRequest(security_type="stock", ts_code=CODE, period=period, adjustment=adjustment,
                              start=datetime.combine(start, time(), TZ), end=datetime.combine(end, time(), TZ),
                              calculations=calculations)


def test_boundaries_period_dates_and_pre_adjusted_input(warehouse):
    seed, service, _, opened, queries, _ = warehouse
    outside, origin, next_week = date(2013, 12, 27), date(2014, 1, 3), date(2014, 1, 17)
    # Listed boundary, a gap with no product, and a historical adjustment date unrelated to the label.
    seed("week", ((outside, outside, 90), (origin, date(2026, 10, 16), 10), (next_week, next_week, 12)))
    nov, finished_through = date(2026, 11, 30), date(2026, 11, 20)
    sep = date(2026, 9, 30)
    seed("week", ((sep, sep, 14),))
    seed("month", ((sep, None, 20), (nov, finished_through, 24)))
    kernel = service()
    result = kernel.calculate(request_for("week", outside, next_week))
    assert result.times == (date(2013, 12, 30), date(2014, 1, 13))
    assert result.source_as_of == (origin, next_week)
    assert result.period_bars[0].end_date == date(2026, 10, 16)
    assert result.period_bars[0].pct_chg == 1.25
    assert not result.price_adjustment.converted
    assert result.statistics.price_conversion_batches == 0
    assert dict(result.calculations[0].fields) == dict(
        open=(9., 11.), high=(12., 14.), low=(8., 10.), close=(10., 12.),
        volume=(1225., 1225.), amount=(36125., 36125.),
    )
    previous = kernel.calculate(request_for("week", next_week, next_week))
    assert previous.statistics.source_rows == 2
    assert dict(previous.calculations[1].fields)["value"] == (11.,)
    short_week = kernel.calculate(request_for("week", date(2026, 9, 28), sep, (PRICE,)))
    assert short_week.times == (date(2026, 9, 28),) and short_week.source_as_of == (sep,)
    assert dict(short_week.calculations[0].fields)["close"] == (14.,)
    result = kernel.calculate(request_for("month", date(2026, 9, 1), finished_through))
    assert result.times == (date(2026, 9, 1), date(2026, 11, 1))
    assert result.source_as_of == (sep, nov)
    assert [bar.end_date for bar in result.period_bars] == [None, finished_through]
    assert result.statistics.source_rows == result.range.count == 2
    assert dict(result.calculations[1].fields)["value"] == (None, 22.)
    encoded = encode_response_utf8(result, control=ExecutionControl(arrived_at=monotonic(), config=kernel.config))
    assert b'"period_bars"' not in encoded
    capabilities = describe_calculation(create_builtin_registry(), "nineturn", config=kernel.config).source_capabilities
    assert {(c.security_type, c.period, c.adjustment) for c in capabilities if c.period in ("week", "month")} == {
        ("stock", "week", "qfq"), ("stock", "month", "qfq"),
    }
    with pytest.raises(SourceUnsupportedError):
        kernel.calculate(request_for("week", origin, next_week, (PRICE,), adjustment="none"))
    assert all("2013-12-27" not in str(path) for path in opened)
    assert all("adj_factor" not in sql for sql, _ in queries)


def test_output_and_warmup_options_share_reads_without_leaking(warehouse):
    seed, service, backend, opened, queries, _ = warehouse
    days = tuple(date(2014, 1, 3) + timedelta(weeks=i) for i in range(620))
    seed("week", ((day, day, 10 + (i * 17) % 29) for i, day in enumerate(days)))
    kernel = service()
    page = request_for("week", days[-100], days[-1], (PRICE, MACD, KDJ, NINE))
    full = request_for("week", days[-500], days[-1], (PRICE, MACD, KDJ, NINE))
    limited = kernel.calculate(page, output_rows=100, warmup_error_budget=0.00001)
    assert limited.range.count == 100 and limited.statistics.source_rows == 459
    assert limited.source_as_of == days[-100:]
    if backend == "dg":
        assert len(opened) == 459 and set(opened.values()) == {1}
    else:
        assert len(queries) == 2
        assert queries[1][1][3] < queries[0][1][2]
        assert '"pct_chg"' in queries[0][0] and '"end_date"' not in queries[1][0]
        assert queries[1][1][-1] == 359

    first_reads = opened.copy(), queries.copy()
    opened.clear()
    queries.clear()
    without_nine = request_for("week", days[-100], days[-1], (PRICE, MACD, KDJ))
    same = kernel.calculate(without_nine, output_rows=100, warmup_error_budget=0.00001)
    assert (opened, queries) == first_reads
    assert same.statistics.source_rows == limited.statistics.source_rows
    assert same.calculations == limited.calculations[:-1]

    common = kernel.calculate(page, output_rows=100)
    assert common.statistics.source_rows == 600
    wide = kernel.calculate(full, output_rows=500, warmup_error_budget=0.00001)
    assert wide.range.count == 500 and wide.statistics.source_rows == 620
    assert wide.source_as_of[-100:] == limited.source_as_of
    assert dict(wide.calculations[0].fields)["close"][-100:] == dict(limited.calculations[0].fields)["close"]
    for left, right in zip(limited.calculations[1:3], common.calculations[1:3], strict=True):
        for (_, actual), (_, reference) in zip(left.fields, right.fields, strict=True):
            assert actual == pytest.approx(reference, abs=0.00001, rel=0)
    for left, right in zip(limited.calculations[1:3], wide.calculations[1:3], strict=True):
        for (_, actual), (_, reference) in zip(left.fields, right.fields, strict=True):
            assert actual == pytest.approx(reference[-100:], abs=0.00001, rel=0)
    alternative = request_for("week", days[-100], days[-1], (KDJ, MACD))
    assert kernel.calculate(alternative, output_rows=100, warmup_error_budget=0.00001).statistics.source_rows == 459
    assert kernel.calculate(page, output_rows=100, warmup_error_budget=0.00001).statistics.source_rows == 459
    with pytest.raises(ResourceLimitError, match="max_output_rows"):
        kernel.calculate(full, output_rows=100)
    with pytest.raises(ResourceLimitError, match="max_output_rows"):
        service(limit=99).calculate(page, output_rows=500)
    with pytest.raises(RequestInvalidError):
        kernel.calculate(page, output_rows=200)
    with pytest.raises(RequestInvalidError):
        kernel.calculate(page, warmup_error_budget=0.01)


@pytest.mark.parametrize(("freq", "first_close", "counts"), (("week", 0, 13), ("month", 4, 12)))
def test_nine_turn_consumes_its_sixteenth_preceding_period(warehouse, freq, first_close, counts):
    seed, service, _, _, _, _ = warehouse
    if freq == "week":
        days = tuple(date(2014, 1, 3) + timedelta(weeks=index) for index in range(17))
    else:
        # Close dates can precede the calendar month-end.
        days = tuple(date(2024 + index // 12, 1 + index % 12, 28) for index in range(17))
    seed(freq, ((day, day, close) for day, close in zip(days, (first_close, *range(1, 17)), strict=True)))
    result = service().calculate(request_for(freq, days[-1], days[-1], (NINE,)))
    assert result.statistics.source_rows == 17
    assert result.calculations[0].fields == (("up_count", (counts,)), ("down_count", (0,)))


def test_cancel_stock_period_read_and_retry(warehouse, monkeypatch):
    seed, service, _, _, _, engine = warehouse
    first, last = date(2014, 1, 3), date(2014, 1, 10)
    seed("week", ((first, first, 10), (last, last, 12)))
    kernel = service(control_factory=lambda cfg: ExecutionControl(arrived_at=monotonic(), config=cfg))
    if engine is None:
        original = LakePriceLocator._read_stock_period_partition

        def interrupt(locator, *args):
            row = original(locator, *args)
            kernel.control.request_stop("cancel")
            return row

        with monkeypatch.context() as patch:
            patch.setattr(LakePriceLocator, "_read_stock_period_partition", interrupt)
            with pytest.raises(CalculationCancelledError):
                kernel.calculate(request_for("week", first, last))
    else:
        def interrupt(conn, cursor, statement, params, context, executemany):
            if "stk_period_bar_adj" in statement:
                kernel.control.request_stop("cancel")

        event.listen(engine, "after_cursor_execute", interrupt)
        try:
            with pytest.raises(CalculationCancelledError):
                kernel.calculate(request_for("week", first, last))
        finally:
            event.remove(engine, "after_cursor_execute", interrupt)
        assert engine.pool.checkedout() == 0
    assert kernel.control.resources_released_at is not None
    result = service().calculate(request_for("week", first, last))
    assert result.source_as_of == (first, last)
    assert result.statistics.source_rows == 2
