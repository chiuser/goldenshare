"""Trend-channel LLD: independent literals/Decimal reference and real calculation SQL.

Engine tests supply canonical PriceBatch columns directly, isolating source I/O.
Public-service tests use the producer-shaped temporary stock daily, calendar,
lifecycle, suspension and adjustment-factor files from the existing nine-turn
tests. No formal Lake, database, D3 fixture or old channel result is accessed.
"""

from datetime import date, datetime, time
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo

import pyarrow as pa
import pytest

from goldenshare_technical_indicators import CalculationRequest
from goldenshare_technical_indicators.calculation.calculation import SqlStep
from goldenshare_technical_indicators.calculation.engine import CalculationEngine
from goldenshare_technical_indicators.calculation.indicators import create_builtin_registry
from goldenshare_technical_indicators.calculation.indicators.trend_channel import DEFINITION
from goldenshare_technical_indicators.discovery import describe_calculation, list_calculations
from goldenshare_technical_indicators.errors import (
    CalculationCancelledError, CalculationExecutionError, CalculationUnsupportedError,
    OutputContractError, SourceContractError, SourceReadError,
)
from goldenshare_technical_indicators.execution_control import ExecutionControl
from goldenshare_technical_indicators.executor import DuckDBExecutor
from goldenshare_technical_indicators.sources.contracts import PriceBatch
from test_executor import opened
from test_nine_turn_calculation import _config, _request, _service, _write_daily_lake
from test_stage_b_stock_daily import CODE


TREND = {"calculation_id": "trend_channel", "parameters": {}}
FIELDS = ("short_upper", "short_lower", "long_upper", "long_lower")
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/quote_trend_channel/000001_sh_daily_input.json"


def _decimal_reference(pairs):
    # Independent scalar recurrence, not SQL or any calculation helper.
    with localcontext() as context:
        context.prec = 70
        state = None
        result = []
        for high, low in pairs:
            prices = (Decimal(str(high)), Decimal(str(low))) * 2
            if state is None:
                state = prices
            else:
                state = tuple(previous + Decimal(2) / Decimal(period + 1) * (price - previous)
                              for previous, price, period in zip(state, prices, (25, 25, 90, 90), strict=True))
            result.append(state)
        return result


def _assert_accurate(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected, strict=True):
        assert len(got) == len(want) == 4
        for value, reference in zip(got, want, strict=True):
            assert abs(Decimal(str(value)) - Decimal(str(reference))) <= Decimal("0.01")


def _engine_values(pairs, *, batch_rows=None, overlap=0):
    """Real engine/SQL/cleanup; only the source is replaced with typed Arrow rows."""
    request = CalculationRequest(security_type="index", ts_code="000001.SH", period="day", adjustment="none",
        start=datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
        end=datetime(2026, 1, 2, tzinfo=ZoneInfo("Asia/Shanghai")), calculations=(TREND,))
    values = []
    with opened() as (connection, executor, control):
        engine = CalculationEngine(executor, create_builtin_registry().expand_dependencies(request))
        try:
            engine.prepare()
            requirement = engine.resolve_history_requirement(1500000)
            assert requirement.warmup_rows == 500
            for start in range(0, len(pairs), batch_rows or len(pairs)):
                end = min(len(pairs), start + (batch_rows or len(pairs)))
                first = max(0, start - overlap)
                columns = pa.record_batch([
                    pa.array(range(first + 1, end + 1), type=pa.int64()),
                    pa.array([float(pair[0]) for pair in pairs[first:end]], type=pa.float64()),
                    pa.array([float(pair[1]) for pair in pairs[first:end]], type=pa.float64()),
                ], names=["seq", "high", "low"])
                executor.register_arrow("ti_fixture", columns)
                executor.execute(SqlStep("fixture_input", "CREATE TEMP TABLE ti_prices AS SELECT * FROM ti_fixture",
                                         (), ("ti_fixture",), ("ti_prices",), end - first))
                executor.unregister_arrow("ti_fixture")
                batch = PriceBatch("ti_prices", start + 1, end, end - start, start - first, (), ("high", "low"), "none")
                engine.consume(batch)
                output = engine.output_for(batch).instances[0][1]
                rows = connection.execute(f"SELECT seq,{','.join(FIELDS)} FROM {output.table_name} ORDER BY seq").fetchall()
                assert [row[0] for row in rows] == list(range(start + 1, end + 1))
                values.extend(tuple(row[1:]) for row in rows)
                engine.release_batch_tables()
                assert not engine.sessions[0].batch_tables
                assert len(engine.sessions[0].state_tables) == 2
                executor.drop_table("ti_prices")
            engine.finish()
        finally:
            control.stop_monitor()
            engine.close()
        assert not executor._live_tables and not executor._live_arrow
        assert not engine.sessions[0].state_tables and not engine.sessions[0].batch_tables
    return values


def test_definition_discovery_and_fixed_history_do_not_use_macd_bounds(tmp_path):
    registry = create_builtin_registry()
    description = describe_calculation(registry, "trend_channel", config=_config(tmp_path))
    assert description in list_calculations(registry, config=_config(tmp_path))
    assert description.source_supported
    assert description.definition is DEFINITION
    assert description.source_capabilities == describe_calculation(registry, "macd", config=_config(tmp_path)).source_capabilities
    assert DEFINITION.algorithm_version == "1.0.0" and DEFINITION.parameter_specs == ()
    assert DEFINITION.input_fields == {"high", "low"}
    assert [(field.name, field.sql_type, field.nullable) for field in DEFINITION.output_fields] == [
        (name, "DOUBLE", False) for name in FIELDS]
    calculation = registry._create(DEFINITION, ())
    assert calculation.dependencies() == ()
    # A plain object has no recursive_warmup/price-bound fields: fixed history needs neither.
    history = calculation.input_requirement(object(), 1000)
    assert history.warmup_rows == 500 and history.preceding_rows == 0
    assert not history.requires_source_origin
    assert history.fields == {"high", "low"}
    assert history.state_fields == ("last_seq", *FIELDS)


@pytest.mark.parametrize("batch_rows", (1, 2, 10))
def test_independent_two_bar_literal_and_single_bar_initialization(batch_rows):
    values = _engine_values(((11, 9), (12, 10)), batch_rows=batch_rows)
    assert values[0] == (11.0, 9.0, 11.0, 9.0)
    # Literal fractions are derived by hand from alpha=2/(N+1).
    assert values[1] == pytest.approx((144 / 13, 118 / 13, 1003 / 91, 821 / 91))
    assert _engine_values(((11, 9),), batch_rows=batch_rows) == [(11.0, 9.0, 11.0, 9.0)]


@pytest.fixture(scope="module")
def historical_pairs():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == "ed585326d64fae260f14e7ec53b885037db31609726ed38cb20c1cbe772e42ad"
    data = json.loads(FIXTURE.read_text())
    assert data["row_count"] == len(data["rows"]) == 1599
    assert data["first_trade_date"] == "2020-01-02" and data["last_trade_date"] == "2026-08-07"
    return tuple((row["high"], row["low"]) for row in data["rows"])


@pytest.mark.parametrize("batch_rows", (17, 257, 2048))
def test_real_snapshot_sql_and_overlapping_batches_match_independent_reference(historical_pairs, batch_rows):
    actual = _engine_values(historical_pairs, batch_rows=batch_rows, overlap=2)
    _assert_accurate(actual, _decimal_reference(historical_pairs))


@pytest.mark.parametrize("target", (700, 1099, 1598))
def test_500_preceding_rows_against_different_start_full_reference(historical_pairs, target):
    reference = _decimal_reference(historical_pairs)
    # Reference starts at snapshot row zero; tested SQL starts at target-500.
    actual = _engine_values(historical_pairs[target - 500:target + 1], batch_rows=128)
    _assert_accurate(actual[-1:], reference[target:target + 1])


def test_485_rows_preserve_the_documented_counterexample(historical_pairs):
    reference = _decimal_reference(historical_pairs)
    # Locate the recorded counterexample independently, not via production SQL.
    target = max(range(485, len(historical_pairs)), key=lambda index:
        abs(_decimal_reference(historical_pairs[index - 485:index + 1])[-1][2] - reference[index][2]))
    actual = _engine_values(historical_pairs[target - 485:target + 1])[-1]
    assert abs(Decimal(str(actual[2])) - reference[target][2]) > Decimal("0.01")
    assert abs(Decimal(str(_engine_values(historical_pairs[target - 500:target + 1])[-1][2])) - reference[target][2]) <= Decimal("0.01")
    # The same EMA seed difference decays by beta**500 in every window.
    # Select its largest value from the independent full-history reference.
    target = max(range(500, len(historical_pairs)), key=lambda index:
        abs(Decimal(historical_pairs[index - 500][0]) - reference[index - 500][2]))
    _assert_accurate(_engine_values(historical_pairs[target - 500:target + 1])[-1:], reference[target:target + 1])


def test_public_paging_counts_warmup_separately_and_accepts_true_origin_shortage(tmp_path):
    closes = tuple(20 + index % 7 for index in range(1003))
    days = _write_daily_lake(tmp_path, closes)
    config = _config(tmp_path)
    expected = _decimal_reference(tuple((value, value) for value in closes))
    for end, first, source_first in ((1002, 503, 3), (502, 3, 0)):
        request = CalculationRequest(security_type="stock", ts_code=CODE, period="day", adjustment="qfq",
            end=datetime.combine(days[end], time.min, ZoneInfo("Asia/Shanghai")), latest_rows=500, calculations=(TREND,))
        result = _service(config).calculate(request)
        assert result.times == days[first:end + 1] and result.range.count == 500
        assert result.source.read_start == days[source_first]
        assert result.statistics.source_rows == end - source_first + 1
        actual = list(zip(*(dict(result.calculations[0].fields)[name] for name in FIELDS), strict=True))
        _assert_accurate(actual, expected[first:end + 1])
        assert result.calculations[0].parameters == () and result.calculations[0].algorithm_version == "1.0.0"
        assert not hasattr(result.calculations[0], "info")


def test_public_same_request_shares_adjustment_and_preserves_existing_indicators(tmp_path):
    closes = tuple(range(11, 31))
    days = _write_daily_lake(tmp_path, closes)
    config = _config(tmp_path, batch_rows=7)
    calculations = tuple({"calculation_id": name, "parameters": {}} for name in ("price", "ma", "boll", "macd", "kdj"))
    request = _request(days[13], days[-1], calculations=calculations)
    baseline = _service(config).calculate(request)
    combined = _service(config).calculate(_request(days[13], days[-1], calculations=(*calculations, TREND)))
    assert combined.times == baseline.times == days[13:]
    assert combined.calculations[:-1] == baseline.calculations
    assert combined.statistics.source_rows == baseline.statistics.source_rows == 20
    assert combined.statistics.source_files == baseline.statistics.source_files
    assert combined.statistics.price_conversion_batches == baseline.statistics.price_conversion_batches
    actual = list(zip(*(dict(combined.calculations[-1].fields)[name] for name in FIELDS), strict=True))
    _assert_accurate(actual, _decimal_reference(tuple((value, value) for value in closes))[13:])


def test_parameters_are_rejected_before_source_reads(tmp_path):
    day = date(2026, 1, 5)
    with pytest.raises(CalculationUnsupportedError, match="Unknown calculation parameter"):
        _service(_config(tmp_path)).calculate(_request(day, day, calculations=(
            {"calculation_id": "trend_channel", "parameters": {"period": 25}},)))


def test_missing_prewarm_file_is_not_treated_as_legal_short_history(tmp_path):
    days = _write_daily_lake(tmp_path, tuple(range(11, 31)))
    # Only a synthetic input is removed; the calendar/lifecycle still require it.
    (tmp_path / f"silver/quote/stock_daily/trade_date={days[1]}/part-000.parquet").unlink()
    with pytest.raises((SourceReadError, SourceContractError)):
        _service(_config(tmp_path)).calculate(_request(days[17], days[-1], calculations=(TREND,)))


@pytest.mark.parametrize(("fault", "reason"), (
    ("field", "missing_fields"), ("nan", "nonfinite_value"),
    ("missing_row", "missing_rows"), ("misaligned", "missing_rows"),
))
def test_invalid_four_rail_output_discards_the_request_and_cleans_resources(tmp_path, monkeypatch, fault, reason):
    days = _write_daily_lake(tmp_path, tuple(range(11, 31)))
    service = _service(_config(tmp_path, batch_rows=7))
    original_output, original_open = CalculationEngine.output_for, service._open_execution
    executions, seen = [], []

    def record_open(control):
        connection, executor = original_open(control)
        executions.append((executor, control))
        return connection, executor

    def corrupt(engine, batch):
        outputs = original_output(engine, batch)
        seen.append(batch.new_first_seq)
        if batch.new_first_seq == 8:
            table = outputs.instances[0][1].table_name
            statements = {
                "field": f"ALTER TABLE {table} DROP COLUMN long_lower",
                "nan": f"UPDATE {table} SET long_lower='NaN'::DOUBLE",
                "missing_row": f"DELETE FROM {table} WHERE seq=8",
                "misaligned": f"UPDATE {table} SET seq=seq+1",
            }
            engine.executor.connection.execute(statements[fault])
        return outputs

    monkeypatch.setattr(service, "_open_execution", record_open)
    monkeypatch.setattr(CalculationEngine, "output_for", corrupt)
    with pytest.raises(OutputContractError) as error:
        service.calculate(_request(days[0], days[-1], calculations=(TREND,)))
    # Shifting seq removes the required first position; the collector reports
    # missing_rows before extra positions. Nonfinite values are checked when
    # the complete result is built, so that case can consume the final batch.
    assert error.value.reason == reason and seen[:2] == [1, 8]
    executor, control = executions[0]
    assert not executor._live_tables and not executor._live_arrow
    assert control.resources_released_at is not None


@pytest.mark.parametrize("stop", ("cancel", "failure"))
def test_partial_segment_failure_cleans_all_resources_and_retry_starts_fresh(tmp_path, monkeypatch, stop):
    closes = tuple(range(11, 31))
    days = _write_daily_lake(tmp_path, closes)
    config = _config(tmp_path, batch_rows=7)
    control = ExecutionControl(arrived_at=monotonic(), config=config)
    request = _request(days[13], days[-1], calculations=(TREND,))
    execute, cleanup_drop = DuckDBExecutor.execute, DuckDBExecutor.cleanup_drop
    cleaned = []

    def interrupt(executor, step):
        result = execute(executor, step)
        if step.name == "trend_channel_segment":
            if stop == "cancel":
                control.request_stop("cancel")
            else:
                raise CalculationExecutionError("injected failure after real trend-channel segment")
        return result

    def record_drop(executor, name):
        if name.startswith("ti_trend_channel_"):
            cleaned.append(name)
        return cleanup_drop(executor, name)

    with monkeypatch.context() as patch:
        patch.setattr(DuckDBExecutor, "execute", interrupt)
        patch.setattr(DuckDBExecutor, "cleanup_drop", record_drop)
        expected = CalculationCancelledError if stop == "cancel" else CalculationExecutionError
        with pytest.raises(expected):
            _service(config, control=control).calculate(request)
    assert set(cleaned) == {f"ti_trend_channel_{name}_0" for name in ("parameters", "state", "work", "output")}
    assert control.resources_released_at is not None
    retry = _service(config).calculate(request)
    actual = list(zip(*(dict(retry.calculations[0].fields)[name] for name in FIELDS), strict=True))
    _assert_accurate(actual, _decimal_reference(tuple((value, value) for value in closes))[13:])
