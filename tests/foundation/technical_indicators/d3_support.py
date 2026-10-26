"""D3-only finite acceptance support; no operation runs at import time.

Producer contracts are technical_indicator_contracts.MINUTE_SCHEMA/DAILY_SCHEMA/
PERIOD_SCHEMA, based on the actual DG producer schemas already checked in D2.
All files are isolated in an owned temporary directory. The required-check
resume restores accounting without reopening an earlier pytest directory.
Only timing/stop signals are substituted in small tests; SQL stays real.
"""

from contextlib import contextmanager
from datetime import date
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from time import monotonic

import pytest

from src.foundation.config.settings import Settings
from src.foundation.clients.local_lake.technical_indicator_price_source import LakeTechnicalIndicatorPriceSource
from src.foundation.technical_indicators import CalculationInstance, CalculationRequest
from src.foundation.technical_indicators.calculation.indicators import create_builtin_registry
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import CalculationCancelledError
from src.foundation.technical_indicators.execution_control import ExecutionControl
from src.foundation.technical_indicators.service import TechnicalIndicatorService


REPORT = Path(__file__).resolve().parents[3] / "reports/technical_indicator_kernel_d3_20261025"
_CACHE = {}


class D3Control:
    """A complete stop/clock substitute, never a fake database executor."""

    clock = staticmethod(monotonic)

    def __init__(self, config):
        self.config = config
        self.arrived_at = monotonic()
        self.work_until = self.target_finish = float("inf")
        self.owner = threading.get_ident()
        self.stop_requested_at = self.resources_released_at = None
        self.cleanup_ready = False
        self.stopped = False

    def _assert_working_thread(self):
        assert threading.get_ident() == self.owner

    def check_active(self):
        if self.stopped:
            raise CalculationCancelledError("D3 deliberately injected stop")

    def start_monitor(self, callback):
        self._assert_working_thread()

    def _note_sql_returned(self):
        pass

    def stop_monitor(self):
        self.cleanup_ready = True
        return ()


class TracedSource:
    """Delegate every source operation; retain only counters and batch sizes."""

    def __init__(self, config):
        self.actual = LakeTechnicalIndicatorPriceSource(config)
        self.context = None
        self.batches = []
        self.open_calls = 0
        self.actual_price_rows = 0

    def __getattr__(self, name):
        return getattr(self.actual, name)

    def describe(self, request, requirement, *, control, read_context):
        self.context = read_context
        record = read_context.record_price_rows

        def observed_rows(rows):
            self.actual_price_rows += rows
            return record(rows)

        read_context.record_price_rows = observed_rows
        return self.actual.describe(request, requirement, control=control, read_context=read_context)

    def open(self, executor, description, requirement, *, read_context):
        self.open_calls += 1
        stream = self.actual.open(executor, description, requirement, read_context=read_context)
        source = self

        class Trace:
            def next_batch(self, max_rows):
                batch = stream.next_batch(max_rows)
                if batch is not None:
                    source.batches.append(batch.selected_rows)
                return batch

            def release_current_batch(self):
                return stream.release_current_batch()

            def close(self):
                return stream.close()

        return Trace()


class ObservedService(TechnicalIndicatorService):
    def _open_execution(self, control):
        connection, self.observed_executor = super()._open_execution(control)
        return connection, self.observed_executor


class D3State:
    def __init__(self, root):
        self.root = root
        self.started = monotonic()
        self.elapsed_before = 0.0
        self._resume_counts = self._resume_limits = None
        self.input_rows = self.sql_rows = self.real_controls = self.fixture_rows = 0
        self.executed = []
        self.queries = []
        self.calls = []
        self.status = "running"
        self.references = {}
        self.times = ()
        self.template_reads = []
        self.config = KernelConfig.from_settings(Settings(_env_file=None, GOLDENSHARE_LAKE_ROOT=str(root)))

    @classmethod
    def resume_saved(cls, saved: dict, *, elapsed_before: float, root: Path):
        """Restore only saved accounting; the caller owns this run's root."""
        root = root.resolve(strict=True)
        assert root.parent == Path("/private/tmp") and root.name.startswith("ti_d3_required_")
        state = cls(root)
        state.literal_root = root / "literal"
        for field, key in (("input_rows", "input_rows"), ("sql_rows", "sql_logical_rows"),
                           ("real_controls", "real_controls"), ("fixture_rows", "fixture_rows")):
            value = saved[key]
            assert type(value) is int and value >= 0
            setattr(state, field, value)
        for field, key in (("executed", "executed_cases"), ("queries", "queries"),
                           ("calls", "calls"), ("template_reads", "template_reads")):
            assert isinstance(saved[key], list)
            setattr(state, field, list(saved[key]))
        assert elapsed_before >= saved["elapsed_seconds"]
        state.elapsed_before = elapsed_before
        state._resume_counts = (state.input_rows, state.sql_rows, state.real_controls)
        state.status = "running_approved_resume"
        return state

    def prepare_required_literals(self):
        """Only three producer-shaped files, never a long fixture/reference."""
        import pyarrow as pa
        import pyarrow.parquet as pq
        from src.foundation.technical_indicators.service import connect_private_memory_instance

        # Independent copy of SILVER_STOCK_DAILY_SCHEMA in the current DG
        # run_contracts/asset_column_schemas.py; do not infer it from a query.
        expected = (
            ("ts_code", pa.string()), ("trade_date", pa.date32()),
            *((name, pa.float64()) for name in (
                "open", "high", "low", "close", "pre_close", "change_amount",
                "pct_chg", "vol", "amount",
            )),
        )
        self.fixture_files = []
        connection = None
        primary_error = None
        try:
            connection = connect_private_memory_instance(self.config)
            for text, price in (("2026-01-05", 10.0), ("2026-01-06", 12.0), ("2026-01-07", 11.0)):
                path = self.literal_root / f"silver/quote/stock_daily/trade_date={text}/part-000.parquet"
                path.parent.mkdir(parents=True)
                copied = self.query(connection, "fixture_required_literal", """COPY (
                    SELECT '600000.SH'::VARCHAR AS ts_code, $day::DATE AS trade_date,
                        $price::DOUBLE AS open, $price::DOUBLE AS high,
                        $price::DOUBLE AS low, $price::DOUBLE AS close,
                        $price::DOUBLE AS pre_close, 0.0::DOUBLE AS change_amount,
                        0.0::DOUBLE AS pct_chg, 100.0::DOUBLE AS vol, 1000.0::DOUBLE AS amount
                    ) TO $target (FORMAT PARQUET)""", rows=1,
                    bindings={"day": date.fromisoformat(text), "price": price, "target": str(path)})
                assert copied == [(1,)]
                self.fixture_rows += 1
                self.save()
                reader = pq.ParquetFile(path)
                metadata_error = None
                try:
                    assert reader.metadata.num_rows == 1
                    actual = tuple((field.name, field.type) for field in reader.schema_arrow)
                    assert actual == expected
                    self.fixture_files.append({
                        "path": str(path), "rows": 1,
                        "fields": [(name, str(data_type)) for name, data_type in actual],
                    })
                except BaseException as error:
                    metadata_error = error
                    raise
                finally:
                    try:
                        reader.close()
                    except BaseException as error:
                        if metadata_error is None:
                            raise
                        metadata_error.add_note(f"Fixture metadata cleanup: {type(error).__name__}: {error}")
                self.save()
        except BaseException as error:
            primary_error = error
            raise
        finally:
            if connection is not None:
                try:
                    connection.close()
                except BaseException as error:
                    if primary_error is None:
                        raise
                    primary_error.add_note(f"Fixture connection cleanup: {type(error).__name__}: {error}")

    def save(self):
        REPORT.mkdir(parents=True, exist_ok=True)
        (REPORT / "progress.json").write_text(json.dumps({
            "status": self.status, "executed_cases": self.executed,
            "input_rows": self.input_rows, "sql_logical_rows": self.sql_rows,
            "real_controls": self.real_controls, "fixture_rows": self.fixture_rows,
            "elapsed_seconds": self.elapsed_before + monotonic() - self.started,
            "fixture_root": str(self.root),
            "queries": self.queries, "calls": self.calls,
            "template_reads": self.template_reads,
            "fixture_files": getattr(self, "fixture_files", []),
        }, ensure_ascii=False, indent=2, default=str) + "\n")

    def budget(self):
        assert self.input_rows <= 100000
        assert self.sql_rows <= 5000000
        assert self.real_controls <= 4
        assert self.elapsed_before + monotonic() - self.started <= 300
        if self._resume_limits is not None:
            counts = (self.input_rows, self.sql_rows, self.real_controls)
            assert all(now - before <= limit for now, before, limit in
                       zip(counts, self._resume_counts, self._resume_limits))

    @contextmanager
    def case(self, name):
        started = monotonic()
        before = (self.input_rows, self.sql_rows, self.real_controls)
        entry = {"case": name, "status": "running"}
        self.executed.append(entry)
        self.save()
        try:
            self.budget()
            yield
            assert monotonic() - started <= 30
            self.budget()
            entry["status"] = "passed"
        except BaseException as error:
            entry.update(status="failed", error_type=type(error).__name__, error=str(error))
            self.status = "failed_stop_without_retry"
            raise
        finally:
            entry.update(elapsed_seconds=monotonic() - started,
                         input_rows=self.input_rows - before[0],
                         sql_logical_rows=self.sql_rows - before[1],
                         real_controls=self.real_controls - before[2])
            self.save()

    def query(self, connection, name, sql, *, rows, bindings=()):
        """Reference/setup SQL is charged even if execute or fetching fails."""
        self.sql_rows += rows
        entry = {"name": name, "logical_input_rows": rows, "status": "running"}
        self.queries.append(entry)
        self.save()
        started = monotonic()
        try:
            self.budget()
            cursor = connection.execute(sql, bindings)
            result = cursor.fetchall()
            entry.update(status="passed", output_rows=len(result))
            return result
        except BaseException as error:
            entry.update(status="failed", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            entry["elapsed_seconds"] = monotonic() - started
            self.save()

    def run(self, request, *, real=False, config=None, source=None, registry=None):
        config = config or self.config
        source = source or TracedSource(config)
        if real:
            self.real_controls += 1
            self.save()
            self.budget()
            control = ExecutionControl(arrived_at=monotonic(), config=config)
        else:
            control = D3Control(config)
        service = ObservedService(source=source, registry=registry or create_builtin_registry(),
                                  config=config, control=control)
        call = {"real_control": real, "period": request.period, "status": "running"}
        self.calls.append(call)
        self.save()
        template_start = len(self.template_reads)
        result = None
        try:
            result = service.calculate(request)
            call["status"] = "passed"
            return result, service, source
        except BaseException as error:
            call.update(status="failed", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            context = getattr(source, "context", None)
            read_rows = getattr(source, "actual_price_rows", context.source_rows if context is not None else 0)
            self.input_rows += read_rows
            executor = getattr(service, "observed_executor", None)
            sql_rows = executor.sql_processed_rows if executor is not None else 0
            self.sql_rows += sql_rows
            call.update(source_rows=read_rows, sql_logical_rows=sql_rows,
                        batches=list(getattr(source, "batches", ())),
                        source_open_calls=getattr(source, "open_calls", None),
                        template_reads=self.template_reads[template_start:])
            if executor is not None:
                call["steps"] = [dict(step_name=s.step_name, logical_input_rows=s.logical_input_rows,
                                      output_rows=s.output_rows, failed=s.failed)
                                 for s in executor.statistics]
                call["live_tables"] = sorted(executor._live_tables)
                call["live_arrow"] = sorted(executor._live_arrow)
            self.save()


@contextmanager
def template_io(state, monkeypatch):
    """Observe real filesystem opens, rather than calls to a loader helper."""
    original = io.open

    def observed(file, *args, **kwargs):
        try:
            path = Path(file)
        except TypeError:
            path = None
        if path is not None and path.suffix == ".sql" and any(
            part in str(path) for part in (
                "technical_indicators/calculation/sql/", "technical_indicators/output/sql/",
            )
        ):
            state.template_reads.append(str(path.resolve()))
        return original(file, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(io, "open", observed)
        yield


def assert_templates_once(call, expected_names):
    names = [Path(path).name for path in call["template_reads"]]
    assert set(names) == set(expected_names)
    assert len(names) == len(set(names))


def request(calculations=None, **kwargs):
    return CalculationRequest(**(dict(
        security_type="stock", ts_code="600000.SH", period="1m",
        calculations=calculations or (CalculationInstance("price", "price", {}),),
    ) | kwargs))


def default_calculations():
    return (CalculationInstance("macd", "macd", {}), CalculationInstance("kdj", "kdj", {}),
            *(CalculationInstance("ma" + str(period), "ma", {"period": period})
              for period in (5, 10, 20, 30, 60, 90, 250)),
            CalculationInstance("boll", "boll", {}), CalculationInstance("price", "price", {}))


def values(result):
    return {item.instance_id: dict(item.fields) for item in result.calculations}


def close_enough(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        if want is None:
            assert got is None
        else:
            assert got is not None and abs(got - want) <= 1e-8 + 1e-10 * abs(want)


def assert_closed(service):
    executor = service.observed_executor
    assert not executor._live_tables and not executor._live_arrow
    assert service.control.resources_released_at is not None
    monitor = getattr(service.control, "monitor", None)
    assert monitor is None or not monitor.is_alive()


@pytest.fixture(scope="session")
def d3_data(tmp_path_factory, request):
    plan = json.loads((REPORT / "plan.json").read_text())
    resume = plan.get("resume")
    if resume is not None:
        # Reject an accidental full-suite command before opening any source or
        # running SQL. Parameterized cases keep their original fixed variants.
        items = request.session.items
        selected = tuple(dict.fromkeys(item.nodeid.split("[", 1)[0] for item in items))
        assert selected == tuple(resume["node_ids"])
        assert len(items) == resume["expected_items"]
        assert plan["status"] == "approved_D3_final_fetch_count"
        assert resume["baseline_file"] == "final_fetch_count_baseline_20261026.json"
        assert resume["fixture_mode"] == "owned_required_literals"
        baseline = REPORT / resume["baseline_file"]
        if baseline in _CACHE:
            return _CACHE[baseline]
        saved = json.loads(baseline.read_text())["progress.json"]
        lifecycle_record = REPORT / "fixture_final_fetch_count_20261026.json"
        assert not lifecycle_record.exists(), "Do not recreate a fixture after a prior attempt"
        temporary = TemporaryDirectory(dir="/private/tmp", prefix="ti_d3_required_")
        root = Path(temporary.name)
        state = None

        def finish_owned_directory():
            from src.foundation.technical_indicators.service import raise_primary_or_cleanup_error_if_any

            errors = []
            try:
                temporary.cleanup()
            except BaseException as error:
                errors.append(error)
            removed = not root.exists()
            if not removed and not errors:
                errors.append(RuntimeError("The owned D3 fixture directory remains after cleanup"))
            record = dict(root=str(root), removed=removed, status="failed" if errors else "passed",
                          errors=[f"{type(error).__name__}: {error}" for error in errors])
            try:
                lifecycle_record.write_text(json.dumps(record, indent=2) + "\n")
            except BaseException as error:
                errors.append(error)
            _CACHE.pop(baseline, None)
            if state is not None:
                if errors:
                    state.status = "failed_fixture_cleanup_stop_without_retry"
                try:
                    state.save()
                except BaseException as error:
                    errors.append(error)
            raise_primary_or_cleanup_error_if_any(None, tuple(errors))

        # Registered immediately: pytest also invokes this finalizer if setup
        # fails before returning a state. The closure holds the directory owner
        # until the session finishes, including both importing test modules.
        request.addfinalizer(finish_owned_directory)
        try:
            state = D3State.resume_saved(saved, elapsed_before=resume["elapsed_before_seconds"], root=root)
            state._resume_limits = (resume["source_input_rows_upper_bound"],
                                    resume["sql_logical_rows_upper_bound"], resume["new_real_controls"])
            state.budget()
            state.save()
            with state.case("required_fixture_three_literals"):
                state.prepare_required_literals()
                assert state.fixture_rows - saved["fixture_rows"] == resume["fixture_rows_upper_bound"] == 3
                assert state.references == {} and state.times == ()
            _CACHE[baseline] = state
            return state
        except BaseException as error:
            if state is not None:
                state.status = "failed_fixture_preparation_stop_without_retry"
                try:
                    state.save()
                except BaseException as save_error:
                    error.add_note(f"Fixture failure record: {type(save_error).__name__}: {save_error}")
            raise
    root = (tmp_path_factory.getbasetemp() / "ti_d3_acceptance").resolve()
    if root in _CACHE:
        return _CACHE[root]
    assert not root.exists(), "Do not silently rebuild a partial D3 fixture"
    root.mkdir()
    state = D3State(root)
    _CACHE[root] = state
    from d3_reference import build_fixture_and_reference
    with state.case("fixture_and_independent_reference"):
        build_fixture_and_reference(state)
    return state
