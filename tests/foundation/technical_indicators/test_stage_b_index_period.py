"""Read both index period contracts using isolated Parquet and PostgreSQL."""

from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import count
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy.orm import sessionmaker

from goldenshare_technical_indicators import CalculationRequest
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.configuration.datasets import DATASET_LOCATIONS
from goldenshare_technical_indicators.discovery.catalog import describe_calculation
from goldenshare_technical_indicators.errors import (
    CalculationCancelledError, ResourceLimitError, SourceContractError, SourceReadError, SourceUnsupportedError,
)
from goldenshare_technical_indicators.execution_control import ExecutionControl
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from src.app.runtime.technical_indicators.composition import build_runtime_config
from src.foundation.clients.local_lake.technical_indicator_price_locator import LakePriceLocator
from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.clients.technical_indicator_postgres import PostgresTechnicalIndicatorPriceSource
from src.foundation.config.settings import Settings, technical_indicator_config_from_settings
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from tests.wealth_watchlist_postgres_support import isolated_postgres


SHANGHAI = ZoneInfo("Asia/Shanghai")
PRICE = {"calculation_id": "price", "parameters": {}}
MA2 = {"calculation_id": "ma", "parameters": {"period": 2}}
MA250 = {"calculation_id": "ma", "parameters": {"period": 250}}
BOLL2 = {"calculation_id": "boll", "parameters": {"period": 2, "multiplier": 2}}
MACD = {"calculation_id": "macd", "parameters": {"fast": 12, "slow": 26, "signal": 9}}
KDJ = {"calculation_id": "kdj", "parameters": {"window": 9, "k_period": 3, "d_period": 3}}
MODELS = {"week": IndexWeeklyServing, "month": IndexMonthlyServing}
_CODES = count(900000)


def _day(value):
    return date.fromisoformat(f"2026-{value}")


# Actual short-week and month-end dates follow the LLD samples. Prices are
# independent literals. The fixture also closes one whole week (Oct 19–23).
WEEKS = (("09-21", "09-24", 10), ("09-28", "09-30", 12), ("10-08", "10-09", 11))
MONTHS = (("09-01", "09-30", 10), ("10-08", "10-30", 12), ("11-02", "11-20", 11))


def _calendar():
    lo, hi = _day("09-01"), _day("11-30")
    closed = {_day("09-25"), *(_day("10-01") + timedelta(days=i) for i in range(7)),
              *(_day("10-19") + timedelta(days=i) for i in range(5))}
    return [dict(exchange="SSE", trade_date=day, is_open=day.weekday() < 5 and day not in closed)
            for day in (lo + timedelta(days=i) for i in range((hi - lo).days + 1))]


@pytest.fixture(scope="module")
def period_postgres(tmp_path_factory):
    with isolated_postgres(tmp_path_factory.mktemp("index-period-pg")) as engine:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA core_serving")
            for model in (TradeCalendar, *MODELS.values()):
                model.__table__.create(connection)
            connection.execute(TradeCalendar.__table__.insert(), _calendar())
        yield engine


@pytest.fixture(params=("dg", "prod_pg"))
def warehouse(request, tmp_path):
    backend = request.param
    engine = request.getfixturevalue("period_postgres") if backend == "prod_pg" else None

    def create(period, prices, *, limit=500, batch_rows=2, null_amount=False):
        code = f"{next(_CODES)}.SH"
        dataset = "index_weekly" if period == "week" else "index_monthly"
        locations = deepcopy(DATASET_LOCATIONS)
        locations[dataset][backend]["enabled_adjustments"] = ("none",)
        config = technical_indicator_config_from_settings(Settings(
            _env_file=None, GOLDENSHARE_LAKE_ROOT=str(tmp_path), TECHNICAL_INDICATOR_BATCH_ROWS=batch_rows,
            TECHNICAL_INDICATOR_MAX_OUTPUT_ROWS=limit,
        ), data_location=backend, dataset_locations=locations)
        target = config.resolve_dataset_location(dataset)
        # Both fixtures use the audited column types and each source's units.
        volume, amount = (("12.250000", "36.1250000") if backend == "dg" else ("1225.0000", "36125.0000"))
        data = [dict(ts_code=code, period_start_date=_day(start), trade_date=_day(cutoff),
                     open=Decimal(close - 1), high=Decimal(close + 1), low=Decimal(close - 2),
                     close=Decimal(close), vol=Decimal(volume), amount=Decimal(amount))
                for start, cutoff, close in prices]
        if null_amount:
            data[-1]["amount"] = None
        if engine is None:
            path = tmp_path / locations[dataset][backend]["relative_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            schema = pa.schema([("ts_code", pa.string()), ("period_start_date", pa.date32()), ("trade_date", pa.date32()),
                                *((name, pa.decimal128(18, 4)) for name in ("open", "high", "low", "close")),
                                ("vol", pa.decimal128(20, 6)), ("amount", pa.decimal128(20, 7))])
            pq.write_table(pa.Table.from_pylist(data, schema=schema), path, row_group_size=2)
            calendar = tmp_path / locations["trade_calendar"]["dg"]["relative_path"]
            calendar.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pylist(_calendar()), calendar)
            source = LakeTechnicalIndicatorPriceSource(config)
        else:
            with engine.begin() as connection:
                connection.execute(MODELS[period].__table__.insert(), data)
            source = PostgresTechnicalIndicatorPriceSource(config, sessionmaker(engine))
        return code, config, source, target

    return create, engine


def _calculate(case, period, start, end, calculations=(PRICE, MA2), *, control=None, adjustment="none"):
    code, config, source, _ = case
    service = TechnicalIndicatorService(source=source, config=config, registry=create_builtin_registry(), control=control)
    return service.calculate(CalculationRequest(
        security_type="index", ts_code=code, period=period, adjustment=adjustment,
        start=datetime.combine(_day(start), time(), SHANGHAI),
        end=datetime.combine(_day(end), time(), SHANGHAI), calculations=calculations,
    ))


@pytest.mark.parametrize("period,source,lower,upper,labels,cutoffs", [
    ("week", WEEKS, "09-28", "10-09", ("09-28", "10-05"), ("09-30", "10-09")),
    ("month", MONTHS, "10-01", "11-20", ("10-01", "11-01"), ("10-30", "11-20")),
])
def test_periods_share_one_price_input_with_actual_cutoffs(warehouse, period, source, lower, upper, labels, cutoffs):
    create, engine = warehouse
    case = create(period, source, limit=2)
    result = _calculate(case, period, lower, upper, (PRICE, MA2, MA250))
    assert result.series.price_unit == "index_point"
    assert (result.series.volume_unit, result.series.amount_unit) == ("share", "CNY")
    assert result.times == tuple(map(_day, labels))
    assert result.source_as_of == tuple(map(_day, cutoffs))
    assert result.range.count == 2 and result.statistics.source_rows == 3
    prices = dict(result.calculations[0].fields)
    assert prices == dict(open=(11., 10.), high=(13., 12.), low=(10., 9.), close=(12., 11.),
                          volume=(1225., 1225.), amount=(36125., 36125.))
    assert dict(result.calculations[1].fields)["value"] == (11., 11.5)
    assert dict(result.calculations[2].fields)["value"] == (None, None)
    with pytest.raises(ResourceLimitError, match="max_output_rows"):
        _calculate(case, period, source[0][0], upper)
    with pytest.raises(SourceUnsupportedError):
        _calculate(case, period, lower, upper, adjustment="qfq")
    if engine is not None:
        assert engine.pool.checkedout() == 0


def test_indicators_and_legal_null_continue_across_batches(warehouse):
    create, _ = warehouse
    case = create("week", WEEKS, batch_rows=1, null_amount=True)
    result = _calculate(case, "week", "09-28", "10-09", (PRICE, MA2, BOLL2, MACD, KDJ))
    price, ma, boll, macd, kdj = (dict(calculation.fields) for calculation in result.calculations)
    assert price["amount"] == (36125., None)
    assert ma["value"] == (11., 11.5)
    assert boll == {"upper": (13., 12.5), "middle": (11., 11.5), "lower": (9., 10.5)}

    # Manually apply the EMA coefficients to closes 10, 12 and 11.
    dif_second = 4 / 13 - 4 / 27
    dif_third = (4 / 13 + 2 / 13 * (1 - 4 / 13)) - (4 / 27 + 2 / 27 * (1 - 4 / 27))
    dea_second = dif_second / 5
    dea_third = (4 * dea_second + dif_third) / 5
    assert macd["dif"] == pytest.approx((dif_second, dif_third))
    assert macd["dea"] == pytest.approx((dea_second, dea_third))
    assert macd["hist"] == pytest.approx((2 * (dif_second - dea_second), 2 * (dif_third - dea_third)))

    # RSV values from the literal fixtures are 200/3, 80 and 60.
    k_first, d_first = 500 / 9, 1400 / 27
    k_second = (2 * k_first + 80) / 3
    k_third = (2 * k_second + 60) / 3
    d_second = (2 * d_first + k_second) / 3
    d_third = (2 * d_second + k_third) / 3
    assert kdj["k"] == pytest.approx((k_second, k_third))
    assert kdj["d"] == pytest.approx((d_second, d_third))
    assert kdj["j"] == pytest.approx((3 * k_second - 2 * d_second, 3 * k_third - 2 * d_third))


def test_partial_updates_keep_period_and_reject_the_later_version(warehouse):
    create, _ = warehouse
    monday = create("week", (*WEEKS, ("10-12", "10-12", 14)))
    first = _calculate(monday, "week", "10-12", "10-12")
    tuesday = create("week", (*WEEKS, ("10-12", "10-13", 16)))
    second = _calculate(tuesday, "week", "10-12", "10-13")
    assert first.times == second.times == (_day("10-12"),)
    assert first.source_as_of == (_day("10-12"),)
    assert second.source_as_of == (_day("10-13"),)
    assert dict(first.calculations[1].fields)["value"] == (12.5,)
    assert dict(second.calculations[1].fields)["value"] == (13.5,)
    with pytest.raises(SourceUnsupportedError, match="later version"):
        _calculate(tuesday, "week", "10-12", "10-12")


@pytest.mark.parametrize("broken,message", [
    ((WEEKS[0], ("09-28", "09-29", 12), WEEKS[2]), "expected 2026-09-30"),
    ((WEEKS[0], WEEKS[2]), "Missing scheduled index period starting 2026-09-28"),
    ((WEEKS[0], ("09-28", "09-29", 12), ("09-29", "09-30", 12), WEEKS[2]), "duplicated"),
    ((WEEKS[0], ("09-28", "10-08", 12), WEEKS[2]), "does not belong"),
])
def test_bad_period_dates_cannot_reach_price_input(warehouse, monkeypatch, broken, message):
    create, _ = warehouse
    case = create("week", broken)

    def fail_if_opened(*args, **kwargs):
        pytest.fail("Invalid dates must fail before opening the price stream")

    monkeypatch.setattr(case[2], "open", fail_if_opened)
    with pytest.raises(SourceContractError, match=message):
        _calculate(case, "week", "09-21", "10-09")


def test_all_closed_week_is_skipped_and_empty_has_no_warmup(warehouse):
    create, _ = warehouse
    case = create("week", (*WEEKS, ("10-12", "10-16", 14), ("10-26", "10-30", 16)))
    result = _calculate(case, "week", "10-12", "10-30")
    assert result.times == (_day("10-12"), _day("10-26"))
    assert result.source_as_of == (_day("10-16"), _day("10-30"))
    with pytest.raises(SourceReadError) as error:
        _calculate(case, "week", "10-19", "10-23")
    assert error.value.detail == "数据缺失"


def test_cancel_releases_read_resources_and_retries(warehouse, monkeypatch):
    create, engine = warehouse
    case = create("week", WEEKS)
    _, config, source, _ = case
    control = ExecutionControl(arrived_at=monotonic(), config=config)
    open_stream = source.open

    def cancel_after_first_read(*args, **kwargs):
        stream = open_stream(*args, **kwargs)
        read_batch = stream.next_batch

        def read(max_rows):
            batch = read_batch(max_rows)
            control.request_stop("cancel")
            return batch

        stream.next_batch = read
        return stream

    with monkeypatch.context() as patch:
        patch.setattr(source, "open", cancel_after_first_read)
        with pytest.raises(CalculationCancelledError):
            _calculate(case, "week", "09-28", "10-09", control=control)
    assert control.resources_released_at is not None
    if engine is not None:
        assert engine.pool.checkedout() == 0
    assert _calculate(case, "week", "09-28", "10-09").range.count == 2


@pytest.mark.parametrize("warehouse", ["prod_pg"], indirect=True)
def test_prod_keeps_one_read_only_snapshot_for_dates_and_prices(warehouse, monkeypatch):
    create, engine = warehouse
    case = create("week", WEEKS)
    code, _, source, _ = case
    open_stream = source.open

    def change_after_date_selection(executor, description, requirement, *, read_context):
        reader = source._connection(read_context, executor.control)
        assert reader.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
        assert reader.exec_driver_sql("SHOW transaction_isolation").scalar_one() == "repeatable read"
        table = IndexWeeklyServing.__table__
        with engine.begin() as writer:
            writer.execute(table.update().where(table.c.ts_code == code, table.c.trade_date == _day("10-09"))
                           .values(close=Decimal("11.5")))
        return open_stream(executor, description, requirement, read_context=read_context)

    with monkeypatch.context() as patch:
        patch.setattr(source, "open", change_after_date_selection)
        before = _calculate(case, "week", "09-28", "10-09")
    after = _calculate(case, "week", "09-28", "10-09")
    assert dict(before.calculations[0].fields)["close"] == (12., 11.)
    assert dict(after.calculations[0].fields)["close"] == (12., 11.5)
    assert engine.pool.checkedout() == 0


@pytest.mark.parametrize("environment,backend", [("local", "dg"), ("prod", "prod_pg")])
def test_runtime_config_and_discovery_enable_only_unadjusted_index_periods(environment, backend):
    config = build_runtime_config(Settings(_env_file=None, APP_ENV=environment,
                                           GOLDENSHARE_LAKE_ROOT="/Volumes/datasource/data_lake"))
    capabilities = describe_calculation(create_builtin_registry(), "price", config=config).source_capabilities
    assert {(item.security_type, item.period, item.adjustment, item.source_id)
            for item in capabilities if item.period in ("week", "month")} == {
                ("index", "week", "none", "index_weekly"), ("index", "month", "none", "index_monthly"),
            }
    for period in ("week", "month"):
        dataset = config.market_dataset_id("index", period)
        assert config.resolve_dataset_location(dataset).backend == backend
        assert not config.enabled_adjustments(config.market_dataset_id("stock", period))


@pytest.mark.parametrize("warehouse", ["dg"], indirect=True)
def test_dg_reads_each_date_group_once_and_rejects_file_replacement(warehouse, monkeypatch):
    create, _ = warehouse
    case = create("week", WEEKS)
    *_, source, target = case
    read_keys = LakePriceLocator._index_period_keys
    scanned = []

    def record_keys(locator, path, index):
        scanned.append(index)
        yield from read_keys(locator, path, index)

    def fail_old_pass(*args, **kwargs):
        pytest.fail("Period data must not use the second date pass")

    monkeypatch.setattr(LakePriceLocator, "_bounds", fail_old_pass)
    monkeypatch.setattr(LakePriceLocator, "_index_period_keys", record_keys)
    assert _calculate(case, "week", "09-28", "10-09").range.count == 2
    assert scanned == [0, 1]

    open_stream = source.open

    def replace_before_read(*args, **kwargs):
        path = Path(target.location["path_template"])
        replacement = path.with_suffix(".replacement.parquet")
        pq.write_table(pq.read_table(path), replacement)
        replacement.replace(path)
        return open_stream(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(source, "open", replace_before_read)
        with pytest.raises(SourceReadError, match="file changed"):
            _calculate(case, "week", "09-28", "10-09")
    assert _calculate(case, "week", "09-28", "10-09").range.count == 2
