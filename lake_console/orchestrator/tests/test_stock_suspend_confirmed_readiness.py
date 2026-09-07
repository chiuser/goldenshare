"""Bounded physical readiness and unchanged candidate selection; no instance discovery."""

from stock_suspend_confirmed_test_support import (
    make_confirmed_test_resources,
    require_isolated_context,
)

ALLOWED = require_isolated_context()

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import dagster as dg
import pytest
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus as Status,
)

from orchestrator.defs import stock_suspend_confirmed_contract as contract
from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.paths import silver_stock_suspend_confirmed_path
from orchestrator.defs.run_contracts.metadata import (
    CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY as HASH,
)
from orchestrator.defs.run_contracts.metadata import (
    CONFIRMED_FACT_VERSION_METADATA_KEY as VERSION,
)
from orchestrator.defs.sensors import readiness
from orchestrator.defs.sensors import suspend_d_sensor as sensor


def _instance(root, problem="ok"):
    key = dg.AssetKey(contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY)
    metadata = {VERSION: contract.STOCK_SUSPEND_CONFIRMED_VERSION,
                HASH: contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256,
                "dagster/uri": str(silver_stock_suspend_confirmed_path(root))}
    mat_metadata = dict(metadata)
    field = {"mat_version": VERSION, "mat_hash": HASH, "mat_uri": "dagster/uri"}.get(problem)
    if field:
        mat_metadata[field] = "wrong"
    mat = dg.AssetMaterialization(key, metadata=mat_metadata, partition="2020-01-02" if problem == "mat_partition" else None)
    published = SimpleNamespace(asset_materialization=mat, storage_id=7, timestamp=1)

    def record(name, *, broken):
        if problem == "failed_first":
            broken = broken and name == contract.STOCK_SUSPEND_CONFIRMED_CHECKS[0]
        elif problem == "failed_second":
            broken = broken and name == contract.STOCK_SUSPEND_CONFIRMED_CHECKS[1]
        changed = dict(metadata)
        if broken and problem in ("check_version", "check_hash"):
            changed[VERSION if problem == "check_version" else HASH] = "wrong"
        evaluation = SimpleNamespace(
            asset_key=key, check_name=name, passed=not (broken and problem in ("failed", "failed_first", "failed_second", "old_green")),
            blocking=not (broken and problem == "nonblocking"),
            partition="2020-01-02" if broken and problem == "check_partition" else None,
            target_materialization_data=SimpleNamespace(storage_id=6 if broken and problem == "wrong_target" else 7),
            metadata={k: dg.MetadataValue.text(v) for k, v in changed.items()},
        )
        status = Status.PLANNED if broken and problem == "planned" else Status.FAILED if not evaluation.passed else Status.SUCCEEDED
        return SimpleNamespace(status=status, event=None if status == Status.PLANNED else SimpleNamespace(dagster_event=SimpleNamespace(event_specific_data=evaluation)))

    def fetch(filters, **kwargs):
        assert filters.asset_key == key and filters.asset_partitions is None and kwargs == {"limit": 1}
        if problem == "event_error":
            raise RuntimeError("synthetic storage unavailable")
        return SimpleNamespace(records=[] if problem == "no_mat" else [published])

    def history(check_key, **kwargs):
        assert check_key.asset_key == key and kwargs == {"limit": 1}
        if problem == "missing_check":
            return []
        # A preceding good record must never rescue the latest bad/in-progress record.
        return [record(check_key.name, broken=True), record(check_key.name, broken=False)][:kwargs["limit"]]

    return SimpleNamespace(fetch_materializations=Mock(side_effect=fetch),
                           event_log_storage=SimpleNamespace(get_asset_check_execution_history=Mock(side_effect=history)))


@pytest.mark.parametrize("problem", ["missing", "schema", "content", "over"])
def test_physical_gate(problem, fixed_lake, connection, monkeypatch):
    path = silver_stock_suspend_confirmed_path(fixed_lake)
    if problem == "missing":
        path.rename(path.with_suffix(".moved"))
    elif problem == "schema":
        connection.execute("COPY (SELECT 1 wrong) TO ? (FORMAT PARQUET)", [str(path)])
    else:
        connection.execute("CREATE TEMP TABLE changed AS SELECT * FROM read_parquet(?)", [str(path)])
        connection.execute("UPDATE changed SET ts_code='000002.SZ' WHERE ts_code='000001.SZ'" if problem == "content"
                           else "INSERT INTO changed SELECT '000003.SZ', DATE '2020-01-03', NULL, 'S', 'add_missing'")
        connection.execute("COPY changed TO ? (FORMAT PARQUET)", [str(path)])
    instance = _instance(fixed_lake)
    inspect = Mock(wraps=contract.inspect_confirmed_file)
    monkeypatch.setattr(contract, "inspect_confirmed_file", inspect)
    status = readiness.stock_suspend_confirmed_readiness(instance, connection, lake_root=fixed_lake)
    assert not status.ready and inspect.call_count == 1
    assert status.reason_code == {"missing": "physical_read_failed", "schema": "schema_mismatch",
                                  "content": "approved_content_mismatch", "over": "row_count_mismatch"}[problem]
    assert not instance.fetch_materializations.called
    assert not instance.event_log_storage.get_asset_check_execution_history.called


@pytest.mark.parametrize("problem", ["ok", "no_mat", "mat_partition", "mat_version", "mat_hash", "mat_uri", "event_error"])
def test_publication_gate(problem, fixed_lake, connection):
    instance = _instance(fixed_lake, problem)
    status = readiness.stock_suspend_confirmed_readiness(instance, connection, lake_root=fixed_lake)
    assert status.ready == (problem == "ok")
    assert instance.fetch_materializations.call_count == 1
    assert instance.event_log_storage.get_asset_check_execution_history.call_count == (2 if problem == "ok" else 0)
    if status.ready:
        assert status.materialization_storage_id == 7 and status.physical_logical_sha256 == contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256
        assert all(status.check_results.values())  # timestamp=1: no daily freshness constraint.


@pytest.mark.parametrize("problem", ["missing_check", "failed", "failed_first", "failed_second", "planned", "wrong_target", "check_partition", "nonblocking", "check_version", "check_hash", "old_green"])
def test_latest_checks_gate(problem, fixed_lake, connection):
    instance = _instance(fixed_lake, problem)
    status = readiness.stock_suspend_confirmed_readiness(instance, connection, lake_root=fixed_lake)
    assert not status.ready and status.reason_code == "checks_not_ready"
    assert instance.fetch_materializations.call_count == 1
    assert instance.event_log_storage.get_asset_check_execution_history.call_count == 2


@pytest.mark.parametrize("problem", ["no_candidates", "one", "two", "first_raw_blocked", "both_raw_blocked", "fixed_blocked", "gap", "connection_error"])
def test_sensor_bounded_gate(problem, fixed_lake, tmp_path, monkeypatch):
    dates = ("2020-01-02", "2020-01-03", "2020-01-06")
    all_dates = dates
    if problem == "one":
        dates = dates[:1]
    elif problem == "gap":
        dates = (dates[0], dates[2])
    instance = _instance(fixed_lake, "failed" if problem == "fixed_blocked" else "ok")
    instance.get_dynamic_partitions = Mock(return_value=list(dates))
    instance.get_materialized_partitions = Mock(return_value=set(dates) if problem == "no_candidates" else set())
    resources = make_confirmed_test_resources(lake_root=fixed_lake, work_root=ALLOWED)
    context = SimpleNamespace(instance=instance, resources=SimpleNamespace(**resources))
    expected = all_dates if problem == "gap" else dates
    window = ContinuityExpectedDateWindow(expected_trade_dates=expected, min_trade_date="2014-01-01",
        max_trade_date=expected[-1], evaluated_at=datetime(2020, 1, 7, tzinfo=UTC), window_limit=10)
    gap = build_registered_gap_status(expected_trade_dates=expected, registered_trade_dates=dates)
    monkeypatch.setattr(sensor, "_stock_trade_day_registered_gap", lambda *args, **kwargs: (window, gap))
    inspect = Mock(wraps=contract.inspect_confirmed_file)
    monkeypatch.setattr(contract, "inspect_confirmed_file", inspect)
    checked = Mock(wraps=readiness.stock_suspend_confirmed_readiness)
    monkeypatch.setattr(sensor, "stock_suspend_confirmed_readiness", checked)

    def raw_ready(_instance, day):
        return SimpleNamespace(ready=problem != "both_raw_blocked" and not (problem == "first_raw_blocked" and day == dates[0]))

    raw = Mock(side_effect=raw_ready)
    monkeypatch.setattr(sensor, "raw_tushare_suspend_d_ready_for_trade_date", raw)
    if problem == "connection_error":
        monkeypatch.setattr(type(resources["duckdb"]), "connect", Mock(side_effect=RuntimeError("synthetic connection error")))
    result = sensor.silver_suspend_d_update_job_sensor._raw_fn(context)
    zero = problem in ("no_candidates", "gap", "connection_error")
    assert checked.call_count == inspect.call_count == (0 if zero else 1)
    assert instance.fetch_materializations.call_count == (0 if zero else 1)
    assert instance.event_log_storage.get_asset_check_execution_history.call_count == (0 if zero else 2)
    expected_runs = [] if problem in ("no_candidates", "gap", "connection_error", "both_raw_blocked", "fixed_blocked") else [dates[1]] if problem == "first_raw_blocked" else list(dates[:2])
    assert [request.partition_key for request in result.run_requests] == expected_runs
    assert [request.run_key for request in result.run_requests] == [f"silver_suspend_d_update:{day}" for day in expected_runs]
    assert raw.call_count == (0 if zero or problem == "fixed_blocked" else len(dates[:2]))
    payload = json.loads(result.cursor)
    assert result.cursor.count('"stock_suspend_confirmed":') == (0 if problem in ("no_candidates", "gap") else 1)
    assert payload["details"]["evidence"]["max_run_requests_per_tick"] == 2
    assert "frontier" in payload["details"]
    if problem == "no_candidates":
        assert payload["details"]["reason_code"] == "all_ready"
    if problem in ("fixed_blocked", "connection_error"):
        assert payload["details"]["reason_code"] == "confirmed_not_ready"
    if problem == "first_raw_blocked":
        assert raw.call_args_list[0].args[1] == dates[0] and raw.call_args_list[1].args[1] == dates[1]
