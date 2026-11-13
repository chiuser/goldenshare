"""Independent upstream contracts, native temporary records and THS precheck boundaries."""

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from datetime import time as daytime
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from requests import Response
from requests.exceptions import HTTPError

from orchestrator.defs import paths
from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_connection
from orchestrator.defs.run_contracts import moneyflow_automation as automation
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError
from orchestrator.defs.sensors import moneyflow_ths_sensor as sensors
from orchestrator.defs.sensors import moneyflow_update_selection as selection
from orchestrator.defs.sensors import readiness
from orchestrator.defs.source_readiness import moneyflow_ths as source
from orchestrator.defs.tushare_errors import TushareResponseError
from tests import test_moneyflow_ths_definitions as definitions
from tests.test_moneyflow_ths_definitions import IsolatedLake
from tests.test_moneyflow_ths_http_worker import (
    TOKEN,
    Reply,
    localhost_source,
    source_body,
)

pytest_plugins = ("tests.test_moneyflow_ths_http_worker",)

DAY = "2026-11-10"
NOW = datetime(2026, 11, 10, 20, 0, tzinfo=readiness.CN_A_SENSOR_TIMEZONE)
EXPECTED = frozenset({"000001.SZ", "600002.SH", "000004.SZ", "000007.SZ", "000010.SZ"})
LIFECYCLE = readiness.SILVER_STOCK_LIFECYCLE_READINESS_SPEC
SUSPEND = readiness.AssetReadinessSpec(readiness.SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY, readiness.SILVER_SUSPEND_D_CHECKS)


def seed(instance, spec, partition=None, *, bad=None):
    instance.report_runless_asset_event(dg.AssetMaterialization(asset_key=spec.asset_key, partition=partition))
    query = dg.AssetRecordsFilter(asset_key=spec.asset_key, asset_partitions=[partition] if partition else None)
    record = instance.fetch_materializations(query, limit=1).records[0]
    if bad == "stale":
        timestamp = datetime(2026, 11, 9, tzinfo=readiness.CN_A_SENSOR_TIMEZONE).timestamp()
        instance.event_log_storage.store_event(record.event_log_entry._replace(timestamp=timestamp))
        record = instance.fetch_materializations(query, limit=1).records[0]
    for i, name in enumerate(spec.blocking_check_names):
        evaluation = AssetCheckEvaluation(
            asset_key=spec.asset_key, partition=partition, check_name=name,
            passed=not (bad == "failed" and i == 0), blocking=bad != "nonblocking",
            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                storage_id=record.storage_id + int(bad == "binding"),
                run_id=record.run_id, timestamp=record.timestamp,
            ),
        )
        # Repeated partitioned evaluations require distinct native run identities.
        # Runless checks all use run_id='', which collides on the second partitioned batch.
        instance.report_dagster_event(
            dg.DagsterEvent(
                event_type_value="ASSET_CHECK_EVALUATION", job_name="stage2_upstream_fixture",
                event_specific_data=evaluation,
            ),
            run_id=f"stage2-check-{record.storage_id}",
        )


def inputs(root, temp, *, empty_suspend=False, capacity=None):
    # Full producer schemas verified against assets/stock_lifecycle.py,
    # assets/suspend_d.py and physical footer schemas on 2026-11-13.
    life, suspend = paths.silver_stock_lifecycle_path(root), paths.silver_stock_suspend_daily_path(root, DAY)
    life.parent.mkdir(parents=True, exist_ok=True)
    suspend.parent.mkdir(parents=True, exist_ok=True)
    with moneyflow_candidate_connection(temp) as con:
        con.execute("CREATE TABLE life(ts_code VARCHAR,symbol VARCHAR,name VARCHAR,exchange VARCHAR,market VARCHAR,curr_type VARCHAR,is_cny_stock BOOLEAN,list_status VARCHAR,list_date DATE,delist_date DATE)")
        if capacity is not None:
            con.execute("INSERT INTO life SELECT printf('%06d.SZ',i+1),printf('%06d',i+1),'人工样本','SZSE','主板','CNY',true,'L',DATE '2010-01-01',NULL FROM range(?) t(i)", [capacity])
        else:
            for code, cny, listed, delisted in (
                ("000001.SZ", True, "2010-01-01", None),
                ("600002.SH", True, DAY, None),
                ("000003.SZ", True, "2010-01-01", DAY),
                ("000004.SZ", True, "2010-01-01", "2026-11-11"),
                ("000005.SZ", True, "2026-11-11", None),
                ("000006.SZ", True, "2010-01-01", None),
                ("000007.SZ", True, "2010-01-01", None),
                ("200008.SZ", False, "2010-01-01", None),
                ("920009.BJ", True, "2010-01-01", None),
                ("000010.SZ", True, "2010-01-01", None),
            ):
                con.execute("INSERT INTO life VALUES (?,?,?,'SZSE','主板',?,?,?,CAST(? AS DATE),CAST(? AS DATE))", [code, code[:6], "人工样本", "CNY" if cny else "HKD", cny, "D" if delisted else "L", listed, delisted])
        con.execute("COPY life TO ? (FORMAT PARQUET)", [str(life)])
        con.execute("CREATE TABLE suspension(ts_code VARCHAR,trade_date DATE,suspend_timing VARCHAR,suspend_type VARCHAR)")
        if not empty_suspend and capacity is None:
            for code, timing, kind in (("000006.SZ", None, "S"), ("000007.SZ", "09:30-10:00", "S"), ("000010.SZ", None, "R")):
                con.execute("INSERT INTO suspension VALUES (?,CAST(? AS DATE),?,?)", [code, DAY, timing, kind])
        con.execute("COPY suspension TO ? (FORMAT PARQUET)", [str(suspend)])


@pytest.fixture
def market(tmp_path, monkeypatch):
    monkeypatch.delenv("DAGSTER_HOME", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr(source, "DEFAULT_DUCKDB_TEMP_DIRECTORY", tmp_path)
    root = tmp_path / "lake"
    root.mkdir()
    inputs(root, tmp_path)
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    with dg.DagsterInstance.local_temp(str(instance_path), overrides={"telemetry": {"enabled": False}}) as instance:
        seed(instance, LIFECYCLE)
        seed(instance, SUSPEND, DAY)
        yield SimpleNamespace(
            root=root, tmp=tmp_path, instance=instance,
            resources=SimpleNamespace(lake_root=IsolatedLake(root_path=str(root)), tushare=SimpleNamespace(token="isolated-stage2-token")),
        )


def response(codes, *, columns=source.FIELDS):
    return SimpleNamespace(columns=columns, rows=[{"ts_code": c, "trade_date": "20261110"} for c in codes])


def check(market, monkeypatch, pages):
    calls = []
    iterator = iter(pages)

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        value = next(iterator)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(source, "call_moneyflow_source", request)
    return source.check_moneyflow_ths_source_ready(market, DAY, deadline=time.perf_counter() + 60), calls


def test_real_upstream_files_define_target_day_universe(market):
    expected, suspended = source.load_moneyflow_ths_universe(market.instance, market.root, DAY, deadline=time.perf_counter() + 60)
    assert expected == EXPECTED
    assert suspended == {"000006.SZ"}


def test_valid_empty_final_suspension_is_not_missing(market, monkeypatch):
    inputs(market.root, market.tmp, empty_suspend=True)
    result, calls = check(market, monkeypatch, [response(sorted(EXPECTED | {"000006.SZ"}))])
    assert result.ready and result.missing_count == 0 and len(calls) == 1


@pytest.mark.parametrize("missing,ready", [(0, True), (24, True), (25, False)])
def test_literal_missing_boundary_with_real_universe(market, monkeypatch, missing, ready):
    inputs(market.root, market.tmp, capacity=30)
    result, calls = check(market, monkeypatch, [response([f"{i:06d}.SZ" for i in range(missing + 1, 31)])])
    assert result.ready is ready
    assert (result.expected_count, result.source_count, result.missing_count) == (30, 30 - missing, missing)
    assert calls[0][0][1:] == ("moneyflow_ths", {"trade_date": "20261110", "limit": 2000, "offset": 0}, ("ts_code", "trade_date"))


def test_equal_counts_do_not_mask_one_missing_with_legal_suspension(market, monkeypatch):
    codes = (EXPECTED - {"000001.SZ"}) | {"000006.SZ"}
    result, _ = check(market, monkeypatch, [response(sorted(codes))])
    assert result.ready and result.expected_count == result.source_count == 5
    assert result.missing_count == 1


@pytest.mark.parametrize("extra", ["000003.SZ", "000005.SZ", "200008.SZ", "920009.BJ", "999999.SH"])
def test_extra_codes_are_not_silently_dropped(market, monkeypatch, extra):
    result, _ = check(market, monkeypatch, [response(sorted(EXPECTED | {extra}))])
    assert not result.ready and result.reason == "source_extra_codes"


@pytest.mark.parametrize("spec,partition,bad,reason", [
    (LIFECYCLE, None, "failed", "source_lifecycle_not_ready"),
    (LIFECYCLE, None, "binding", "source_lifecycle_not_ready"),
    (LIFECYCLE, None, "stale", "source_lifecycle_not_ready"),
    (SUSPEND, DAY, "failed", "source_suspend_not_ready"),
    (SUSPEND, DAY, "binding", "source_suspend_not_ready"),
    (SUSPEND, DAY, "nonblocking", "source_suspend_not_ready"),
])
def test_actual_bad_native_evidence_stops_before_source(market, monkeypatch, spec, partition, bad, reason):
    seed(market.instance, spec, partition, bad=bad)
    result, calls = check(market, monkeypatch, [])
    assert not result.ready and result.reason == reason and not calls


@pytest.mark.parametrize("asset", ["lifecycle", "suspension"])
def test_missing_input_file_is_not_ready(market, monkeypatch, asset):
    path = paths.silver_stock_lifecycle_path(market.root) if asset == "lifecycle" else paths.silver_stock_suspend_daily_path(market.root, DAY)
    path.unlink()  # Owned temporary fixture only.
    result, calls = check(market, monkeypatch, [])
    assert result.reason == "source_universe_unavailable" and not calls


def test_empty_expected_universe_waits(market, monkeypatch):
    inputs(market.root, market.tmp, capacity=0)
    result, calls = check(market, monkeypatch, [])
    assert result.reason == "source_expected_empty" and not calls


@pytest.mark.parametrize("fault,reason", [
    (SimpleNamespace(columns=("trade_date", "ts_code"), rows=[]), "source_schema"),
    (SimpleNamespace(columns=source.FIELDS, rows=[{"ts_code": "000001.SZ", "trade_date": "20261111"}]), "source_partition_or_key"),
    (SimpleNamespace(columns=source.FIELDS, rows=[{"ts_code": None, "trade_date": "20261110"}]), "source_partition_or_key"),
    (SimpleNamespace(columns=source.FIELDS, rows=[{"ts_code": "bad", "trade_date": "20261110"}]), "source_partition_or_key"),
    (SimpleNamespace(columns=source.FIELDS, rows=[{"ts_code": "000001.SZ"}]), "source_partition_or_key"),
    (response(["000001.SZ", "000001.SZ"]), "source_duplicate_key"),
    (response([]), "source_empty"),
    (response(["000001.SZ"] * 2001), "source_page_size"),
])
def test_bad_source_never_uses_missing_tolerance(market, monkeypatch, fault, reason):
    result, calls = check(market, monkeypatch, [fault])
    assert not result.ready and result.reason == reason and len(calls) == 1


def test_cross_page_duplicate_and_partial_failure_stop_immediately(market, monkeypatch):
    first = response([f"{i:06d}.SZ" for i in range(1, 2001)])
    result, calls = check(market, monkeypatch, [first, response(["000001.SZ"])])
    assert result.reason == "source_duplicate_key" and len(calls) == 2
    result, calls = check(market, monkeypatch, [first, TushareResponseError("not complete")])
    assert not result.ready and len(calls) == 2


@pytest.mark.parametrize("status,reason", [(403, "source_permission_or_parameter"), (429, "rate_limit"), (503, "transient")])
def test_source_error_categories_do_not_retry_in_sensor(market, monkeypatch, status, reason):
    raw = Response()
    raw.status_code = status
    result, calls = check(market, monkeypatch, [HTTPError("credential-must-not-appear", response=raw)])
    assert result.reason == reason and not result.ready and len(calls) == 1
    assert "credential" not in repr(result)


@pytest.mark.parametrize("end", [False, True])
def test_20000_row_bound_and_empty_end_page(market, monkeypatch, end):
    inputs(market.root, market.tmp, capacity=20000)
    pages = [response([f"{i:06d}.SZ" for i in range(offset + 1, offset + 2001)]) for offset in range(0, 20000, 2000)]
    pages.append(response([] if end else ["020001.SZ"]))
    result, calls = check(market, monkeypatch, pages)
    assert len(calls) == 11
    assert result.ready is end
    assert result.reason == ("ready" if end else "source_row_budget")


def test_sql_deadline_interrupts_real_query_and_joins_timer(market):
    before = set(threading.enumerate())
    with pytest.raises(duckdb.InterruptException), source.moneyflow_ths_connection(time.perf_counter() + 0.3) as connection:
        connection.execute("SELECT sum(sin(i::DOUBLE)) FROM range(1000000000) t(i)").fetchall()
    assert set(threading.enumerate()) == before


def test_expired_deadline_does_not_read_upstream_or_source(market, monkeypatch):
    monkeypatch.setattr(source, "silver_stock_lifecycle_ready_for_trade_date", lambda *_: pytest.fail("expired upstream read"))
    result = source.check_moneyflow_ths_source_ready(market, DAY, deadline=time.perf_counter() - 1)
    assert result.reason == "source_precheck_deadline"


def test_whole_source_window_is_not_reset_between_pages(market, monkeypatch):
    clock = [0.0]
    deadlines = []
    monkeypatch.setattr(source, "load_moneyflow_ths_universe", lambda *a, **kw: (frozenset({"000001.SZ"}), frozenset()))
    def request(*args, **kwargs):
        deadlines.append(kwargs["deadline"])
        clock[0] += 16
        return response([f"{i:06d}.SZ" for i in range(1, 2001)])
    monkeypatch.setattr(source, "call_moneyflow_source", request)
    result = source.check_moneyflow_ths_source_ready(market, DAY, deadline=60, clock=lambda: clock[0])
    assert not result.ready and result.reason == "source_precheck_deadline"
    assert deadlines == [30, 30]


def test_fixed_contract_time_and_tolerance_are_ths_only():
    for value in vars(automation).values():
        if isinstance(value, automation.MoneyflowAutomationContract):
            automation.require_moneyflow_automation_contract(value)
            assert value.register_start == daytime(20 if value.dataset == "moneyflow_ths" else 22, 0)
            assert value.missing_record_limit == (25 if value.dataset == "moneyflow_ths" else None)


@pytest.mark.parametrize("change", [{"register_start": daytime(21, 0)}, {"missing_record_limit": 26}])
def test_changed_automation_contract_still_rejected(change):
    with pytest.raises(MoneyflowContractError, match="automation_dataset"):
        automation.require_moneyflow_automation_contract(replace(automation.STOCK_THS_MONEYFLOW_AUTOMATION, **change))


@pytest.mark.parametrize("case,reason", [
    ("no_lifecycle", "source_lifecycle_not_ready"),
    ("no_suspend", "source_suspend_not_ready"),
    ("other_partition", "source_suspend_not_ready"),
])
def test_missing_or_other_partition_native_evidence_never_requests_source(market, monkeypatch, case, reason):
    path = market.tmp / "missing-instance"
    path.mkdir()
    with dg.DagsterInstance.local_temp(str(path), overrides={"telemetry": {"enabled": False}}) as instance:
        if case != "no_lifecycle":
            seed(instance, LIFECYCLE)
        if case == "other_partition":
            seed(instance, SUSPEND, "2026-11-09")
        isolated = SimpleNamespace(instance=instance, resources=market.resources)
        result, calls = check(isolated, monkeypatch, [])
    assert not result.ready and result.reason == reason and not calls


@pytest.mark.parametrize("error", [KeyboardInterrupt(), MemoryError(), RuntimeError("local bug")])
def test_cancellation_and_unexpected_local_failure_are_not_swallowed(market, monkeypatch, error):
    with pytest.raises(type(error)):
        check(market, monkeypatch, [error])


@contextmanager
def sensor_context(market, monkeypatch, *, cursor=None):
    calendar = paths.silver_trade_calendar_path(market.root)
    calendar.parent.mkdir(parents=True, exist_ok=True)
    with moneyflow_candidate_connection(market.tmp) as con:
        con.execute("COPY (SELECT 'SSE' exchange,DATE '2026-11-10' trade_date,true is_open) TO ? (FORMAT PARQUET)", [str(calendar)])
    market.instance.add_dynamic_partitions(sensors.PARTITIONS, [DAY])
    resources = {
        "lake_root": market.resources.lake_root,
        "duckdb": dg.ResourceDefinition.hardcoded_resource(SimpleNamespace()),
        "tushare": dg.ResourceDefinition.hardcoded_resource(SimpleNamespace(token=TOKEN)),
    }
    defs = dg.Definitions(
        assets=[definitions.RAW, definitions.SILVER], asset_checks=definitions.CHECKS,
        jobs=[definitions.raw_tushare_moneyflow_ths_update_job, definitions.silver_moneyflow_ths_update_job],
        sensors=[sensors.raw_tushare_moneyflow_ths_update_job_sensor], resources=resources,
    )
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(sensors, "datetime", FixedDateTime)
    with (
        dg.partition_loading_context(dynamic_partitions_store=market.instance),
        dg.build_sensor_context(instance=market.instance, definitions=defs, resources=resources, cursor=cursor) as context,
    ):
        yield context


def test_native_tick_real_three_page_http_worker_and_cost(market, monkeypatch, ths_probe, record_property):
    inputs(market.root, market.tmp, capacity=5218)
    query_calls, metadata_calls, history_calls, deadlines, call_times = [], [], [], [], []
    original_connection = source.moneyflow_candidate_connection
    original_materialization = market.instance.fetch_materializations
    original_history = market.instance.event_log_storage.get_asset_check_execution_history
    real_call = source.call_moneyflow_source

    @contextmanager
    def observed_connection(directory):
        with original_connection(directory) as con:
            class Observed:
                def execute(self, sql, *args):
                    query_calls.append(sql)
                    return con.execute(sql, *args)
                def interrupt(self):
                    con.interrupt()
            yield Observed()

    def materializations(filter, **kwargs):
        result = original_materialization(filter, **kwargs)
        if filter.asset_key in (LIFECYCLE.asset_key, SUSPEND.asset_key):
            metadata_calls.append((filter.asset_key.to_user_string(), filter.asset_partitions, kwargs["limit"], len(result.records)))
        return result

    def history(key, **kwargs):
        result = original_history(key, **kwargs)
        if key.asset_key in (LIFECYCLE.asset_key, SUSPEND.asset_key):
            history_calls.append((kwargs["limit"], len(result)))
        return result

    def actual_request(*args, **kwargs):
        call_times.append(time.perf_counter())
        deadlines.append(kwargs["deadline"])
        return real_call(*args, **kwargs, _command=ths_probe.command)

    def http(payload, _):
        offset = payload["params"]["offset"]
        records = [{"ts_code": f"{i:06d}.SZ", "trade_date": "20261110"} for i in range(offset + 1, min(offset + 2000, 5218) + 1)]
        return Reply(200, source_body(("ts_code", "trade_date"), records))

    with sensor_context(market, monkeypatch) as context:
        monkeypatch.setattr(source, "moneyflow_candidate_connection", observed_connection)
        monkeypatch.setattr(market.instance, "fetch_materializations", materializations)
        monkeypatch.setattr(market.instance.event_log_storage, "get_asset_check_execution_history", history)
        monkeypatch.setattr(source, "call_moneyflow_source", actual_request)
        with localhost_source(http) as (url, requests):
            monkeypatch.setenv("TUSHARE_BASE_URL", url)
            started = time.perf_counter()
            result = sensors.raw_tushare_moneyflow_ths_update_job_sensor.evaluate_tick(context)
            elapsed = time.perf_counter() - started
    assert len(result.run_requests) == 1 and result.run_requests[0].partition_key == DAY
    assert load_sensor_cursor(result.cursor)["details"]["reason_code"] == "request_run"
    assert len(result.cursor.encode()) < 2048 and "000001.SZ" not in result.cursor
    assert len(query_calls) == 2  # Calendar plus target-day universe; configuration checks are separate.
    assert len(metadata_calls) == 2 and all(row[2:] == (1, 1) for row in metadata_calls)
    assert len(history_calls) == 6 and history_calls == [(5000, 1)] * 6
    assert [r[1]["params"] for r in requests] == [{"trade_date": "20261110", "limit": 2000, "offset": offset} for offset in (0, 2000, 4000)]
    assert all(r[1]["fields"] == "ts_code,trade_date" and r[1]["token"] == TOKEN for r in requests)
    assert len(ths_probe.owned) == 3 and len(set(deadlines)) == 1
    assert market.instance.get_runs_count() == 0  # Proposal only; no Raw job executes.
    assert elapsed < 60 and deadlines[0] <= started + 60
    assert 0 < deadlines[0] - call_times[0] <= 30
    record_property("ths_stage2_full_tick", json.dumps({
        "seconds": elapsed, "source_rows": 5218, "http_requests": 3,
        "workers": 3, "business_sql": 2, "connection_settings_sql": 4,
        "upstream_metadata_calls": 8, "upstream_returned_records": 8,
        "cursor_bytes": len(result.cursor.encode()), "loopback_only": True,
    }))


def test_precheck_failure_does_not_advance_attempt_or_store_partial_codes(market, monkeypatch):
    inputs(market.root, market.tmp, capacity=30)
    calls = []
    def request(*args, **kwargs):
        calls.append(args[2])
        return response([f"{i:06d}.SZ" for i in range(26, 31)])
    monkeypatch.setattr(source, "call_moneyflow_source", request)
    with sensor_context(market, monkeypatch) as context:
        first = sensors.raw_tushare_moneyflow_ths_update_job_sensor.evaluate_tick(context)
    with sensor_context(market, monkeypatch, cursor=first.cursor) as context:
        second = sensors.raw_tushare_moneyflow_ths_update_job_sensor.evaluate_tick(context)
    assert not first.run_requests and not second.run_requests and len(calls) == 2
    state = load_sensor_cursor(second.cursor)
    assert state["details"]["reason_code"] == "source_missing_codes"
    # The existing cursor builder removes recursively empty runtime state.
    assert "runtime_state" not in state["details"]
    assert "000026.SZ" not in second.cursor and "缺失25" in second.cursor
    previous = json.loads(first.cursor)
    previous["details"]["runtime_state"] = {"dates": {DAY: {"attempt": 2, "attempt_date": DAY}}}
    with sensor_context(market, monkeypatch, cursor=json.dumps(previous)) as context:
        third = sensors.raw_tushare_moneyflow_ths_update_job_sensor.evaluate_tick(context)
    assert not third.run_requests and len(calls) == 3
    assert load_sensor_cursor(third.cursor)["details"]["runtime_state"]["dates"][DAY]["attempt"] == 2
    def no_response(*args, **kwargs):
        raise TushareResponseError("no valid response")
    monkeypatch.setattr(source, "call_moneyflow_source", no_response)
    with sensor_context(market, monkeypatch, cursor=third.cursor) as context:
        incomplete = sensors.raw_tushare_moneyflow_ths_update_job_sensor.evaluate_tick(context)
    assert not incomplete.run_requests
    assert "缺失0" not in incomplete.cursor and "返回0" not in incomplete.cursor


def test_local_selection_time_is_part_of_rpc_budget(market, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(selection, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(selection, "default_sensor_grpc_timeout", lambda: 60)
    @contextmanager
    def calendar(deadline):
        assert deadline == 60
        with moneyflow_candidate_connection(market.tmp) as con:
            yield con
    monkeypatch.setattr(selection, "moneyflow_ths_connection", calendar)
    original = selection.batch_moneyflow_readiness
    def slow_local(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = 61
        return result
    monkeypatch.setattr(selection, "batch_moneyflow_readiness", slow_local)
    monkeypatch.setattr(source, "perf_counter", lambda: clock[0])
    def budgeted(context, day, *, deadline):
        return source.check_moneyflow_ths_source_ready(context, day, deadline=deadline, clock=lambda: clock[0])
    monkeypatch.setattr(selection, "check_moneyflow_ths_source_ready", budgeted)
    monkeypatch.setattr(source, "silver_stock_lifecycle_ready_for_trade_date", lambda *_: pytest.fail("expired upstream"))
    with sensor_context(market, monkeypatch) as context:
        result = sensors.raw_tushare_moneyflow_ths_update_job_sensor.evaluate_tick(context)
    assert not result.run_requests
    assert load_sensor_cursor(result.cursor)["details"]["reason_code"] == "source_precheck_deadline"
