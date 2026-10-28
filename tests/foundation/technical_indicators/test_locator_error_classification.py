"""LLD 19.34 and locator-test-cleanup-20261028: locator error regression.

Producer contract: local_lake.technical_indicator_contracts.DAILY_SCHEMA,
already checked against the daily Silver producer. This module owns three
date-partition files per data test. State and metrics belong only to the
current test; historical acceptance files are never read or written.
Only D3Control and the specified raw Arrow/close boundary are substituted.
"""

from contextlib import contextmanager
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from types import SimpleNamespace

import pytest

from d3_support import D3Control
from src.foundation.clients.local_lake import technical_indicator_price_locator as locator_module
from src.foundation.clients.local_lake import technical_indicator_price_source as source_module
from src.foundation.clients.local_lake.technical_indicator_contracts import DAILY_SCHEMA
from src.foundation.technical_indicators import CalculationInstance, CalculationRequest
from src.foundation.technical_indicators.calculation.history import HistoryRequirement
from src.foundation.technical_indicators.calculation.indicators import create_builtin_registry
from src.foundation.technical_indicators.configuration import KernelConfig
from src.foundation.technical_indicators.errors import (
    CalculationCancelledError, CalculationDeadlineError, ResourceCleanupError,
    ResourceLimitError, SourceReadError,
)
from src.foundation.technical_indicators.service import TechnicalIndicatorService
from src.foundation.technical_indicators.sources.contracts import ReadRequirement
from src.foundation.technical_indicators.sources.read_context import SourceReadContext


_DATES = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7))
_CLOSES = (10.0, 12.0, 11.0)
_NODES = (
    "test_locator_read_errors_and_cleanup",
    "test_locator_metadata_memory_and_close_errors",
    "test_locator_preserves_existing_errors",
)


def _request():
    return CalculationRequest("stock", "600000.SH", "day",
        (CalculationInstance("price", "price", {}),), adjustment="none", limit=3)


class _ObservedSource(source_module.LakeTechnicalIndicatorPriceSource):
    def __init__(self, config):
        super().__init__(config)
        self.context = None
        self.locators, self.streams = [], []
        self.price_rows = 0

    def create_locator(self, executor, requirement, *, read_context):
        self.context = read_context
        original = read_context.record_price_rows

        def record(rows):
            self.price_rows += rows
            return original(rows)

        read_context.record_price_rows = record
        locator = super().create_locator(executor, requirement, read_context=read_context)
        self.locators.append(locator)
        return locator

    def open(self, executor, description, requirement, *, read_context):
        stream = super().open(executor, description, requirement, read_context=read_context)
        self.streams.append(stream)
        return stream


class _ObservedService(TechnicalIndicatorService):
    def _open_execution(self, control):
        connection, executor = super()._open_execution(control)
        self.observed_connection, self.observed_executor = connection, executor
        return connection, executor


class _Metadata:
    def __init__(self, actual, faults):
        self.actual, self.faults = actual, faults
        self.close_calls = 0

    def __getattr__(self, name):
        return getattr(self.actual, name)

    def close(self):
        self.close_calls += 1
        if self.faults.mode == "metadata_close_failure" and not self.faults.injected:
            self.faults.injected = True
            raise self.faults.error
        self.actual.close()


class _Reader:
    def __init__(self, actual, faults):
        self.actual, self.faults = actual, faults
        self.read_calls = self.close_calls = 0
        self.closed = False

    def read_next_batch(self):
        self.read_calls += 1
        if (self.read_calls == 2 and self.faults.mode in ("key_arrow_invalid", "key_arrow_memory")
                and not self.faults.injected):
            self.faults.injected = True
            raise self.faults.error
        batch = self.actual.read_next_batch()
        self.faults.actual_key_rows += batch.num_rows
        return batch

    def close(self):
        self.close_calls += 1
        if self.faults.mode == "key_close_failure" and not self.faults.injected:
            self.faults.injected = True
            raise self.faults.error
        self.actual.close()
        self.closed = True


class _Scanner:
    def __init__(self, actual, faults):
        self.actual, self.faults = actual, faults

    def to_reader(self):
        reader = _Reader(self.actual.to_reader(), self.faults)
        self.faults.readers.append(reader)
        return reader


class _Faults:
    """Delegate real Parquet/Scanner calls; change only the named failure."""

    def __init__(self, mode):
        import pyarrow as pa
        self.mode, self.injected = mode, False
        self.metadata, self.readers = [], []
        self.opens = self.actual_key_rows = 0
        self.error = {
            "normal": None,
            "metadata_arrow_invalid": pa.ArrowInvalid("deliberate metadata decoding failure"),
            "key_arrow_invalid": pa.ArrowInvalid("deliberate key decoding failure"),
            "key_arrow_memory": pa.ArrowMemoryError("deliberate key allocation failure"),
            "inspect_memory": MemoryError("deliberate projected metadata allocation failure"),
            "metadata_close_failure": OSError("deliberate metadata close failure"),
            "key_close_failure": OSError("deliberate key close failure"),
        }[mode]

    @contextmanager
    def installed(self, monkeypatch):
        import pyarrow.parquet as pq
        original_arrow = locator_module._arrow
        pa, ds, fs, _ = original_arrow()
        original_parquet_file = pq.ParquetFile

        def parquet_file(*args, **kwargs):
            self.opens += 1
            if ((self.mode == "metadata_arrow_invalid" and self.opens == 1)
                    or (self.mode == "inspect_memory" and self.opens == 4)):
                self.injected = True
                raise self.error
            reader = _Metadata(original_parquet_file(*args, **kwargs), self)
            self.metadata.append(reader)
            return reader

        def scanner_from_fragment(*args, **kwargs):
            return _Scanner(ds.Scanner.from_fragment(*args, **kwargs), self)

        class Dataset:
            Scanner = SimpleNamespace(from_fragment=scanner_from_fragment)

            def __getattr__(self, name):
                return getattr(ds, name)

        with monkeypatch.context() as patch:
            patch.setattr(pq, "ParquetFile", parquet_file)
            patch.setattr(locator_module, "_arrow", lambda: (pa, Dataset(), fs, pq))
            yield

    def check_closed(self):
        assert all(item.actual.closed for item in self.metadata)
        # RecordBatchReader has no public closed property. The flag is set only
        # after delegating its real close successfully; locator refs are checked too.
        assert all(item.closed for item in self.readers)
        if self.mode == "metadata_close_failure":
            assert self.metadata[0].close_calls == 2
        if self.mode == "key_close_failure":
            assert self.readers[0].close_calls == 2


class _State:
    def __init__(self, root):
        from src.foundation.config.settings import Settings
        self.root = root
        self.started = monotonic()
        self.saved = dict(status="running", completed_nodes=[], attempts=[], calls=[],
            fixture_queries=[], preservation=[], fixture_root=str(root))
        self.config = KernelConfig.from_settings(Settings(_env_file=None, GOLDENSHARE_LAKE_ROOT=str(root)))
        self.input_rows = self.locator_rows = self.sql_rows = self.fake_controls = 0
        self.save()

    def save(self):
        self.saved.update(new_input_rows=self.input_rows, new_locator_rows=self.locator_rows,
            new_sql_logical_rows=self.sql_rows, new_real_controls=0, new_fake_controls=self.fake_controls,
            program_elapsed_seconds=monotonic() - self.started)

    def budget(self):
        self.save()
        assert self.input_rows <= 9 and self.locator_rows <= 10 and self.sql_rows <= 61

    @contextmanager
    def case(self, name):
        assert name in _NODES and name not in self.saved["completed_nodes"]
        entry = dict(node=name, status="running")
        self.saved["attempts"].append(entry)
        self.save()
        try:
            yield
            self.budget()
            entry["status"] = "passed"
            self.saved["completed_nodes"].append(name)
        except BaseException as error:
            entry.update(status="failed", error_type=type(error).__name__, error=str(error))
            self.saved["status"] = "failed"
            raise
        finally:
            self.save()

    def prepare(self):
        import duckdb
        import pyarrow as pa
        import pyarrow.parquet as pq
        expected_schema = pa.schema([("ts_code",pa.string()),("trade_date",pa.date32()),
            *((name,pa.float64()) for name in ("open","high","low","close","vol","amount"))])
        assert tuple(expected_schema.names) == tuple(name for name,_ in DAILY_SCHEMA)
        con = duckdb.connect(":memory:",config={"threads":1,"max_temp_directory_size":"0B"})
        try:
            for day,value in zip(_DATES,_CLOSES):
                path = self.root/f"silver/quote/stock_daily/trade_date={day.isoformat()}/part-000.parquet"
                path.parent.mkdir(parents=True)
                self.input_rows += 1
                self.sql_rows += 1
                event = dict(day=day.isoformat(), input_rows=1, logical_rows=1, status="running")
                self.saved["fixture_queries"].append(event)
                self.budget()
                actual = con.execute("""COPY (SELECT '600000.SH'::VARCHAR AS ts_code,$day::DATE AS trade_date,
                    $value::DOUBLE AS "open",$value::DOUBLE AS "high",$value::DOUBLE AS "low",$value::DOUBLE AS "close",
                    100::DOUBLE AS vol,1000::DOUBLE AS amount) TO $path (FORMAT PARQUET)""",
                    dict(day=day,value=value,path=str(path))).fetchall()
                assert actual == [(1,)]
                with pq.ParquetFile(path) as metadata:
                    assert metadata.schema_arrow == expected_schema and metadata.metadata.num_rows == 1
                event["status"] = "passed"
                self.save()
        finally:
            con.close()

    def run(self, mode, expected, monkeypatch):
        import duckdb
        source = _ObservedSource(self.config)
        self.fake_controls += 1
        service = _ObservedService(source=source, registry=create_builtin_registry(),
            config=self.config, control=D3Control(self.config))
        faults = _Faults(mode)
        entry = dict(mode=mode,status="running")
        self.saved["calls"].append(entry)
        returned = None
        try:
            with faults.installed(monkeypatch):
                if expected is None:
                    returned = service.calculate(_request())
                    assert returned.times == _DATES and returned.msg == ""
                    values = dict(returned.calculations[0].fields)
                    for name in ("open","high","low","close"):
                        assert values[name] == _CLOSES
                    assert values["volume"] == (100.0,)*3 and values["amount"] == (1000.0,)*3
                    assert returned.range.count == 3
                    entry["status"] = "passed"
                else:
                    with pytest.raises(expected) as caught:
                        returned = service.calculate(_request())
                    assert returned is None and caught.value.__cause__ is faults.error
                    assert faults.injected
                    entry.update(status="expected_failure", error_type=type(caught.value).__name__,
                        cause_type=type(caught.value.__cause__).__name__, cause_identity=True)
        except BaseException as error:
            entry.update(status="unexpected_failure_stop", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            executor = getattr(service,"observed_executor",None)
            self.input_rows += source.price_rows
            keys = source.context.locator_rows if source.context is not None else 0
            self.locator_rows += keys
            logical = executor.sql_processed_rows if executor is not None else 0
            self.sql_rows += logical
            entry.update(price_rows=source.price_rows, locator_rows=keys, sql_logical_rows=logical,
                actual_key_rows=faults.actual_key_rows, metadata_open_calls=faults.opens,
                steps=[dict(name=s.step_name,rows=s.logical_input_rows,output=s.output_rows,failed=s.failed)
                    for s in executor.statistics] if executor is not None else [])
            self.save()
            assert executor is not None and not executor._live_tables and not executor._live_arrow
            assert service.control.cleanup_ready and service.control.resources_released_at is not None
            assert all(item._closed and not item._tables and not item._registrations
                and all(getattr(item,name) is None for name in ("_metadata_reader","_reader","_scanner","_fragment"))
                for item in source.locators)
            assert all(item._closed for item in source.streams)
            faults.check_closed()
            expected_keys, expected_sql = {
                "normal": (3,41), "metadata_arrow_invalid": (0,0),
                "key_arrow_invalid": (1,1), "key_arrow_memory": (1,1),
                "inspect_memory": (3,3), "metadata_close_failure": (1,1),
                "key_close_failure": (1,1),
            }[mode]
            assert keys == faults.actual_key_rows == expected_keys
            assert logical == expected_sql and source.price_rows == (3 if mode == "normal" else 0)
            if mode in ("key_arrow_invalid","key_arrow_memory"):
                assert faults.readers[0].read_calls == 2
                assert [(item["rows"],item["output"]) for item in entry["steps"]
                    if item["name"] == "locate_stage"] == [(1,1)]
            if mode == "inspect_memory":
                assert faults.opens == 4
            self.sql_rows += 1
            with pytest.raises(duckdb.ConnectionException,match="[Cc]losed"):
                service.observed_connection.execute("SELECT 1")
            entry["cleanup"] = "passed"
            self.budget()


@pytest.fixture
def locator_error_state(tmp_path, monkeypatch, record_property):
    history = Path(__file__).resolve().parents[3] / "reports"
    original_read, original_write = Path.read_text, Path.write_text

    def read(path, *args, **kwargs):
        assert not path.absolute().is_relative_to(history), "Regression read acceptance history"
        return original_read(path, *args, **kwargs)

    def write(path, *args, **kwargs):
        assert not path.absolute().is_relative_to(history), "Regression wrote acceptance history"
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(Path, "write_text", write)
    temporary = TemporaryDirectory(prefix="locator_error_", dir=tmp_path)
    state = None
    try:
        state = _State(Path(temporary.name))
        yield state
    finally:
        cleanup_error = None
        try:
            temporary.cleanup()
        except BaseException as error:
            cleanup_error = error
            raise
        finally:
            if state is not None:
                removed = not state.root.exists()
                state.saved["fixture_cleanup"] = dict(removed=removed,
                    error_type=type(cleanup_error).__name__ if cleanup_error is not None else None)
                passed = (removed and cleanup_error is None and state.saved["status"] != "failed"
                          and len(state.saved["completed_nodes"]) == 1)
                state.saved["status"] = "passed" if passed else "failed"
                state.save()
                record_property("locator_error_metrics", json.dumps(state.saved, ensure_ascii=False))
                assert removed, "The test's temporary directory was not released"


@pytest.fixture
def locator_error_data(locator_error_state):
    locator_error_state.prepare()
    return locator_error_state


def test_locator_read_errors_and_cleanup(locator_error_data,monkeypatch):
    state = locator_error_data
    with state.case("test_locator_read_errors_and_cleanup"):
        for mode,expected in (("normal",None),("metadata_arrow_invalid",SourceReadError),
                ("key_arrow_invalid",SourceReadError),("key_arrow_memory",ResourceLimitError)):
            state.run(mode,expected,monkeypatch)
        assert len(state.saved["calls"]) == state.fake_controls == 4
        assert (state.input_rows,state.locator_rows,state.sql_rows) == (6,5,50)


def test_locator_metadata_memory_and_close_errors(locator_error_data,monkeypatch):
    state = locator_error_data
    with state.case("test_locator_metadata_memory_and_close_errors"):
        for mode,expected in (("inspect_memory",ResourceLimitError),
                ("metadata_close_failure",ResourceCleanupError),("key_close_failure",ResourceCleanupError)):
            state.run(mode,expected,monkeypatch)
        assert len(state.saved["calls"]) == state.fake_controls == 3
        assert (state.input_rows,state.locator_rows,state.sql_rows) == (3,5,11)


def test_locator_preserves_existing_errors(locator_error_state,monkeypatch):
    state = locator_error_state
    with state.case("test_locator_preserves_existing_errors"):
        requirement = ReadRequirement(_request(),HistoryRequirement(frozenset(("close",)),0,0,
            False,(),"price"),8192,None,None)
        for error in (SourceReadError("already classified"),CalculationCancelledError("cancelled"),
                CalculationDeadlineError("deadline"),KeyboardInterrupt("interrupted"),ValueError("programming error")):
            state.fake_controls += 1
            control = D3Control(state.config)
            locator = locator_module.LakePriceLocator(source_module.LakeTechnicalIndicatorPriceSource(state.config),
                SimpleNamespace(control=control),requirement,read_context=SourceReadContext(state.config))
            with monkeypatch.context() as patch:
                def fail(*args):
                    raise error
                patch.setattr(locator,"_select",fail)
                try:
                    with pytest.raises(type(error)) as caught:
                        locator.describe()
                    assert caught.value is error and caught.value.__cause__ is None
                finally:
                    locator.close()
            assert locator._closed and not locator._tables and not locator._registrations
            state.saved["preservation"].append(dict(error_type=type(error).__name__,same_object=True))
        assert len(state.saved["preservation"]) == state.fake_controls == 5
        assert state.saved["calls"] == state.saved["fixture_queries"] == []
        assert (state.input_rows,state.locator_rows,state.sql_rows) == (0,0,0)
