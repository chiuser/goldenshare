"""LLD §04.2/06.4/07.2 literal prices and shared-input ownership.

The original LiteralSource tests substitute file access while exercising real
Arrow registration and DuckDB SQL; their expected 5/6 and 20/24 values are the
independently approved LLD literals.  The separately selected D2 final 21-row
test uses real LakeTechnicalIndicatorPriceSource, temporary producer-contract
daily/factor files, PriceInputSession and SQL, with one real control.  It proves
that temporary contract boundary, not formal-Lake coverage or page performance.
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
from src.foundation.technical_indicators.sources.contracts import PriceReadSelection, ReadRequirement, SourceBatch, SourceDescription
from src.foundation.technical_indicators.sources.read_context import SourceReadContext
from src.foundation.technical_indicators.sources.session import PriceInputSession

# Only these shared helpers/fixture are imported; no existing control-creating
# test is called.  The fixture caches by the common pytest base directory.
from test_source_contracts import (
    batch_assembly_files, AssemblyReadTrace, assembly_metrics, assembly_source, assembly_config,
    track_assembly_reader, track_compact_copies, _ASSEMBLY_DATES,
)


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
            selection=PriceReadSelection(days[0], days[-1], days[0], days[-1], 2, 0, True, ()),
            standard_projection=tuple((name, f'b."{name}"') for name in fields))

    def create_locator(self, executor, requirement, *, read_context):
        # This test source already owns producer-shaped literal Arrow batches.
        # The factory creates no table, reader or connection.
        description = self.description

        class Locator:
            def describe(self):
                return description

            def close(self):
                pass

        return Locator()

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
    history = HistoryRequirement(frozenset(("close", "volume")), preceding_rows, None, True, (),
                                initial_null_rule="literal")
    requirement = ReadRequirement(request, history, 2, None, None)
    session = PriceInputSession(executor, source, requirement, read_context=context)
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
    source.description = replace(source.description,
        selection=PriceReadSelection(start, start, start, start, 1, 0, True, ()))
    inputs = PriceInputSession(executor, source, requirement, read_context=context)
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
    description = replace(original, price_paths=paths, factor_paths=factors, standard_projection=projection,
        selection=replace(original.selection, row_groups=((0,),)))
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


def test_assembled_daily_batch_runs_one_qfq_session(batch_assembly_files, monkeypatch, record_property):
    """LLD 18.1 final 21-row request: real Lake source, SQL and one control.

    Independently declared literals: raw OHLC=10/11/9/10, first ten daily
    factors=1, final eleven=2, latest basis=2.  Expected qfq OHLC are therefore
    5/5.5/4.5/5 then 10/11/9/10.  Daily volume/amount remain lot/thousand_CNY.
    """
    from time import monotonic
    started, trace = monotonic(), AssemblyReadTrace()
    cfg = assembly_config(batch_assembly_files)
    control = ExecutionControl(arrived_at=monotonic(), config=cfg)
    cfg, request, requirement, context, _, source, description, _ = assembly_source(
        batch_assembly_files,daily=True,adjustment="qfq",control=control,open_stream=False)
    service = TechnicalIndicatorService(source=source, registry=None, config=cfg)
    connection = executor = inputs = None
    streams, delivered, cleanup = [], [], ()
    verification_sql_rows = 0
    calls = {"open":0,"basis":0,"factors":0}
    original_open, original_basis, original_factors = source.open, source.prepare_basis, source.prepare_factors

    def observed_open(*args, **kwargs):
        calls["open"] += 1
        stream = original_open(*args, **kwargs)
        track_assembly_reader(stream, trace, monkeypatch)
        streams.append(stream)
        return stream

    def observed_basis(*args, **kwargs):
        calls["basis"] += 1
        return original_basis(*args, **kwargs)

    def observed_factors(*args, **kwargs):
        calls["factors"] += 1
        return original_factors(*args, **kwargs)

    monkeypatch.setattr(source,"open",observed_open)
    monkeypatch.setattr(source,"prepare_basis",observed_basis)
    monkeypatch.setattr(source,"prepare_factors",observed_factors)
    track_compact_copies(trace,monkeypatch)
    requirement = replace(requirement, history=replace(requirement.history,preceding_rows=19))
    values = []
    try:
        connection, executor = service._open_execution(control)
        inputs = PriceInputSession(executor,source,requirement,read_context=context)
        inputs.prepare()
        batch = inputs.next_batch()
        assert batch is not None and batch.new_row_count==21
        assert (batch.new_first_seq,batch.new_last_seq,batch.history_rows)==(1,21,0)
        delivered.append(batch.new_row_count)
        assert streams[0]._current_batch is streams[0]._pending_batch is None
        assert inputs.conversion_batches==1 and calls=={"open":1,"basis":1,"factors":1}
        resolved = inputs.resolved_description()
        assert resolved.basis_date==date(2026,2,2) and resolved.basis_value==2.0
        assert resolved.volume_unit=="lot" and resolved.amount_unit=="thousand_CNY"
        verification_sql_rows += 21
        rows = connection.execute(
            f'SELECT trade_date,open,high,low,close,volume,amount FROM "{batch.table_name}" ORDER BY seq').fetchall()
        assert [row[0] for row in rows]==list(_ASSEMBLY_DATES)
        values=[row[1:] for row in rows]
        assert values==[(5.,5.5,4.5,5.,100.,1000.)]*10+[(10.,11.,9.,10.,100.,1000.)]*11
        inputs.retain_required_history()
        verification_sql_rows += 19
        assert executor.scalar("SELECT count(*) FROM ti_history")==19
        inputs.finish_batch()
        assert inputs.next_batch() is None
        assert context.source_rows==trace.actual_read_rows==21
        assert len(trace.reader_opens)==21
    finally:
        cleanup=service._close_execution(control,connection,inputs=inputs)
        assembly_metrics(record_property,"daily_qfq_final",trace,context,started,
            real_controls=1,delivered=delivered,
            sql_rows=(0 if executor is None else executor.sql_processed_rows)+verification_sql_rows,
            cleanup=[str(item) for item in cleanup],
            expected={"input":21,"sizes":[21],"qfq_close_first":5.0,"qfq_close_last":10.0,
                      "conversion_batches":1,"retained_history":19},
            source_calls=calls,stop_requested_at=control.stop_requested_at,
            sql_step_logical_rows=0 if executor is None else executor.sql_processed_rows,
            verification_sql_logical_rows=verification_sql_rows,
            resources_released_at=control.resources_released_at,
            monitor_join_elapsed_ms=control.monitor_join_elapsed_ms,
            value_samples=[] if not values else [values[0],values[-1]])
        assert not cleanup
        if inputs is not None:
            assert inputs._closed and not inputs._registrations and not inputs._tables
        if executor is not None:assert not executor._live_arrow and not executor._live_tables
        assert all(reader.closed for reader in trace.readers)
