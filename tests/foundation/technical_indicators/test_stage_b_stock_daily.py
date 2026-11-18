"""Stock daily contracts with real Parquet reads and independently computed values."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
from time import monotonic

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from goldenshare_technical_indicators import CalculationRequest
from goldenshare_technical_indicators.calculation.engine import CalculationEngine
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.configuration.datasets import DATASET_LOCATIONS
from goldenshare_technical_indicators.errors import (
    CalculationCancelledError, ResourceLimitError, SourceContractError, SourceReadError, SourceUnsupportedError,
)
from goldenshare_technical_indicators.execution_control import ExecutionControl
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from goldenshare_technical_indicators.sources.read_context import SourceReadContext
from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.clients.technical_indicator_stock_daily import full_day_suspension
from src.foundation.config.settings import Settings, technical_indicator_config_from_settings


CODE = "600519.SH"
FRI, SAT, SUN, MON, TUE = (date(2026, 11, day) for day in range(13, 18))
PRICE = {"calculation_id": "price", "parameters": {}}
MA2 = {"calculation_id": "ma", "parameters": {"period": 2}}


def _write(root, relative_path, schema, rows):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(schema)), path)


def _dg(root, prices, *, suspensions=None, listed=FRI, delisted=None):
    # Field names and physical DATE/Boolean/DOUBLE types from the formal DG
    # files for 2026-11-16/17. Four prices and quantities here are test values.
    for day, closes in prices.items():
        _write(root, f"silver/quote/stock_daily/trade_date={day}/part-000.parquet",
               [("ts_code", pa.string()), ("trade_date", pa.date32()),
                *((column, pa.float64()) for column in ("open", "high", "low", "close", "vol", "amount"))],
               [dict(ts_code=CODE, trade_date=day, open=close-1, high=close+1, low=close-2, close=close,
                     vol=12.25, amount=36.125) for close in closes])
    _write(root, "silver/basic/stock_lifecycle/full/part-000.parquet",
           [("ts_code", pa.string()), ("list_date", pa.date32()), ("delist_date", pa.date32())],
           [dict(ts_code=CODE, list_date=listed, delist_date=delisted)])
    _write(root, "silver/calendar/trade_calendar/full/part-000.parquet",
           [("exchange", pa.string()), ("trade_date", pa.date32()), ("is_open", pa.bool_())],
           [dict(exchange="SSE", trade_date=day, is_open=day in (FRI, MON, TUE))
            for day in (FRI, SAT, SUN, MON, TUE)])
    for day in (FRI, MON, TUE):
        _write(root, f"silver/quote/stock_suspend_daily/trade_date={day}/part-000.parquet",
               [("ts_code", pa.string()), ("trade_date", pa.date32()), ("suspend_type", pa.string()),
                ("suspend_timing", pa.string())],
               [dict(ts_code=CODE, trade_date=day, suspend_type=kind, suspend_timing=timing)
                for kind, timing in (suspensions or {}).get(day, ())])


@contextmanager
def _read(root, first, last, *, max_output=2, batch_rows=1, calculations=(PRICE,)):
    locations = deepcopy(DATASET_LOCATIONS)
    locations["stock_daily"]["dg"]["enabled_adjustments"] = ("none",)
    config = technical_indicator_config_from_settings(Settings(
        _env_file=None, GOLDENSHARE_LAKE_ROOT=str(root), TECHNICAL_INDICATOR_BATCH_ROWS=batch_rows,
        TECHNICAL_INDICATOR_MAX_OUTPUT_ROWS=max_output,
    ), data_location="dg", dataset_locations=locations)
    control = ExecutionControl(arrived_at=monotonic(), config=config)
    source = LakeTechnicalIndicatorPriceSource(config)
    service = TechnicalIndicatorService(config=config, source=source, registry=create_builtin_registry())
    request = CalculationRequest(
        security_type="stock", ts_code=CODE, period="day", adjustment="none",
        start=datetime.combine(first, datetime.min.time(), tzinfo=timezone.utc),
        end=datetime.combine(last, datetime.min.time(), tzinfo=timezone.utc),
        calculations=calculations,
    )
    prepared = service._prepare_calculation(request)
    read_context = SourceReadContext(config)
    connection, executor = service._open_execution(control)
    engine = CalculationEngine(executor, prepared.plan)
    session = None
    try:
        session = service._build_input_session(prepared, engine, executor, read_context)
        session.prepare()
        yield session, connection, read_context, control
    finally:
        assert not service._close_execution(control, connection, engine=engine, inputs=session)
        assert control.resources_released_at is not None


def _windows(session, connection):
    windows = []
    while session.next_batch() is not None:
        windows.append(connection.execute(
            "SELECT trade_date, period_start, period_end, source_as_of, close, volume, amount "
            "FROM ti_price_window ORDER BY seq"
        ).fetchall())
        session.retain_required_history()
        session.finish_batch()
    return windows


def test_shared_input_units_and_prewarm_with_two_target_rows_at_the_limit(tmp_path):
    _dg(tmp_path, {FRI: [10], MON: [20], TUE: [30]})
    with _read(tmp_path, SAT, TUE, calculations=(PRICE, MA2)) as (session, connection, context, _):
        resolved = session.resolved_description()
        assert (resolved.selection.target_rows, resolved.selection.preceding_rows) == (2, 1)
        assert (resolved.volume_unit, resolved.amount_unit) == ("share", "CNY")
        assert _windows(session, connection) == [
            [(FRI, FRI, FRI, FRI, 10, 1225, 36125)],
            [(FRI, FRI, FRI, FRI, 10, 1225, 36125), (MON, MON, MON, MON, 20, 1225, 36125)],
            [(MON, MON, MON, MON, 20, 1225, 36125), (TUE, TUE, TUE, TUE, 30, 1225, 36125)],
        ]
        assert context.source_rows == 3
    with pytest.raises(ResourceLimitError, match="max_output_rows"):
        with _read(tmp_path, FRI, TUE):
            pytest.fail("Excess target rows must never be truncated")


def test_no_target_stops_before_reading_auxiliary_facts(tmp_path):
    _dg(tmp_path, {FRI: [10]})
    (tmp_path / "silver/calendar/trade_calendar/full/part-000.parquet").unlink()
    (tmp_path / f"silver/quote/stock_daily/trade_date={FRI}/part-000.parquet").write_bytes(b"bad footer")
    with pytest.raises(SourceReadError, match="读取数据失败") as error:
        with _read(tmp_path, MON, TUE):
            pytest.fail("A pre-warm row cannot substitute for a missing target")
    assert error.value.detail == "数据缺失"


@pytest.mark.parametrize(("suspension", "error"), (
    ([], "Missing scheduled market data"),
    ([("S", "09:30-10:30")], "Missing scheduled market data"),
    ([("S", None), ("R", None)], "Missing scheduled market data"),
    ([("S", None)], None),
))
def test_missing_open_day_and_full_day_suspension(tmp_path, suspension, error):
    _dg(tmp_path, {FRI: [10], TUE: [30]}, suspensions={MON: suspension})
    if error:
        with pytest.raises(SourceContractError, match=error):
            with _read(tmp_path, FRI, TUE) as (session, connection, _, _):
                _windows(session, connection)
    else:
        with _read(tmp_path, FRI, TUE) as (session, connection, _, _):
            assert [window[-1][0] for window in _windows(session, connection)] == [FRI, TUE]
    assert full_day_suspension(iter(suspension)) is (error is None)


@pytest.mark.parametrize(("listed", "delisted", "prices", "expected"), (
    (MON, None, {MON: [20], TUE: [30]}, [MON, TUE]),
    (FRI, TUE, {FRI: [10], MON: [20]}, [FRI, MON]),
))
def test_listing_is_inclusive_and_delisting_is_exclusive(tmp_path, listed, delisted, prices, expected):
    _dg(tmp_path, prices, listed=listed, delisted=delisted)
    with _read(tmp_path, FRI, TUE) as (session, connection, _, _):
        assert [window[-1][0] for window in _windows(session, connection)] == expected


def test_missing_last_open_day_and_duplicate_dates_fail(tmp_path):
    _dg(tmp_path, {MON: [20]})
    with pytest.raises(SourceContractError, match="Missing scheduled market data: 2026-11-17"):
        with _read(tmp_path, MON, TUE) as (session, connection, _, _):
            _windows(session, connection)
    _dg(tmp_path, {MON: [20, 20]})
    with pytest.raises(SourceContractError, match="Duplicate stock daily positions"):
        with _read(tmp_path, MON, MON, max_output=1) as (session, connection, _, _):
            _windows(session, connection)


def test_price_with_wrong_partition_date_reports_contract_error(tmp_path):
    _dg(tmp_path, {MON: [20]})
    path = tmp_path / f"silver/quote/stock_daily/trade_date={MON}/part-000.parquet"
    original = pq.read_table(path, partitioning=None)
    pq.write_table(original.set_column(1, "trade_date", pa.array([TUE], type=pa.date32())), path)
    with pytest.raises(SourceContractError, match="partition date"):
        with _read(tmp_path, MON, MON):
            pytest.fail("A misplaced price must not be mistaken for missing target data")


def test_incomplete_delivery_and_io_error_are_distinct(tmp_path, monkeypatch):
    _dg(tmp_path, {MON: [20], TUE: [30]})
    with _read(tmp_path, MON, TUE) as (session, connection, _, _):
        with monkeypatch.context() as patch:
            patch.setattr(session._stream, "next_batch", lambda limit: None)
            with pytest.raises(SourceContractError) as error:
                _windows(session, connection)
    assert (error.value.reason, error.value.expected_count, error.value.actual_count) == (
        "selection_count_mismatch", 2, 0)
    (tmp_path / f"silver/quote/stock_suspend_daily/trade_date={MON}/part-000.parquet").unlink()
    with pytest.raises(SourceReadError, match="stock_suspend_daily") as error:
        with _read(tmp_path, MON, TUE):
            pytest.fail("A missing suspension file cannot establish the stock's schedule")
    assert error.value.detail is None


def test_cancelled_request_releases_input_and_restarts_from_the_beginning(tmp_path):
    _dg(tmp_path, {MON: [20], TUE: [30]})
    with pytest.raises(CalculationCancelledError):
        with _read(tmp_path, MON, TUE) as (session, _, _, control):
            assert session.next_batch().new_last_seq == 1
            control.request_stop("cancel")
            session.executor.control.check_active()
    with _read(tmp_path, MON, TUE) as (session, connection, _, _):
        assert [window[-1][0] for window in _windows(session, connection)] == [MON, TUE]


def test_dg_reader_rejects_a_prod_target_before_checking_its_path(tmp_path, monkeypatch):
    _dg(tmp_path, {MON: [20]})
    with _read(tmp_path, MON, MON) as (session, _, context, _):
        prod = replace(session.requirement.target, backend="prod_pg")
        wrong_backend = replace(session.requirement, target=prod)

        def unexpected_root():
            pytest.fail("The DG reader must reject a Prod instruction before accessing any path")

        monkeypatch.setattr(session.source, "_root", unexpected_root)
        locator = session.source.create_locator(session.executor, wrong_backend, read_context=context)
        with pytest.raises(SourceUnsupportedError):
            locator.describe()
        locator.close()
