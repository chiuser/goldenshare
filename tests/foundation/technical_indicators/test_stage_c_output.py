"""Phase C output and cleanup with independently specified results."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, time, timezone
import json
from time import monotonic
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from goldenshare_technical_indicators.calculation.engine import CalculationEngine
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.configuration.datasets import DATASET_LOCATIONS
from goldenshare_technical_indicators.contracts import CalculationRequest, CalculationStatistics
from goldenshare_technical_indicators.errors import (
    CalculationCancelledError, OutputContractError, OutputEncodingError, SourceReadError,
)
from goldenshare_technical_indicators.execution_control import ExecutionControl
from goldenshare_technical_indicators.executor import DuckDBExecutor
from goldenshare_technical_indicators.output.collector import OutputCollector
from goldenshare_technical_indicators.output.encoding import encode_response_utf8
from goldenshare_technical_indicators.output.result import build_calculation_result
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from goldenshare_technical_indicators.sources.contracts import PriceReadSelection, SourceDescription
from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.config.settings import Settings, technical_indicator_config_from_settings
from test_stage_b_index_minutes import SH, _setup, _write_gold
from test_stage_b_stock_daily import CODE, FRI, MON, TUE, PRICE, MA2, _dg


SHANGHAI = ZoneInfo("Asia/Shanghai")
MA1 = {"calculation_id": "ma", "parameters": {"period": 1}}
BOLL2 = {"calculation_id": "boll", "parameters": {"period": 2}}
MACD = {"calculation_id": "macd", "parameters": {"fast": 2, "slow": 3, "signal": 2}}
KDJ = {"calculation_id": "kdj", "parameters": {}}


def _service(config):
    return TechnicalIndicatorService(config=config, source=LakeTechnicalIndicatorPriceSource(config),
                                     registry=create_builtin_registry())


def _stock(root, *, calculations=(PRICE, MA2), batch_rows=1, first=FRI):
    locations = deepcopy(DATASET_LOCATIONS)
    locations["stock_daily"]["dg"]["enabled_adjustments"] = ("none",)
    config = technical_indicator_config_from_settings(Settings(
        _env_file=None, GOLDENSHARE_LAKE_ROOT=str(root), TECHNICAL_INDICATOR_BATCH_ROWS=batch_rows,
    ), data_location="dg", dataset_locations=locations)
    request = CalculationRequest(
        security_type="stock", ts_code=CODE, period="day", adjustment="none", calculations=calculations,
        start=datetime.combine(first, time(12), SHANGHAI).astimezone(timezone.utc),
        end=datetime.combine(TUE, time(12), SHANGHAI),
    )
    return config, request


def _json(result, config):
    control = ExecutionControl(arrived_at=monotonic(), config=config)
    return json.loads(encode_response_utf8(result, control=control))


def _assert_values(result, expected):
    columns = dict(result.fields)
    assert tuple(columns) == tuple(expected)
    for name, values in expected.items():
        for actual, want in zip(columns[name], values, strict=True):
            if want is None or want == 0:
                assert actual == want
            else:
                assert actual is not None and abs(actual - want) <= 1e-8 + 1e-10 * abs(want)


@pytest.fixture
def literal_lake(tmp_path):
    # The historical formula sample has flat OHLC and closes of 10, 12, 11.
    _dg(tmp_path, {FRI: [10], MON: [12], TUE: [11]})
    for day, price in ((FRI, 10), (MON, 12), (TUE, 11)):
        path = tmp_path / f"silver/quote/stock_daily/trade_date={day}/part-000.parquet"
        table = pq.read_table(path, partitioning=None)
        replacements = {"open": price, "high": price, "low": price}
        if day == TUE:
            replacements["vol"] = None
        if day == MON:
            replacements["amount"] = None
        for name, value in replacements.items():
            table = table.set_column(table.schema.get_field_index(name), name, pa.array([value], type=pa.float64()))
        pq.write_table(table, path)
    return tmp_path


@pytest.mark.parametrize("batch_rows", (1, 3))
def test_public_output_retains_formula_values_and_request_order(literal_lake, batch_rows, monkeypatch):
    config, request = _stock(
        literal_lake, batch_rows=batch_rows, calculations=(PRICE, MA2, BOLL2, MACD, KDJ, MA1, MA2),
    )
    original = CalculationEngine.output_for

    def observe_shared_node(engine, batch):
        outputs = original(engine, batch)
        assert outputs.instances[1][1] is outputs.instances[6][1]
        assert outputs.instances[1][1] is not outputs.instances[5][1]
        return outputs

    monkeypatch.setattr(CalculationEngine, "output_for", observe_shared_node)
    result = _service(config).calculate(request)
    assert result.times == (FRI, MON, TUE) and result.source_as_of is None
    assert result.range.count == 3 and result.statistics.source_rows == 3
    assert (result.series.volume_unit, result.series.amount_unit) == ("share", "CNY")
    assert [item.calculation_id for item in result.calculations] == ["price", "ma", "boll", "macd", "kdj", "ma", "ma"]
    price, ma2, boll, macd, kdj, ma1, repeated = result.calculations
    _assert_values(price, {
        "open": (10, 12, 11), "high": (10, 12, 11), "low": (10, 12, 11), "close": (10, 12, 11),
        "volume": (1225, 1225, None), "amount": (36125, None, 36125),
    })
    _assert_values(ma2, {"value": (None, 11, 11.5)})
    _assert_values(ma1, {"value": (10, 12, 11)})
    assert repeated == ma2 and ma2.parameters == (("period", 2),)
    _assert_values(boll, {"middle": (None, 11, 11.5), "upper": (None, 13, 12.5), "lower": (None, 9, 10.5)})
    _assert_values(macd, {"dif": (0, 1/3, 1/9), "dea": (0, 2/9, 4/27), "hist": (0, 2/9, -2/27)})
    _assert_values(kdj, {"k": (50, 200/3, 550/9), "d": (50, 500/9, 1550/27), "j": (50, 800/9, 1850/27)})
    encoded = _json(result, config)
    assert result.kernel_version == encoded["kernel_version"] == "4.0.0"
    assert encoded["times"] == [str(FRI), str(MON), str(TUE)] and encoded["source_as_of"] is None
    assert encoded["requested"] == {"start": "2026-11-13T12:00:00+08:00", "end": "2026-11-17T12:00:00+08:00"}
    assert all(row.keys() == {"calculation_id", "algorithm_version", "parameters", "fields"}
               for row in encoded["calculations"])
    assert encoded["calculations"][0]["fields"]["volume"][-1] is None
    assert encoded["calculations"][0]["fields"]["amount"][1] is None


def test_day_uses_selected_rows_even_with_noon_bounds_and_prewarm(literal_lake):
    config, request = _stock(literal_lake, first=MON)
    result = _service(config).calculate(request)
    assert result.times == (MON, TUE)
    assert result.range.actual_start == MON and result.range.actual_end == TUE
    assert (result.source.read_start, result.source.read_end) == (FRI, TUE)
    assert dict(result.calculations[1].fields)["value"] == (11, 11.5)


def test_minute_output_is_timezone_aware_and_skips_ordinary_gap(tmp_path):
    _write_gold(tmp_path, SH, (35, 45))
    config, request = _setup(tmp_path, "dg", 35, 45)
    service = _service(config)
    result = service.calculate(request)
    encoded = _json(result, config)
    assert encoded["times"] == ["2026-11-17T09:35:00+08:00", "2026-11-17T09:45:00+08:00"]
    assert encoded["range"]["count"] == 2
    assert encoded["source"]["read_start"] == encoded["times"][0]
    assert encoded["range"]["actual_end"] == encoded["times"][-1]
    assert encoded["source_as_of"] is None
    with pytest.raises(SourceReadError) as error:
        service.calculate(replace(request, end=request.start.replace(minute=30), start=request.start.replace(minute=30)))
    assert str(error.value) == "读取数据失败" and error.value.detail == "数据缺失"


@pytest.mark.parametrize(("period", "first", "last", "cutoffs"), (
    ("week", date(2026, 11, 9), date(2026, 11, 16), (date(2026, 11, 13), date(2026, 11, 19))),
    ("month", date(2026, 10, 1), date(2026, 11, 1), (date(2026, 10, 30), date(2026, 11, 19))),
))
def test_week_and_month_result_preserve_actual_cutoff_dates(tmp_path, period, first, last, cutoffs):
    config, request = _stock(tmp_path, calculations=(MA1,))
    request = replace(request, period=period, start=datetime.combine(first, time(10), SHANGHAI),
                      end=datetime.combine(cutoffs[-1], time(10), SHANGHAI))
    registry = create_builtin_registry()
    instances = TechnicalIndicatorService._describe_output_instances(registry.expand_dependencies(request))
    source = SourceDescription(
        source_id=f"stock_{period}", contract_version="1", input_adjustment="none",
        basis_rule=None, basis_date=None, basis_value=None, price_unit="CNY", volume_unit="share",
        amount_unit="CNY", timezone="Asia/Shanghai", period_label_rule="period_start",
        history_origin_rule="earliest_available_formal_row", available_through=None,
        supports_partial_period=True, supported_adjustment_paths=(("none", "none"),), converted=False,
        selection=PriceReadSelection(first, last, first, last, 2, 0, True, ()),
    )
    result = build_calculation_result(
        request=request, instances=instances, description=source, statistics=CalculationStatistics(2, 0, 0, 0, 0, 0, 0),
        rows=((1, first, cutoffs[0], 10.0), (2, last, cutoffs[1], 20.0)),
        columns=("seq", "period_start", "source_as_of", "value_0_0"), value_columns=(("value_0_0",),),
        read_start=first, read_end=last,
    )
    assert result.times == (first, last) and result.source_as_of == cutoffs
    assert _json(result, config)["source_as_of"] == [str(day) for day in cutoffs]


@pytest.mark.parametrize(("fault", "reason"), (
    ("index", "missing_instance"), ("field", "missing_fields"), ("type", "type_mismatch"),
    ("missing_row", "missing_rows"), ("duplicate", "duplicate_rows"), ("outside", "unexpected_rows"),
    ("nan", "nonfinite_value"), ("inf", "nonfinite_value"), ("null", "unexpected_null"),
    ("cancel", None),
))
def test_second_batch_failure_discards_first_batch_and_releases_resources(literal_lake, monkeypatch, fault, reason):
    config, request = _stock(literal_lake, calculations=(MACD,))
    service = _service(config)
    normal = CalculationEngine.output_for
    original_open = service._open_execution
    executions = []
    merged = []
    normal_append = OutputCollector.append_new_rows

    def record_open(control):
        connection, executor = original_open(control)
        executions.append((executor, control))
        return connection, executor

    def record_append(collector, outputs):
        normal_append(collector, outputs)
        merged.append(collector._tail_rows)

    def corrupt(engine, batch):
        outputs = normal(engine, batch)
        if batch.new_first_seq != 2:
            return outputs
        if fault == "index":
            return replace(outputs, instances=((9, outputs.instances[0][1]),))
        if fault == "cancel":
            engine.executor.control.request_stop("cancel")
            return outputs
        _, output = outputs.instances[0]
        table = '"' + output.table_name + '"'
        statements = {
            "field": f'ALTER TABLE {table} DROP COLUMN dif',
            "type": f'ALTER TABLE {table} ALTER COLUMN dif TYPE VARCHAR',
            "missing_row": f'DELETE FROM {table}',
            "duplicate": f'INSERT INTO {table} SELECT * FROM {table}',
            "outside": f'INSERT INTO {table} SELECT seq + 1, dif, dea, hist FROM {table}',
            "nan": f"UPDATE {table} SET dif = 'NaN'::DOUBLE",
            "inf": f"UPDATE {table} SET dif = 'Infinity'::DOUBLE",
            "null": f'UPDATE {table} SET dif = NULL',
        }
        engine.executor.connection.execute(statements[fault])
        return outputs

    monkeypatch.setattr(service, "_open_execution", record_open)
    error_type = CalculationCancelledError if fault == "cancel" else OutputContractError
    with monkeypatch.context() as patch:
        patch.setattr(CalculationEngine, "output_for", corrupt)
        patch.setattr(OutputCollector, "append_new_rows", record_append)
        with pytest.raises(error_type) as error:
            service.calculate(request)
    assert merged[0] == 1
    if reason:
        assert error.value.reason == reason
        assert error.value.calculation_index == 0
    executor, control = executions[0]
    assert not executor._live_tables and not executor._live_arrow
    assert control.resources_released_at is not None and control.monitor is None
    assert service.calculate(request).times == (FRI, MON, TUE)


@pytest.mark.parametrize(("fault", "reason"), (
    ("short_fetch", "fetch_count_mismatch"), ("wrong_seq", "wrong_batch"), ("same_day", "wrong_batch"),
))
def test_final_fetch_rejects_misaligned_results(literal_lake, monkeypatch, fault, reason):
    config, request = _stock(literal_lake, calculations=(MA1,))
    original = DuckDBExecutor.read_result

    def corrupt(executor, step, **kwargs):
        rows = original(executor, step, **kwargs)
        if step.name != "select_result":
            return rows
        if fault == "short_fetch":
            return rows[:-1]
        first, second, third = rows
        if fault == "wrong_seq":
            return first, (4, *second[1:]), third
        return first, (second[0], first[1], *second[2:]), third

    monkeypatch.setattr(DuckDBExecutor, "read_result", corrupt)
    with pytest.raises(OutputContractError) as error:
        _service(config).calculate(request)
    assert error.value.reason == reason and error.value.stage == "final_fetch"


def test_json_encoder_rejects_nonfinite_payload(literal_lake):
    config, request = _stock(literal_lake, calculations=(MA1,))
    valid = _service(config).calculate(request)
    malformed = replace(valid, calculations=(replace(valid.calculations[0],
                                                     fields=(("value", (1.0, float("nan"), 2.0)),)),))
    with pytest.raises(OutputEncodingError):
        _json(malformed, config)
