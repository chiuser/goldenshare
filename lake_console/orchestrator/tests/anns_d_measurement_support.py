"""Temporary acceptance measurements; never imported by production code.

The observer delegates all existing operations. File-size references are a model,
SHA byte counts are application reads, and native DuckDB physical IO is unknown.
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import sys
from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path

import pytest

NORMAL_NODE = "tests/anns_d_measurement_cases.py::test_normal_merge_measurement"
NINE_NODE = (
    "tests/test_anns_d_nine_day_recovery.py::"
    "test_nine_day_fourth_day_failure_and_native_same_root_recovery"
)


class _NoMeasurement:
    @contextmanager
    def attempt(self, label, **metadata):
        yield self

    def result(self, **metadata):
        pass


@pytest.fixture
def anns_measurement(request):
    """Explicit seam; ordinary business tests do not enable observation."""
    return getattr(request.config, "_anns_measurement", _NoMeasurement())


@dataclass
class _Span:
    case: str
    attempt: str
    phase: str
    day: str | None = None
    run_id: str | None = None
    window_id: str | None = None
    counts: Counter = field(default_factory=Counter)
    inputs: dict = field(default_factory=dict)
    outputs: list = field(default_factory=list)
    replacements: list = field(default_factory=list)
    snapshots: list = field(default_factory=list)
    status: str = "completed"

    def document(self):
        return {
            "case": self.case, "attempt": self.attempt, "phase": self.phase,
            "day": self.day, "run_id": self.run_id, "window_id": self.window_id,
            "counts": dict(self.counts), "inputs": self.inputs,
            "input_unique_file_size_model_bytes": sum(
                entry["size_bytes"] for entry in self.inputs.values()
            ),
            "outputs": self.outputs, "replacements": self.replacements,
            "temporary_boundary_snapshots": self.snapshots, "status": self.status,
        }


class AnnouncementMeasurement:
    def __init__(self, temporary_root):
        self.temporary_root = Path(temporary_root).resolve()
        self.case = ""
        self.label = "verification"
        self.attempt_metadata = {}
        self.spans = []
        self.roots = set()
        self.results = []
        self._active = ContextVar("announcement_measurement_span", default=None)
        self._default = {}

    def _owned(self, path):
        return Path(path).resolve(strict=False).is_relative_to(self.temporary_root)

    def _relative(self, path):
        return str(Path(path).resolve(strict=False).relative_to(self.temporary_root))

    def _span(self):
        active = self._active.get()
        if active is not None:
            return active
        key = (self.case, self.label)
        if key not in self._default:
            phase = "verification" if self.label == "verification" else "execution_control"
            span = _Span(
                self.case, self.label, phase,
                run_id=self.attempt_metadata.get("run_id"),
                window_id=self.attempt_metadata.get("window_id"),
            )
            self._default[key] = span
            self.spans.append(span)
        return self._default[key]

    @contextmanager
    def attempt(self, label, **metadata):
        previous = self.label, self.attempt_metadata
        self.label, self.attempt_metadata = label, metadata
        try:
            yield self
        finally:
            self.label, self.attempt_metadata = previous

    def result(self, **metadata):
        self.results.append({"case": self.case, "attempt": self.label, **metadata})

    def snapshot(self):
        counts = Counter()
        for root in (self.temporary_root,):
            if not root.exists():
                continue
            for directory, _, filenames in os.walk(root, followlinks=False):
                for name in filenames:
                    try:
                        info = (Path(directory) / name).lstat()
                    except OSError:
                        continue
                    counts["files"] += 1
                    counts["logical_size_bytes"] += info.st_size
                    counts["allocated_bytes"] += getattr(info, "st_blocks", 0) * 512
        return dict(counts)

    @contextmanager
    def phase(self, name, day, store=None, control=None):
        if store is not None:
            for root in (store.root, store.staging):
                if not self._owned(root):
                    raise AssertionError("measurement attempted to leave its temporary root")
                self.roots.add(Path(root).resolve(strict=False))
        if self._active.get() is not None:
            yield self._active.get()
            return
        view = getattr(control, "view", {})
        span = _Span(
            self.case, self.label, name, day,
            view.get("active_run_id", self.attempt_metadata.get("run_id")),
            view.get("window_id", self.attempt_metadata.get("window_id")),
        )
        control_span = self._default.get((self.case, self.label))
        if control_span is not None and control_span.phase == "execution_control":
            control_span.run_id = span.run_id or control_span.run_id
            control_span.window_id = span.window_id or control_span.window_id
        span.snapshots.append(self.snapshot())
        self.spans.append(span)
        token = self._active.set(span)
        try:
            yield span
        except BaseException as error:
            span.status = type(error).__name__
            raise
        finally:
            span.snapshots.append(self.snapshot())
            self._active.reset(token)

    def input(self, path, role):
        path = Path(path)
        if not self._owned(path):
            raise AssertionError("measurement input outside the temporary root")
        try:
            size = path.stat().st_size
        except OSError:
            return
        span = self._span()
        entry = span.inputs.setdefault(
            self._relative(path), {"size_bytes": size, "binding_references": 0, "roles": []}
        )
        entry["binding_references"] += 1
        if role not in entry["roles"]:
            entry["roles"].append(role)
        span.counts["input_binding_file_size_model_bytes"] += size

    def output(self, path, kind):
        path = Path(path)
        if not self._owned(path):
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        span = self._span()
        span.outputs.append({"path": self._relative(path), "kind": kind, "size_bytes": size})
        span.counts[f"{kind}_outputs"] += 1
        span.counts[f"{kind}_output_size_bytes"] += size

    @contextmanager
    def installed(self):
        import duckdb

        from orchestrator.defs import anns_d_execution as execution
        from orchestrator.defs.anns_d_checkpoint import (
            AnnouncementWindowBudget,
            announcement_file_fingerprint,
        )
        from orchestrator.defs.anns_d_io import AnnouncementStore
        from orchestrator.defs.checks import anns_d_checks as checks

        observer = self
        original_open, original_replace = Path.open, os.replace
        original_connect = duckdb.connect
        fingerprint_code = announcement_file_fingerprint.__code__

        def opened(path, mode="r", *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            if not observer._owned(path):
                return stream
            caller = sys._getframe(1).f_code
            sha = mode == "rb" and caller is fingerprint_code
            writing_json = any(value in mode for value in ("w", "x", "a")) and ".json" in path.name
            return _ObservedFile(stream, path, observer, sha, writing_json, "b" in mode)

        def replaced(source, target, *args, **kwargs):
            result = original_replace(source, target, *args, **kwargs)
            target, source = Path(target), Path(source)
            if observer._owned(target):
                kind = "metadata"
                if target.suffix == ".parquet":
                    kind = "formal_parquet" if any(
                        root in target.resolve(strict=False).parents and root.name == "lake"
                        for root in observer.roots
                    ) else "staging_parquet"
                observer._span().replacements.append({
                    "source": observer._relative(source), "target": observer._relative(target),
                    "kind": kind,
                })
                observer._span().counts[f"{kind}_renames"] += 1
            return result

        def connected(*args, **kwargs):
            observer._span().counts["connections"] += 1
            return _ObservedConnection(original_connect(*args, **kwargs), observer)

        original_capture = execution.capture_announcement_day
        original_build = AnnouncementStore.build_day
        original_promote = AnnouncementStore.promote_day
        original_evaluate = checks.evaluate_announcement_check
        original_claim = AnnouncementWindowBudget.claim

        @wraps(original_capture)
        def capture(day, call, store, checkpoint, control, *args, **kwargs):
            with observer.phase("capture", day, store, control):
                return original_capture(day, call, store, checkpoint, control, *args, **kwargs)

        @wraps(original_build)
        def build(store, day, *args, **kwargs):
            with observer.phase("build", day, store, store.control):
                return original_build(store, day, *args, **kwargs)

        @wraps(original_promote)
        def promote(store, day, *args, **kwargs):
            with observer.phase("promote", day, store, store.control):
                return original_promote(store, day, *args, **kwargs)

        @wraps(original_evaluate)
        def evaluate(context, lake_root, *, day, reconciliation, **kwargs):
            name = "delivery_check" if reconciliation else "file_check"
            with observer.phase(name, day, control=kwargs.get("control")) as span:
                span.run_id = context.run.run_id
                record = kwargs.get("target_record")
                materialization = getattr(record, "asset_materialization", None)
                metadata = getattr(materialization, "metadata", {})
                identity = getattr(metadata.get("goldenshare/announcement_identity"), "value", None)
                if isinstance(identity, Mapping):
                    span.window_id = identity.get("window_id")
                control_span = observer._default.get((observer.case, observer.label))
                if control_span is not None:
                    control_span.run_id = span.run_id
                    control_span.window_id = span.window_id or control_span.window_id
                return original_evaluate(context, lake_root, day=day, reconciliation=reconciliation, **kwargs)

        @wraps(original_claim)
        def claim(budget, control, day):
            result = original_claim(budget, control, day)
            observer._span().counts["requests_claimed"] += 1
            return result

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(Path, "open", opened)
            patch.setattr(os, "replace", replaced)
            patch.setattr(duckdb, "connect", connected)
            patch.setattr(execution, "capture_announcement_day", capture)
            patch.setattr(AnnouncementStore, "build_day", build)
            patch.setattr(AnnouncementStore, "promote_day", promote)
            patch.setattr(checks, "evaluate_announcement_check", evaluate)
            patch.setattr(AnnouncementWindowBudget, "claim", claim)
            yield


class _ObservedFile:
    def __init__(self, stream, path, observer, sha, writing_json, binary):
        self.stream, self.path, self.observer = stream, Path(path), observer
        self.sha, self.writing_json = sha, writing_json
        self.binary = binary

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        self.stream.__enter__()
        if self.sha:
            self.observer._span().counts["sha_file_reads"] += 1
        return self

    def __exit__(self, *args):
        result = self.stream.__exit__(*args)
        if self.writing_json:
            self.observer.output(self.path, "json")
        return result

    def read(self, *args, **kwargs):
        value = self.stream.read(*args, **kwargs)
        if self.sha:
            self.observer._span().counts["sha_read_bytes"] += len(value)
        elif self.binary:
            self.observer._span().counts["other_python_binary_read_bytes"] += len(value)
        else:
            self.observer._span().counts["python_text_read_utf8_bytes"] += len(value.encode("utf-8"))
        return value

    def __iter__(self):
        return iter(self.stream)


class _ObservedRelation:
    def __init__(self, relation, observer):
        self.relation, self.observer = relation, observer

    def __getattr__(self, name):
        return getattr(self.relation, name)

    def create_view(self, *args, **kwargs):
        self.observer._span().counts["relation_create_view_calls"] += 1
        result = self.relation.create_view(*args, **kwargs)
        return self if result is self.relation else result


class _ObservedConnection:
    def __init__(self, connection, observer):
        self.connection, self.observer = connection, observer

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)

    def execute(self, sql, *args, **kwargs):
        span = self.observer._span()
        normalized = sql.strip().upper()
        setup = normalized.startswith("SET ") or "FROM DUCKDB_SETTINGS()" in normalized
        span.counts["execute_calls"] += 1
        span.counts["setup_sql_calls" if setup else "business_sql_calls"] += 1
        parameters = args[0] if args else kwargs.get("parameters", [])
        if normalized.startswith("DESCRIBE") and "READ_PARQUET" in normalized:
            self.observer.input(parameters[0], "describe_parquet")
        result = self.connection.execute(sql, *args, **kwargs)
        if normalized.startswith("COPY "):
            self.observer.output(parameters[0], "parquet_copy")
        return self if result is self.connection else result

    def _read(self, kind, source, *args, **kwargs):
        self.observer._span().counts[f"{kind}_calls"] += 1
        paths = source if isinstance(source, (tuple, list)) else [source]
        for path in paths:
            self.observer.input(path, kind)
        relation = getattr(self.connection, kind)(source, *args, **kwargs)
        return _ObservedRelation(relation, self.observer)

    def read_parquet(self, source, *args, **kwargs):
        return self._read("read_parquet", source, *args, **kwargs)

    def read_json(self, source, *args, **kwargs):
        return self._read("read_json", source, *args, **kwargs)


class _MeasurementPlugin:
    def __init__(self, observer):
        self.observer = observer
        self.outcomes = []

    def pytest_configure(self, config):
        config._anns_measurement = self.observer

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        self.observer.case = item.nodeid
        with self.observer.installed():
            yield

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            self.outcomes.append({"nodeid": report.nodeid, "outcome": report.outcome})


def normalized_peak_rss(raw, platform):
    if platform == "darwin":
        return int(raw)
    if platform.startswith("linux"):
        return int(raw) * 1024
    return None


def run_announcement_measurements(report_path):
    """Called only by the fresh worker; report path is an explicit argument."""
    report_path = Path(report_path)
    temporary_root = report_path.parent / "measurement-data"
    temporary_root.mkdir()
    observer = AnnouncementMeasurement(temporary_root)
    plugin = _MeasurementPlugin(observer)
    try:
        status = pytest.main([
            "-q", "--tb=short", "-p", "no:cacheprovider", "--basetemp",
            str(temporary_root / "pytest"), NORMAL_NODE, NINE_NODE,
        ], plugins=[plugin])
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report = {
            "pytest_exit_code": int(status), "outcomes": plugin.outcomes,
            "worker_peak_rss": {
                "raw": peak, "platform": sys.platform,
                "bytes": normalized_peak_rss(peak, sys.platform),
                "scope": "absolute lifetime peak of this fresh worker, including imports and pytest",
            },
            "spans": [span.document() for span in observer.spans],
            "attempt_results": observer.results,
            "measurement_boundaries": {
                "physical_disk_read_bytes": None, "native_duckdb_scan_count": None,
                "file_size_model_is_physical_io": False,
                "temporary_peak": "maximum observed at stage boundaries; short-lived spill may be missed",
                "temporary_scope": "all files below this worker's dedicated measurement-data directory, including temporary instance files",
                "source": "local callable substitute; SDK IPC and network transfer are not measured",
                "sha_bytes": "actual bytes returned by existing SHA read calls, not disk IO",
                "sql": "Python execute submissions; relation API calls reported separately",
            },
            "temporary_boundary_max_logical_bytes": max(
                (snapshot.get("logical_size_bytes", 0) for span in observer.spans for snapshot in span.snapshots),
                default=0,
            ),
        }
    finally:
        shutil.rmtree(temporary_root)
    report["temporary_data_cleaned"] = not temporary_root.exists()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
