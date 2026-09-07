"""Real file-side bootstrap on synthetic facts inside the approved OS boundary."""

from stock_suspend_confirmed_test_support import FACTS_SQL, require_isolated_context

require_isolated_context()

import inspect
import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import dagster as dg
import duckdb
import pytest
import yaml
from dagster_shared.record import copy as copy_record
from sqlalchemy.engine import Engine
from stock_suspend_confirmed_test_support import (
    make_confirmed_test_instance,
    verify_confirmed_test_instance,
)

from orchestrator.defs import stock_suspend_confirmed_contract as contract
from orchestrator.defs.bootstrap import stock_suspend_confirmed as publication
from orchestrator.defs.bootstrap import stock_suspend_confirmed_cli as cli
from orchestrator.defs.bootstrap import stock_suspend_confirmed_events as events
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import (
    suspend_d_normalized_relation_select,
    suspend_d_normalized_select,
)
from orchestrator.defs.paths import raw_suspend_d_path, silver_stock_suspend_daily_path
from orchestrator.defs.sensors.readiness import stock_suspend_confirmed_readiness

DAYS = ("2020-01-02", "2026-01-15", "2026-01-16")


class Interrupted(BaseException):
    """Simulate process exit without exception recovery."""


def _copy_rows(connection, path, rows, *, silver=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = "ts_code, trade_date, suspend_timing, suspend_type"
    if rows:
        def literal(value):
            return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"
        values = ",".join("(" + ",".join(literal(v) for v in row) + ")" for row in rows)
        source = f"(VALUES {values}) t({columns})"
    else:
        source = f"(SELECT NULL ts_code, NULL trade_date, NULL suspend_timing, NULL suspend_type WHERE false) t({columns})"
    query = ("SELECT ts_code::VARCHAR ts_code, trade_date::" + ("DATE" if silver else "VARCHAR") +
             " trade_date, suspend_timing::VARCHAR suspend_timing, suspend_type::VARCHAR suspend_type FROM " + source)
    connection.execute(f"COPY ({query}) TO ? (FORMAT PARQUET)", [str(path)])


def _evidence(path):
    return {**asdict(contract.suspend_file_identity(path)), "sha256": contract.suspend_file_sha256(path)}


def _freeze(scope):
    paths = scope["paths"]
    calendar = "stock_suspend_confirmed_calendar|v1\n" + "".join(f"SSE\t{day}\n" for day in DAYS)
    payload = {
        "schema_version": 1, "operation_id": paths.operation_id, "code_revision": "a" * 40,
        "source": {"csv_revision": "b" * 40, "csv_blob": "c" * 40, "csv_sha256": "d" * 64,
                   "expansion_calendar_sha256": "e" * 64},
        "calendar_dates": list(DAYS), "calendar_sha256": sha256(calendar.encode()).hexdigest(),
        "confirmed": {"version": contract.STOCK_SUSPEND_CONFIRMED_VERSION,
                      "logical_sha256": contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256,
                      "counts": list(contract.STOCK_SUSPEND_CONFIRMED_COUNTS),
                      "override_keys": [list(key) for key in contract.STOCK_SUSPEND_CONFIRMED_OVERRIDE_KEYS],
                      "candidate": _evidence(paths.candidate)},
        "partitions": [{"trade_date": day, "raw": _evidence(raw_suspend_d_path(paths.lake_root, day)),
                        "silver": _evidence(silver_stock_suspend_daily_path(paths.lake_root, day))} for day in DAYS],
        "target_path": str(paths.target),
        "instance": {"home_path": str(paths.operation_dir / "unused-instance"),
                     "storage_identity": {"event": "synthetic-event", "run": "synthetic-run", "schedule": "synthetic-schedule"}},
    }
    paths.plan.write_text(json.dumps(payload))
    scope["plan"] = publication.read_confirmed_plan(paths=paths, expected_plan_sha256=contract.suspend_file_sha256(paths.plan))
    return payload


@pytest.fixture
def prepared(tmp_path, approved_sample):
    directory = tmp_path / "duckdb"
    directory.mkdir()
    settings = DuckDBConnectionSettings(temp_directory=directory, memory_limit="512MB", threads=2, max_temp_directory_size="0B")
    with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as connection:
        paths = publication.PublicationPaths(tmp_path / "lake", tmp_path / "staging", "manual-001")
        paths.candidate.parent.mkdir(parents=True)
        connection.execute(f"COPY ({FACTS_SQL}) TO ? (FORMAT PARQUET)", [str(paths.candidate)])
        raw_rows = ([], [("000002.SZ", "20260115", None, "R")],
                    [("688005.SH", "20260116", None, "R"), ("688005.SH", "20260116", "09:30-10:00", "S")])
        silver_rows = ([("000001.SZ", "2020-01-02", None, "S")],
                       [("000002.SZ", "2026-01-15", None, "R")], [("688005.SH", "2026-01-16", None, "S")])
        for day, raw, silver in zip(DAYS, raw_rows, silver_rows, strict=True):
            _copy_rows(connection, raw_suspend_d_path(paths.lake_root, day), raw)
            _copy_rows(connection, silver_stock_suspend_daily_path(paths.lake_root, day), silver, silver=True)
        scope = {"paths": paths, "connection": connection, "settings": settings}
        _freeze(scope)
        yield scope


def _save_comparison(scope):
    comparison = publication.compare_confirmed_migration(scope["connection"], plan=scope["plan"])
    return publication.save_confirmed_comparison(plan=scope["plan"], comparison=comparison)


def _snapshot(paths):
    return {str(path): (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
            for root in (paths.lake_root, paths.staging_root) for path in root.rglob("*") if path.is_file()}


def _invoke(scope, args):
    return cli.main(args, lake_root=scope["paths"].lake_root, staging_root=scope["paths"].staging_root,
                    connection_settings=scope["settings"])


def _args(scope, command, comparison=None):
    args = [command, "--operation-id", scope["paths"].operation_id]
    if command != "inspect":
        args += ["--expected-plan-sha256", scope["plan"].sha256]
    if comparison is not None:
        args += ["--expected-comparison-sha256", comparison.report_sha256]
    return args


@pytest.fixture
def event_ready(prepared, tmp_path, monkeypatch):
    scope = prepared
    instance_root = tmp_path / "event-instance"
    with make_confirmed_test_instance(instance_root=instance_root) as instance:
        observed = verify_confirmed_test_instance(instance, expected_root=instance_root)
        payload = json.loads(scope["paths"].plan.read_text())
        payload["instance"] = {"home_path": str(instance_root), "storage_identity": observed}
        scope["paths"].plan.write_text(json.dumps(payload))
        scope["plan"] = publication.read_confirmed_plan(paths=scope["paths"])
        scope["paths"].target.parent.mkdir(parents=True)
        os.replace(scope["paths"].candidate, scope["paths"].target)

        def verify(checked, *, plan):
            assert checked is instance and plan.instance_home == str(instance_root)
            assert verify_confirmed_test_instance(checked, expected_root=instance_root) == dict(plan.storage_identity)

        @contextmanager
        def open_instance(*, plan):
            verify(instance, plan=plan)
            yield instance

        # Only backend identity is substituted here. B07 separately tests the
        # native PG constructor; all event APIs/records are real local storage.
        monkeypatch.setattr(events, "verify_confirmed_instance", verify)
        monkeypatch.setattr(events, "open_confirmed_event_instance", open_instance)
        scope["instance"] = instance
        yield scope


def _audit(scope):
    return events.audit_confirmed_events(scope["instance"], scope["connection"], plan=scope["plan"])


def _register(scope):
    return events.register_confirmed_events(scope["instance"], scope["connection"], plan=scope["plan"], audit=_audit(scope))


def _event_counts(scope):
    instance = scope["instance"]
    asset = dg.AssetKey(contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY)
    return (len(instance.fetch_materializations(asset, limit=10).records), *(
        len(instance.event_log_storage.get_asset_check_execution_history(dg.AssetCheckKey(asset, name), limit=10))
        for name in contract.STOCK_SUSPEND_CONFIRMED_CHECKS))


@pytest.mark.parametrize("prefix", [0, 1, 2, 3])
def test_event_roundtrip_and_existing_prefix(event_ready, prefix):
    scope = event_ready
    for index in range(prefix):
        current = _audit(scope)
        scope["instance"].report_runless_asset_event(events._build_event(events._kinds()[index], scope["plan"], current.records[0]))
    before = scope["paths"].target.read_bytes(), contract.suspend_file_identity(scope["paths"].target)
    result = _register(scope)
    assert result.written_events == 3 - prefix and result.events_complete
    assert _event_counts(scope) == (1, 1, 1)
    current = _audit(scope)
    assert current.complete and all(current.records)
    mat = current.records[0]
    for kind in contract.STOCK_SUSPEND_CONFIRMED_CHECKS:
        key = dg.AssetCheckKey(dg.AssetKey(contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY), kind)
        record = scope["instance"].event_log_storage.get_asset_check_execution_history(key, limit=1)[0]
        evaluation = record.event.dagster_event.event_specific_data
        assert record.partition is evaluation.partition is None
        assert evaluation.blocking and evaluation.passed and evaluation.severity == dg.AssetCheckSeverity.ERROR
        assert (evaluation.target_materialization_data.storage_id, evaluation.target_materialization_data.run_id,
                evaluation.target_materialization_data.timestamp) == (mat.record_id, mat.run_id, mat.timestamp)
        assert record.run_id == record.event.run_id == mat.run_id
    assert _register(scope).written_events == 0 and _event_counts(scope) == (1, 1, 1)
    assert stock_suspend_confirmed_readiness(instance=scope["instance"], connection=scope["connection"],
                                            lake_root=scope["paths"].lake_root).ready
    assert before == (scope["paths"].target.read_bytes(), contract.suspend_file_identity(scope["paths"].target))
    assert scope["instance"].get_runs_count() == 0


def test_event_reuses_daily_checks_without_token(event_ready):
    scope = event_ready
    _register(scope)
    current = _audit(scope)
    for kind in contract.STOCK_SUSPEND_CONFIRMED_CHECKS:
        event = events._build_event(kind, scope["plan"], current.records[0])
        event = event.with_metadata({key: value for key, value in event.metadata.items()
                                       if key != events.keys.CONFIRMED_FACT_EVENT_TOKEN_METADATA_KEY})
        scope["instance"].report_runless_asset_event(event)
    assert _register(scope).written_events == 0
    assert _event_counts(scope) == (1, 2, 2)


@pytest.mark.parametrize("point", ["before_api", "after_api_exit", "after_api_timeout", "readback", "confirmed_checkpoint", "pending_checkpoint"])
def test_event_uncertainty_and_recovery(event_ready, monkeypatch, point):
    scope = event_ready
    real_report = scope["instance"].report_runless_asset_event
    real_save = events._save_entry
    real_records = events._read_event_records
    calls = []

    def report(event):
        calls.append(event)
        if point == "before_api":
            raise TimeoutError("not committed")
        real_report(event)
        if point == "after_api_exit":
            raise Interrupted()
        if point == "after_api_timeout":
            raise TimeoutError("committed")

    def read_records(*args):
        if point == "readback" and calls:
            raise OSError("read unavailable")
        return real_records(*args)

    def save(plan, checkpoint, kind, state, record=None):
        if (point == "pending_checkpoint" and state == "pending") or (point == "confirmed_checkpoint" and state == "confirmed"):
            raise OSError("checkpoint unavailable")
        return real_save(plan, checkpoint, kind, state, record)

    with monkeypatch.context() as faults:
        faults.setattr(scope["instance"], "report_runless_asset_event", report)
        faults.setattr(events, "_read_event_records", read_records)
        faults.setattr(events, "_save_entry", save)
        expected = Interrupted if point == "after_api_exit" else (OSError if point == "pending_checkpoint" else contract.ConfirmedFactsError)
        with pytest.raises(expected):
            _register(scope)
    assert len(calls) == (0 if point == "pending_checkpoint" else 1)
    assert scope["paths"].target.exists()
    if point == "before_api":
        assert _audit(scope).uncertain == ("materialization",)
        with patch.object(scope["instance"], "report_runless_asset_event", side_effect=AssertionError("must not retry")), pytest.raises(contract.ConfirmedFactsError, match="event_result_uncertain"):
            _register(scope)
        assert _event_counts(scope) == (0, 0, 0)
    else:
        result = _register(scope)
        assert result.written_events == (3 if point == "pending_checkpoint" else 2)
        assert _event_counts(scope) == (1, 1, 1)


@pytest.mark.parametrize("case", ["version", "uri", "duplicate_mat", "failed", "target", "partition", "duplicate_token", "window", "checkpoint_identity", "stale_audit", "file_changed"])
def test_event_conflicts_never_write(event_ready, monkeypatch, case):
    scope = event_ready
    _register(scope)
    instance = scope["instance"]
    current = _audit(scope)
    if case in ("version", "uri", "duplicate_mat"):
        event = events._build_event("materialization", scope["plan"], None)
        metadata = dict(event.metadata)
        if case != "duplicate_mat":
            key = events.keys.CONFIRMED_FACT_VERSION_METADATA_KEY if case == "version" else "dagster/uri"
            metadata[key] = dg.MetadataValue.text("wrong")
        instance.report_runless_asset_event(event.with_metadata(metadata))
    elif case in ("failed", "target", "partition", "duplicate_token", "window"):
        event = events._build_event(contract.STOCK_SUSPEND_CONFIRMED_CHECKS[0], scope["plan"], current.records[0])
        if case == "failed":
            event = copy_record(event, passed=False)
        elif case == "target":
            event = copy_record(event, target_materialization_data=copy_record(event.target_materialization_data, storage_id=99999))
        elif case == "partition":
            event = copy_record(event, partition="2020-01-02")
        elif case == "window":
            event = event.with_metadata({key: value for key, value in event.metadata.items()
                                           if key != events.keys.CONFIRMED_FACT_EVENT_TOKEN_METADATA_KEY})
        for _ in range(10 if case == "window" else 1):
            instance.report_runless_asset_event(event)
    elif case == "checkpoint_identity":
        path = scope["paths"].events_checkpoint
        payload = json.loads(path.read_text())
        payload["plan_sha256"] = "0" * 64
        path.write_text(json.dumps(payload))
    elif case == "stale_audit":
        current = events.EventAudit("0" * 64, current.file_evidence, current.records, (), ())
    elif case == "file_changed":
        scope["paths"].target.write_bytes(b"invalid")
    target_before = scope["paths"].target.read_bytes()
    with patch.object(instance, "report_runless_asset_event", side_effect=AssertionError("must not write")), pytest.raises((contract.ConfirmedFactsError, duckdb.Error)):
        events.register_confirmed_events(instance, scope["connection"], plan=scope["plan"], audit=current)
    assert target_before == scope["paths"].target.read_bytes()


@pytest.mark.parametrize("case", ["second_exit", "second_timeout", "last_exit", "checkpoint_lost", "pending_check_absent", "wrong_mat_rowcount", "wrong_mat_source", "missing_mat_token"])
def test_event_additional_resume_boundaries(event_ready, monkeypatch, case):
    scope = event_ready
    instance = scope["instance"]
    if case in ("wrong_mat_rowcount", "wrong_mat_source", "missing_mat_token"):
        mat = events._build_event("materialization", scope["plan"], None)
        values = dict(mat.metadata)
        if case == "wrong_mat_rowcount":
            values["dagster/row_count"] = dg.MetadataValue.int(999)
        elif case == "wrong_mat_source":
            values[events.keys.CONFIRMED_FACT_SOURCE_SHA256_METADATA_KEY] = dg.MetadataValue.text("0" * 64)
        else:
            values.pop(events.keys.CONFIRMED_FACT_EVENT_TOKEN_METADATA_KEY)
        instance.report_runless_asset_event(mat.with_metadata(values))
        with patch.object(instance, "report_runless_asset_event", side_effect=AssertionError("invalid mat must block")), pytest.raises(contract.ConfirmedFactsError):
            _register(scope)
        return
    if case == "checkpoint_lost":
        _register(scope)
        scope["paths"].events_checkpoint.rename(scope["paths"].events_checkpoint.with_suffix(".evidence"))
        assert _register(scope).written_events == 0 and _event_counts(scope) == (1, 1, 1)
        assert not scope["paths"].events_checkpoint.exists()
        return
    real_report = instance.report_runless_asset_event
    count = 0

    def interrupted(event):
        nonlocal count
        count += 1
        if count == 2 and case == "pending_check_absent":
            raise TimeoutError()
        real_report(event)
        if count == (3 if case == "last_exit" else 2):
            if case == "second_timeout":
                raise TimeoutError()
            raise Interrupted()

    with monkeypatch.context() as faults:
        faults.setattr(instance, "report_runless_asset_event", interrupted)
        with pytest.raises(contract.ConfirmedFactsError if case in ("second_timeout", "pending_check_absent") else Interrupted):
            _register(scope)
    if case == "pending_check_absent":
        with patch.object(instance, "report_runless_asset_event", side_effect=AssertionError("uncertain must block remaining check")), pytest.raises(contract.ConfirmedFactsError, match="event_result_uncertain"):
            _register(scope)
        assert _event_counts(scope) == (1, 0, 0)
    else:
        assert _register(scope).written_events == (0 if case == "last_exit" else 1)
        assert _event_counts(scope) == (1, 1, 1)


@pytest.mark.parametrize("command", ["audit-events", "register-events"])
def test_event_cli_readonly_and_apply(event_ready, monkeypatch, command):
    scope = event_ready
    args = [command, "--operation-id", scope["paths"].operation_id]
    if command == "register-events":
        args += ["--expected-plan-sha256", scope["plan"].sha256]
    before = _snapshot(scope["paths"])
    with patch.object(Path, "mkdir", side_effect=AssertionError("readonly mkdir")), patch.object(os, "replace", side_effect=AssertionError("readonly replace")), patch.object(scope["instance"], "report_runless_asset_event", side_effect=AssertionError("readonly event")):
        assert _invoke(scope, args) == 0
    assert _snapshot(scope["paths"]) == before and _event_counts(scope) == (0, 0, 0)
    if command == "register-events":
        assert _invoke(scope, args + ["--confirm-event-publish"]) == 0
        assert _event_counts(scope) == (1, 1, 1)


@pytest.mark.parametrize("case", ["ok", "home", "missing", "remote", "options", "identity", "custom", "storage", "artifact", "constructor_write"])
def test_event_native_instance_construction(prepared, tmp_path, monkeypatch, case):
    scope = prepared
    home, artifact = tmp_path / "existing-home", tmp_path / "existing-artifact"
    home.mkdir()
    artifact.mkdir()
    url = "postgresql://synthetic:never-used@localhost:5432/synthetic_dagster"
    config = {"storage": {"postgres": {"postgres_url": url}},
              "local_artifact_storage": {"module": "dagster.core.storage.root", "class": "LocalArtifactStorage", "config": {"base_dir": str(artifact)}}}
    if case in ("remote", "options"):
        config["storage"]["postgres"]["postgres_url"] = url.replace("localhost", "example.invalid") if case == "remote" else url + "?host=elsewhere"
    elif case == "custom":
        config["instance_class"] = {"module": "must_not_import", "class": "Instance"}
    elif case == "storage":
        config["storage"] = {"sqlite": {"base_dir": str(tmp_path / "forbidden")}}
    elif case == "artifact":
        config["local_artifact_storage"]["class"] = "UnexpectedStorage"
    (home / "dagster.yaml").write_text(yaml.safe_dump(config))
    payload = json.loads(scope["paths"].plan.read_text())
    identity = events._storage_identity(url)
    assert identity == "postgresql://synthetic@localhost:5432/synthetic_dagster"
    payload["instance"] = {"home_path": str(home), "storage_identity": dict.fromkeys(("event", "run", "schedule"), identity)}
    if case == "identity":
        payload["instance"]["storage_identity"]["event"] = "wrong"
    scope["paths"].plan.write_text(json.dumps(payload))
    scope["plan"] = publication.read_confirmed_plan(paths=scope["paths"])
    monkeypatch.setattr(events, "_INSTANCE_HOME", tmp_path / "wrong-home" if case == "home" else home)
    if case == "missing":
        (home / "dagster.yaml").rename(home / "not-config")
    if case == "constructor_write":
        monkeypatch.setattr(events.PostgresRunStorage, "__init__", lambda *a, **k: (tmp_path / "forbidden").mkdir())
    before = {str(p): (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    with patch.object(Engine, "connect", side_effect=AssertionError("constructor DB/DDL")), patch.object(Path, "mkdir", side_effect=AssertionError("constructor mkdir")):
        if case == "ok":
            with events.open_confirmed_event_instance(plan=scope["plan"]) as instance:
                events.verify_confirmed_instance(instance, plan=scope["plan"])
                assert instance._compute_log_manager is instance._run_launcher is instance._run_coordinator is None
                assert instance._scheduler is instance._secrets_loader is instance._defs_state_storage is None
        else:
            with pytest.raises((contract.ConfirmedFactsError, FileNotFoundError, AssertionError)), events.open_confirmed_event_instance(plan=scope["plan"]):
                pytest.fail("invalid instance accepted")
    after = {str(p): (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


def test_complete_comparison_is_readonly_and_uses_shared_normalization(prepared):
    paths, plan, connection = prepared["paths"], prepared["plan"], prepared["connection"]
    before = _snapshot(paths)
    comparison = publication.compare_confirmed_migration(connection, plan=plan)
    assert comparison.passed
    assert [(b.year, b.dates, b.raw_rows, b.silver_rows, b.output_rows) for b in comparison.batches] == [
        ("2020", (DAYS[0],), 0, 1, 1), ("2026", DAYS[1:], 3, 2, 2)]
    assert _snapshot(paths) == before
    path = raw_suspend_d_path(paths.lake_root, DAYS[-1])
    connection.execute("CREATE TEMP TABLE normalization_input AS SELECT * FROM read_parquet(?, hive_partitioning=false)", [str(path)])
    assert connection.execute(suspend_d_normalized_select(path)).fetchall() == connection.execute(
        suspend_d_normalized_relation_select("normalization_input")).fetchall()


def test_year_batch_boundary_is_bounded():
    from types import SimpleNamespace
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(368)]
    plan = SimpleNamespace(partitions=tuple(SimpleNamespace(trade_date=day.isoformat()) for day in days))
    assert [(year, len(parts)) for year, parts in publication._batch_partitions(plan)] == [("2024", 366), ("2025", 2)]
    plan.partitions = plan.partitions[:366] + (plan.partitions[0],)
    with pytest.raises(contract.ConfirmedFactsError, match="batch_date_limit"):
        tuple(publication._batch_partitions(plan))


def test_comparison_counts_all_differences_but_limits_samples(prepared):
    paths, connection = prepared["paths"], prepared["connection"]
    rows = [(f"{i:06d}.SZ", DAYS[1], None, "R") for i in range(30)]
    _copy_rows(connection, silver_stock_suspend_daily_path(paths.lake_root, DAYS[1]), rows, silver=True)
    _freeze(prepared)
    comparison = _save_comparison(prepared)
    assert not comparison.passed
    assert sum(b.missing_rows for b in comparison.batches) == 29
    assert sum(len(b.samples) for b in comparison.batches) == 20


@pytest.mark.parametrize("case", ("missing_pair", "duplicate_date", "wrong_path", "wrong_target", "wrong_hash",
                                 "unknown_key", "bool_version", "calendar_hash", "non_calendar", "duplicate_key"))
def test_plan_rejections(prepared, case):
    paths = prepared["paths"]
    value = json.loads(paths.plan.read_text())
    if case == "missing_pair": del value["partitions"][0]["silver"]
    elif case == "duplicate_date": value["partitions"].append(value["partitions"][0])
    elif case == "wrong_path": value["partitions"][0]["raw"]["path"] = str(paths.target)
    elif case == "wrong_target": value["target_path"] = str(paths.candidate)
    elif case == "unknown_key": value["force"] = True
    elif case == "bool_version": value["schema_version"] = True
    elif case == "calendar_hash": value["calendar_sha256"] = "0" * 64
    elif case == "non_calendar":
        value["calendar_dates"] = list(DAYS[1:])
        value["calendar_sha256"] = sha256(("stock_suspend_confirmed_calendar|v1\n" +
            "".join(f"SSE\t{day}\n" for day in DAYS[1:])).encode()).hexdigest()
    encoded = json.dumps(value)
    if case == "duplicate_key": encoded = encoded[:-1] + ', "schema_version": 1}'
    paths.plan.write_text(encoded)
    before = _snapshot(paths)
    with pytest.raises(contract.ConfirmedFactsError):
        publication.read_confirmed_plan(paths=paths, expected_plan_sha256="0" * 64 if case == "wrong_hash" else None)
    assert _snapshot(paths) == before


@pytest.mark.parametrize("case", ("changed_value", "duplicate", "raw_conflict", "raw_wrong_date", "silver_wrong_date", "silver_type"))
def test_comparison_detects_content_and_partition_errors(prepared, case):
    connection, paths = prepared["connection"], prepared["paths"]
    day = DAYS[1]
    raw, silver = raw_suspend_d_path(paths.lake_root, day), silver_stock_suspend_daily_path(paths.lake_root, day)
    if case == "changed_value": _copy_rows(connection, silver, [("000009.SZ", day, None, "R")], silver=True)
    elif case == "duplicate": _copy_rows(connection, silver, [("000002.SZ", day, None, "R")] * 2, silver=True)
    elif case == "raw_conflict": _copy_rows(connection, raw_suspend_d_path(paths.lake_root, DAYS[0]), [("000001.SZ", "20200102", None, "R")])
    elif case == "raw_wrong_date": _copy_rows(connection, raw, [("000002.SZ", "20260116", None, "R")])
    elif case == "silver_wrong_date": _copy_rows(connection, silver, [("000002.SZ", DAYS[-1], None, "R")], silver=True)
    elif case == "silver_type": _copy_rows(connection, silver, [("000002.SZ", day, None, "R")], silver=False)
    _freeze(prepared)
    before = _snapshot(paths)
    if case in ("changed_value", "duplicate"):
        comparison = _save_comparison(prepared)
        assert not comparison.passed
        assert sum(b.added_rows for b in comparison.batches) == (1 if case == "changed_value" else 0)
        assert sum(b.missing_rows for b in comparison.batches) == 1
        with pytest.raises(contract.ConfirmedFactsError, match="comparison_not_passed"):
            publication.publish_confirmed_file(connection, plan=prepared["plan"], comparison=comparison)
    else:
        with pytest.raises(contract.ConfirmedFactsError, match={
            "raw_conflict": "raw_confirmed_conflict", "raw_wrong_date": "input_partition_date_mismatch",
            "silver_wrong_date": "input_partition_date_mismatch", "silver_type": "input_schema_mismatch"}[case]):
            publication.compare_confirmed_migration(connection, plan=prepared["plan"])
        assert _snapshot(paths) == before
    assert not paths.target.exists()


@pytest.mark.parametrize("case", ("before_batch", "after_batch", "before_publish", "after_prepared"))
def test_input_drift_refused(prepared, case):
    paths, connection, plan = prepared["paths"], prepared["connection"], prepared["plan"]
    victim = raw_suspend_d_path(paths.lake_root, DAYS[1])
    if case in ("before_publish", "after_prepared"): comparison = _save_comparison(prepared)
    def mutate(): victim.write_bytes(victim.read_bytes() + b"drift")
    if case in ("before_batch", "before_publish"): mutate()
    if case == "after_batch":
        original = publication._load_comparison_batch
        def load(*args):
            original(*args)
            mutate()
        manager = patch.object(publication, "_load_comparison_batch", side_effect=load)
    elif case == "after_prepared":
        original = publication._save_json
        def save(paths, path, payload):
            original(paths, path, payload)
            if payload.get("stage") == "prepared": mutate()
        manager = patch.object(publication, "_save_json", side_effect=save)
    else:
        from contextlib import nullcontext
        manager = nullcontext()
    with manager, pytest.raises(contract.ConfirmedFactsError, match="input_drift"):
        if case in ("before_publish", "after_prepared"):
            publication.publish_confirmed_file(connection, plan=plan, comparison=comparison)
        else:
            publication.compare_confirmed_migration(connection, plan=plan)
    assert not paths.target.exists()
    assert paths.candidate.exists()


@pytest.mark.parametrize("case", ("partial", "duplicate", "wrong_year", "old_plan", "bad_count"))
def test_report_scope_rejected(prepared, case):
    comparison = _save_comparison(prepared)
    payload = json.loads(prepared["paths"].comparison.read_text())
    if case == "partial": payload["batches"].pop()
    elif case == "duplicate": payload["batches"].append(payload["batches"][0])
    elif case == "wrong_year": payload["batches"][0]["year"] = "2019"
    elif case == "old_plan": payload["plan_sha256"] = "0" * 64
    elif case == "bad_count": payload["batches"][0]["output_rows"] += 1
    prepared["paths"].comparison.write_text(json.dumps(payload))
    with pytest.raises(contract.ConfirmedFactsError):
        publication.read_confirmed_comparison(plan=prepared["plan"])
    with pytest.raises(contract.ConfirmedFactsError, match="document_hash_mismatch"):
        publication.publish_confirmed_file(prepared["connection"], plan=prepared["plan"], comparison=comparison)


def test_report_is_immutable_and_not_implicitly_created(prepared):
    comparison = publication.compare_confirmed_migration(prepared["connection"], plan=prepared["plan"])
    assert not prepared["paths"].comparison.exists()
    with pytest.raises(contract.ConfirmedFactsError, match="comparison_not_saved"):
        publication.publish_confirmed_file(prepared["connection"], plan=prepared["plan"], comparison=comparison)
    saved = publication.save_confirmed_comparison(plan=prepared["plan"], comparison=comparison)
    before = _snapshot(prepared["paths"])
    assert publication.save_confirmed_comparison(plan=prepared["plan"], comparison=comparison) == saved
    assert _snapshot(prepared["paths"]) == before
    payload = json.loads(prepared["paths"].comparison.read_text())
    payload["batches"][0]["elapsed_ms"] += 1
    prepared["paths"].comparison.write_text(json.dumps(payload))
    with pytest.raises(contract.ConfirmedFactsError, match="comparison_already_exists"):
        publication.save_confirmed_comparison(plan=prepared["plan"], comparison=comparison)


@pytest.mark.parametrize("case", ("absent", "equal", "different", "broken", "wrong_schema"))
def test_file_publication_states(prepared, case):
    paths, connection, plan = prepared["paths"], prepared["connection"], prepared["plan"]
    comparison = _save_comparison(prepared)
    if case != "absent": paths.target.parent.mkdir(parents=True)
    if case == "equal":
        connection.execute(f"COPY ({FACTS_SQL} ORDER BY ts_code DESC) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(paths.target)])
        assert paths.target.read_bytes() != paths.candidate.read_bytes()
    elif case == "different":
        connection.execute(f"COPY (SELECT * REPLACE ('000009.SZ' AS ts_code) FROM ({FACTS_SQL})) TO ? (FORMAT PARQUET)", [str(paths.target)])
    elif case == "broken": paths.target.write_bytes(b"broken parquet")
    elif case == "wrong_schema": _copy_rows(connection, paths.target, [], silver=True)
    before_target = _evidence(paths.target) if paths.target.exists() else None
    with patch.object(publication.os, "replace", wraps=os.replace) as replace:
        if case in ("absent", "equal"):
            result = publication.publish_confirmed_file(connection, plan=plan, comparison=comparison)
            assert result.status == ("published" if case == "absent" else "reused")
            assert result.file_committed and not result.events_complete
            assert json.loads(paths.checkpoint.read_text())["stage"] == "committed"
        else:
            with pytest.raises((contract.ConfirmedFactsError, duckdb.Error)):
                publication.publish_confirmed_file(connection, plan=plan, comparison=comparison)
        promotions = [call for call in replace.call_args_list if call.args[1] == paths.target]
    assert len(promotions) == (1 if case == "absent" else 0)
    if before_target: assert _evidence(paths.target) == before_target


@pytest.mark.parametrize("case", ("after_replace", "after_replace_error", "after_checkpoint", "replace_error", "checkpoint_error", "readback_error"))
def test_publication_resume(prepared, case):
    paths, connection, plan = prepared["paths"], prepared["connection"], prepared["plan"]
    comparison = _save_comparison(prepared)
    native_replace, save, inspect_file = os.replace, publication._save_json, publication._inspect_file
    def replace(source, target):
        if target == paths.target and case == "replace_error": raise OSError("replace failed")
        native_replace(source, target)
        if target == paths.target and case == "after_replace": raise Interrupted()
        if target == paths.target and case == "after_replace_error": raise OSError("error after actual move")
    def save_json(paths, path, payload):
        if payload.get("stage") == "prepared" and case == "checkpoint_error": raise OSError("checkpoint failed")
        save(paths, path, payload)
        if payload.get("stage") == "prepared" and case == "after_checkpoint": raise Interrupted()
    def readback(connection, path):
        if path == paths.target and path.exists() and case == "readback_error": raise OSError("readback failed")
        return inspect_file(connection, path)
    with (patch.object(publication.os, "replace", side_effect=replace),
          patch.object(publication, "_save_json", side_effect=save_json),
          patch.object(publication, "_inspect_file", side_effect=readback),
          pytest.raises((Interrupted, OSError, contract.ConfirmedFactsError)) as caught):
        publication.publish_confirmed_file(connection, plan=plan, comparison=comparison)
    already_published = case in ("after_replace", "after_replace_error", "readback_error")
    assert paths.target.exists() is already_published
    if case in ("after_replace_error", "readback_error"): assert caught.value.exit_code == 5
    with patch.object(publication.os, "replace", wraps=os.replace) as replace:
        result = publication.publish_confirmed_file(connection, plan=plan, comparison=comparison)
        assert result.status == ("reused" if already_published else "published")
        assert sum(call.args[1] == paths.target for call in replace.call_args_list) == int(not already_published)


def test_missing_candidate_and_checkpoint_recognizes_correct_target(prepared):
    paths, connection, plan = prepared["paths"], prepared["connection"], prepared["plan"]
    comparison = _save_comparison(prepared)
    paths.target.parent.mkdir(parents=True)
    os.replace(paths.candidate, paths.target)
    before = _evidence(paths.target)
    assert not paths.checkpoint.exists()
    with patch.object(publication.os, "replace", wraps=os.replace) as replace:
        assert publication.publish_confirmed_file(connection, plan=plan, comparison=comparison).status == "reused"
        assert all(call.args[1] != paths.target for call in replace.call_args_list)
    assert _evidence(paths.target) == before


@pytest.mark.parametrize("case", ("candidate_missing", "candidate_link", "target_link", "bad_checkpoint", "bool_checkpoint", "oversized_target", "cross_device"))
def test_unsafe_publication_refused(prepared, case, monkeypatch):
    paths, connection, plan = prepared["paths"], prepared["connection"], prepared["plan"]
    comparison = _save_comparison(prepared)
    if case == "candidate_missing": paths.candidate.rename(paths.candidate.with_suffix(".absent"))
    elif case == "candidate_link":
        moved = paths.candidate.with_suffix(".moved")
        paths.candidate.rename(moved)
        paths.candidate.symlink_to(moved)
    elif case == "target_link":
        paths.target.parent.mkdir(parents=True)
        paths.target.symlink_to(paths.candidate)
    elif case == "bad_checkpoint": paths.checkpoint.write_text('{"stage":"committed"}')
    elif case == "bool_checkpoint":
        payload = publication._checkpoint_payload(plan, comparison, "prepared")
        payload["schema_version"] = True
        paths.checkpoint.write_text(json.dumps(payload))
    elif case == "oversized_target":
        from dataclasses import replace
        identity = contract.suspend_file_identity
        paths.target.parent.mkdir(parents=True)
        paths.target.write_bytes(b"small negative fixture")
        def oversized(path):
            observed = identity(path)
            return replace(observed, size=100 * 1024 * 1024 + 1) if path == paths.target else observed
        monkeypatch.setattr(contract, "suspend_file_identity", oversized)
    elif case == "cross_device":
        native_stat = Path.stat
        def stat(path, *args, **kwargs):
            result = native_stat(path, *args, **kwargs)
            if path == paths.lake_root:
                from types import SimpleNamespace
                return SimpleNamespace(st_dev=result.st_dev + 1, st_mode=result.st_mode)
            return result
        monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises((contract.ConfirmedFactsError, FileNotFoundError)):
        publication.publish_confirmed_file(connection, plan=plan, comparison=comparison)
    assert paths.candidate.exists() or case == "candidate_missing"


@pytest.mark.parametrize("args", ([], ["--help"], ["compare"], ["inspect", "--operation-id", "../wrong"],
                                  ["inspect", "--operation-id", "valid", "--force"],
                                  ["compare", "--operation-id", "valid", "--expected-plan-sha256", "bad"],
                                  ["publish-file", "--operation-id", "valid"], ["register-events"],
                                  ["inspect", "--operation-i", "valid"]))
def test_cli_help_and_bad_arguments_have_no_io(args):
    with (patch.object(Path, "open", side_effect=AssertionError("file IO")),
          patch.object(Path, "lstat", side_effect=AssertionError("file IO")),
          patch.object(Path, "mkdir", side_effect=AssertionError("mkdir")),
          patch("orchestrator.defs.duckdb_connection.duckdb.connect", side_effect=AssertionError("connect"))):
        assert cli.main(args) == (0 if not args or args == ["--help"] else 2)


@pytest.mark.parametrize("command", ("inspect", "compare", "publish-file"))
def test_cli_readonly_full_chain(prepared, command, capsys):
    comparison = _save_comparison(prepared) if command == "publish-file" else None
    paths = prepared["paths"]
    before = _snapshot(paths)
    with (patch.object(Path, "mkdir", side_effect=AssertionError("mkdir")) as mkdir,
          patch.object(publication.os, "replace", side_effect=AssertionError("replace")) as replace):
        assert _invoke(prepared, _args(prepared, command, comparison)) == 0
        mkdir.assert_not_called()
        replace.assert_not_called()
    output = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert output["mode"] == "readonly" and output["applied"] is False
    assert _snapshot(paths) == before


def test_cli_save_and_confirmed_publish_are_separate(prepared, capsys):
    paths = prepared["paths"]
    assert _invoke(prepared, _args(prepared, "compare") + ["--save-report"]) == 0
    output = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert output["mode"] == "apply" and output["applied"]
    assert paths.comparison.exists() and not paths.checkpoint.exists() and not paths.target.exists()
    comparison = publication.read_confirmed_comparison(plan=prepared["plan"])
    assert _invoke(prepared, _args(prepared, "publish-file", comparison) + ["--confirm-file-publish"]) == 0
    output = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert output["mode"] == "apply" and output["applied"] and output["file_committed"]
    assert not output["events_complete"]
    assert not (paths.operation_dir / "unused-instance").exists()
    assert set(inspect.signature(publication.publish_confirmed_file).parameters) == {"connection", "plan", "comparison"}


def test_cli_wrong_hash_does_not_connect(prepared):
    args = _args(prepared, "compare")
    args[-1] = "0" * 64
    with patch("orchestrator.defs.duckdb_connection.duckdb.connect", side_effect=AssertionError("connect")):
        assert _invoke(prepared, args) == 4
