"""LLD §04.2/06.4/07.2 literal prices and shared-input ownership.

The source below substitutes only file access. Real Arrow registration and
DuckDB SQL are exercised; these tests do not claim Lake-source integration.
Expected prices 5/6 and 20/24 are the independently approved LLD literals.
"""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pyarrow as pa
import pytest

from src.foundation.config.settings import Settings
from src.foundation.technical_indicators import CalculationInstance, CalculationRequest
from src.foundation.technical_indicators.calculation.calculation import SqlStep
from src.foundation.technical_indicators.calculation.history import HistoryRequirement
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import CalculationCancelledError, ResourceLimitError, SourceUnsupportedError
from src.foundation.technical_indicators.execution_control import ExecutionControl
from src.foundation.technical_indicators.service import TechnicalIndicatorService
from src.foundation.technical_indicators.sources.contracts import ReadRequirement, SourceBatch, SourceDescription
from src.foundation.technical_indicators.sources.read_context import SourceReadContext
from src.foundation.technical_indicators.sources.session import PriceInputSession


def config(**kwargs):
    return replace(KernelConfig.from_settings(Settings(_env_file=None,
        GOLDENSHARE_LAKE_ROOT="/not-opened/data_lake")), **kwargs)


class LiteralStream:
    """Only a file-reader substitute; retains one borrowed Arrow batch."""
    def __init__(self, context, batches):
        self.context, self.batches = context, iter(batches)
        self.current = None
        self.position = 0
        self.reads = 0
        self.closed = False

    def next_batch(self, max_rows):
        assert self.current is None and not self.closed
        self.reads += 1
        self.current = next(self.batches, None)
        if self.current is None:
            return None
        rows = self.current.num_rows
        assert rows <= max_rows
        self.context.record_price_rows(rows)
        result = SourceBatch(self.current, self.position+1, self.position+rows,
                             None, rows, 0, 0)
        self.position += rows
        return result

    def release_current_batch(self):
        self.current = None

    def close(self):
        self.release_current_batch()
        self.closed = True


class LiteralSource:
    """The declared source produces a standard SQL projection, not Python arithmetic."""
    def __init__(self, context, *, input_adjustment="none", batches=2, missing_factor=False):
        fields = ("trade_date", "period_start", "period_end", "source_as_of", "close", "volume")
        days = (date(2026, 1, 5), date(2026, 1, 6))
        arrow = [pa.record_batch([pa.array([day], type=pa.date32())]*4 +
                 [pa.array([close], type=pa.float64()), pa.array([volume], type=pa.float64())],
                 names=fields) for day, close, volume in zip(days, (10., 6.), (100., 200.))]
        if batches == 1:
            arrow = [pa.Table.from_batches(arrow).combine_chunks().to_batches()[0]]
        self.stream = LiteralStream(context, arrow)
        self.basis_calls = self.factor_calls = self.open_calls = 0
        self.missing_factor = missing_factor
        self.description = SourceDescription("literal", "1", input_adjustment,
            "latest" if input_adjustment == "qfq" else None, None, None, "yuan", "shares", "yuan",
            "Asia/Shanghai", "day", "source_start", None, True,
            (("none", "none"), ("none", "qfq"), ("none", "hfq"), ("qfq", "qfq")), False,
            standard_projection=tuple((name, f'b."{name}"') for name in fields))

    def open(self, executor, description, requirement, *, read_context):
        self.open_calls += 1
        return self.stream

    def prepare_basis(self, executor, description, requirement, *, table_name, read_context):
        self.basis_calls += 1
        latest = requirement.request.adjustment == "qfq"
        value, day = (2., date(2026, 1, 6)) if latest else (.5, date(2020, 1, 2))
        executor.execute(SqlStep("literal_basis",
            f"CREATE TEMP TABLE {table_name} AS SELECT ?::DATE basis_date, ?::DOUBLE basis_value",
            (day, value), (), (table_name,), 1))
        return replace(description, basis_date=day, basis_value=value, converted=True)

    def prepare_factors(self, executor, description, requirement, trade_dates, *, table_name, read_context):
        self.factor_calls += 1
        sql = (f"CREATE TEMP TABLE {table_name} AS SELECT * FROM "
               "(VALUES (DATE '2026-01-05',1.::DOUBLE),(DATE '2026-01-06',2.::DOUBLE)) "
               "f(trade_date,adj_factor)")
        if self.missing_factor:
            sql += " WHERE false"
        executor.execute(SqlStep("literal_factors", sql, (), (), (table_name,), 2))


def open_session(target="qfq", *, input_adjustment="none", preceding_rows=1, batches=2, missing_factor=False):
    cfg = config(batch_rows=2)
    control = ExecutionControl(arrived_at=__import__('time').monotonic(), config=cfg)
    service = TechnicalIndicatorService(source=None, registry=None, config=cfg)
    connection, executor = service._open_execution(control)
    context = SourceReadContext(cfg)
    source = LiteralSource(context, input_adjustment=input_adjustment, batches=batches,
                           missing_factor=missing_factor)
    request = CalculationRequest("stock", "600000.SH", "day",
        (CalculationInstance("price", "price", {}),), adjustment=target)
    history = HistoryRequirement(frozenset(("close", "volume")), preceding_rows, True, (),
                                initial_null_rule="literal")
    requirement = ReadRequirement(request, history, 2, None, None)
    session = PriceInputSession(executor, source, source.description, requirement, read_context=context)
    return service, connection, executor, control, source, context, session


@pytest.mark.parametrize("target,expected", [("qfq", [5., 6.]), ("hfq", [20., 24.])])
def test_literal_conversion_once_per_batch_and_retained_adjusted_history(target, expected):
    service, connection, executor, control, source, context, inputs = open_session(target)
    try:
        with pytest.raises(RuntimeError):
            inputs.resolved_description()
        inputs.prepare()
        assert source.description.basis_value is None  # immutable original
        assert inputs.resolved_description().basis_value == (2. if target == "qfq" else .5)
        values = []
        for seq in (1, 2):
            batch = inputs.next_batch()
            assert (batch.new_first_seq, batch.new_last_seq, batch.new_row_count) == (seq, seq, 1)
            assert batch.history_rows == seq-1
            assert source.stream.current is None  # Arrow already released
            # Two independent SQL consumers borrow the same price table; no re-read.
            values.append(executor.scalar(f"SELECT close FROM {batch.table_name} WHERE seq={seq}"))
            assert executor.scalar(f"SELECT volume FROM {batch.table_name} WHERE seq={seq}") == (100., 200.)[seq-1]
            assert source.stream.reads == seq
            with pytest.raises(RuntimeError):
                inputs.next_batch()
            inputs.retain_required_history()
            inputs.finish_batch()
        assert values == expected
        assert inputs.next_batch() is None
        assert source.open_calls == source.basis_calls == 1
        assert source.factor_calls == inputs.conversion_batches == 2
        assert context.source_rows == 2
        assert inputs.read_start == date(2026, 1, 5) and inputs.read_end == date(2026, 1, 6)
        assert executor.scalar("SELECT count(*) FROM ti_history") == 1
    finally:
        assert not service._close_execution(control, connection, inputs=inputs)
    assert source.stream.closed


def test_already_adjusted_input_has_no_factor_calls_and_no_reconversion():
    service, connection, executor, control, source, _, inputs = open_session(input_adjustment="qfq", batches=1)
    try:
        inputs.prepare()
        batch = inputs.next_batch()
        assert executor.scalar(f"SELECT list(close ORDER BY seq) FROM {batch.table_name}") == [10., 6.]
        assert source.basis_calls == source.factor_calls == inputs.conversion_batches == 0
        assert inputs.resolved_description().basis_value is None
        inputs.retain_required_history()
        inputs.finish_batch()
    finally:
        assert not service._close_execution(control, connection, inputs=inputs)


def test_missing_daily_factor_does_not_drop_positions_or_fall_back_to_one():
    service, connection, executor, control, source, _, inputs = open_session(missing_factor=True, batches=1)
    try:
        inputs.prepare()
        batch = inputs.next_batch()
        assert batch.new_row_count == 2
        assert executor.scalar(f"SELECT list(close ORDER BY seq) FROM {batch.table_name}") == [None, None]
        assert executor.scalar(f"SELECT list(volume ORDER BY seq) FROM {batch.table_name}") == [100., 200.]
    finally:
        assert not service._close_execution(control, connection, inputs=inputs)


@pytest.mark.parametrize("period,start,finish,as_of,cutoff,rejected", [
    ("week", date(2026, 1, 5), date(2026, 1, 9), date(2026, 1, 9), date(2026, 1, 6), True),
    ("week", date(2026, 1, 5), date(2026, 1, 9), date(2026, 1, 6), date(2026, 1, 6), False),
    ("month", date(2026, 1, 1), date(2026, 1, 31), date(2026, 1, 31), date(2026, 1, 6), True),
    ("month", date(2026, 1, 1), date(2026, 1, 31), date(2026, 1, 6), date(2026, 1, 6), False),
    # A completed week remains usable even if the file was republished later.
    ("week", date(2026, 1, 5), date(2026, 1, 9), date(2026, 1, 12), date(2026, 1, 13), False),
])
def test_period_cutoff_rejects_future_information_but_keeps_valid_partial_and_completed_bars(
        period, start, finish, as_of, cutoff, rejected):
    service, connection, executor, control, source, context, previous = open_session("none")
    days = (finish, start, finish, as_of)
    batch = pa.record_batch([pa.array([day], type=pa.date32()) for day in days] +
                            [pa.array([10.]), pa.array([100.])],
                            names=("trade_date", "period_start", "period_end", "source_as_of", "close", "volume"))
    source.stream = LiteralStream(context, (batch,))
    requirement = replace(previous.requirement,
                          request=replace(previous.requirement.request, period=period, end=cutoff))
    inputs = PriceInputSession(executor, source, source.description, requirement, read_context=context)
    try:
        inputs.prepare()
        if rejected:
            with pytest.raises(SourceUnsupportedError, match="later version"):
                inputs.next_batch()
        else:
            assert inputs.next_batch().new_row_count == 1
            assert inputs.read_start == start
    finally:
        assert not service._close_execution(control, connection, inputs=inputs)


def test_source_resource_boundaries_and_request_isolation_without_file_io():
    cfg = config(max_source_files=5000, max_input_rows=1500000)
    context = SourceReadContext(cfg)
    for i in range(5000):
        context.record_file(Path(f"/metadata-only/{i}"), 300000)
    assert context.source_files == 5000 and context.source_file_bytes == 1500000000
    context.record_file(Path("/metadata-only/0"), 300000)
    assert context.source_files == 5000
    with pytest.raises(ResourceLimitError):
        context.record_file(Path("/metadata-only/5000"), 1)
    context.record_price_rows(1500000)
    with pytest.raises(ResourceLimitError):
        context.record_price_rows(1)
    assert context.source_rows == 1500000
    assert SourceReadContext(cfg).source_rows == SourceReadContext(cfg).source_files == 0


def test_description_copies_both_levels_of_source_plan_without_freezing_borrowed_batch():
    context = SourceReadContext(config())
    original = LiteralSource(context).description
    paths, factors, projection = [Path("/x")], [[date(2026, 1, 5), Path("/f")]], [["close", 'b."close"']]
    description = replace(original, price_paths=paths, factor_paths=factors, standard_projection=projection)
    paths.clear(); factors[0][1] = Path("/other"); projection[0][1] = "wrong"
    assert description.price_paths == (Path("/x"),)
    assert description.factor_paths == ((date(2026, 1, 5), Path("/f")),)
    assert description.standard_projection == (("close", 'b."close"'),)


@pytest.mark.parametrize('failure', ['open', 'read', 'register', 'unregister',
                                   'cancel_after_read', 'cancel_before_register', 'cancel_before_stage'])
def test_input_failures_keep_the_original_error_and_release_all_owned_resources(monkeypatch, failure):
    """Failure substitutes only the named boundary; real Arrow/SQL still run.

    Cancellation in the two registration gaps must not invent a cleanup failure
    for a table/registration that never reached the underlying connection.
    """
    service, connection, executor, control, source, _, inputs = open_session(batches=1)

    def fail(*args, **kwargs):
        raise OSError('literal ' + failure)

    if failure == 'open':
        monkeypatch.setattr(source, 'open', fail)
    elif failure == 'read':
        monkeypatch.setattr(source.stream, 'next_batch', fail)
    elif failure == 'register':
        register = executor.register_arrow

        def register_then_fail(*args):
            register(*args)
            fail()
        monkeypatch.setattr(executor, 'register_arrow', register_then_fail)
    elif failure == 'unregister':
        monkeypatch.setattr(executor, 'unregister_arrow', fail)
    elif failure == 'cancel_after_read':
        read = source.stream.next_batch

        def read_then_stop(*args):
            batch = read(*args)
            control.request_stop('cancel')
            return batch
        monkeypatch.setattr(source.stream, 'next_batch', read_then_stop)
    elif failure == 'cancel_before_register':
        register = executor.register_arrow

        def stop_before_register(*args):
            control.request_stop('cancel')
            return register(*args)
        monkeypatch.setattr(executor, 'register_arrow', stop_before_register)
    else:
        execute = executor.execute

        def stop_before_stage(step):
            if step.name == 'stage_input':
                control.request_stop('cancel')
            return execute(step)
        monkeypatch.setattr(executor, 'execute', stop_before_stage)
    expected = CalculationCancelledError if failure.startswith('cancel') else OSError
    try:
        with pytest.raises(expected):
            inputs.prepare()
            inputs.next_batch()
    finally:
        errors = service._close_execution(control, connection, inputs=inputs)
    assert errors == (), [str(item) for item in errors]
    assert not inputs._tables and not inputs._registrations
    assert not executor._live_arrow and not executor._live_tables
    if failure != 'open':
        assert source.stream.closed and source.stream.current is None


def test_cancellation_during_basis_or_factor_preparation_keeps_declared_but_uncreated_tables_safe(monkeypatch):
    """A source can see cancellation before its first execute/SQL table."""
    for method in ('prepare_basis', 'prepare_factors'):
        service, connection, executor, control, source, _, inputs = open_session(batches=1)

        def stopped(*args, **kwargs):
            control.request_stop('cancel')
            control.check_active()
        monkeypatch.setattr(source, method, stopped)
        try:
            with pytest.raises(CalculationCancelledError):
                inputs.prepare()
                inputs.next_batch()
        finally:
            errors = service._close_execution(control, connection, inputs=inputs)
        assert errors == (), [str(item) for item in errors]
        assert not inputs._tables and not inputs._registrations
        assert not executor._live_tables and not executor._live_arrow
