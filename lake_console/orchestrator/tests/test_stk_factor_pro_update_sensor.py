"""Step-six evaluation on real producer-shaped files and a temporary native store.

Most cases replace only the two-column HTTP probe. The explicit HTTP case
replays an archived real row through the actual transport and coverage code.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationPlanned,
)
from dagster._core.remote_origin import (
    RegisteredCodeLocationOrigin,
    RemoteRepositoryOrigin,
)
from dagster._core.storage.tags import PARTITION_NAME_TAG, RUN_KEY_TAG, SENSOR_NAME_TAG
from sqlalchemy import event
from sqlalchemy.engine import Engine

from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.sensors import (
    raw_tushare_stk_factor_pro_update_job_sensor as sensor,
)
from orchestrator.defs.source_readiness.stk_factor_pro import (
    StkFactorProSourceProbeResult,
    probe_stk_factor_pro_source,
)
from orchestrator.tushare_download.configuration import ConfigurationSnapshot
from tests.stk_factor_pro_history_test_support import saved_real_rows, write_factor_file
from tests.stk_factor_pro_test_support import connection, row
from tests.test_stk_factor_pro_batch5_job_integration import seed_upstream_events
from tests.test_stk_factor_pro_bootstrap_coverage import upstream
from tests.test_stk_factor_pro_dagster_events import _isolated_instance
from tests.test_stk_factor_pro_history_repair import setup_failed_history
from tests.test_stk_factor_pro_jobs import (
    DAY,
    PREVIOUS,
    A,
    B,
    config,
    input_files,
    isolated_update_environment,
)
from tests.tushare_download.test_tushare_download_http_integration import (
    Reply,
    localhost_source,
    success,
)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    with isolated_update_environment(
        tmp_path, monkeypatch, substitute_upstream=False
    ) as env:
        instance, _, _, lake, staging, _ = env
        input_files(tmp_path, lake, changed=())
        seed_upstream_events(instance)
        clock = [datetime.fromisoformat("2026-10-16T19:00:00+08:00")]
        monkeypatch.setattr(sensor, "_now", lambda: clock[0])
        monkeypatch.setattr(sensor, "DEFAULT_LAKE_STAGING_ROOT", staging)
        calls = []

        def source(conn, **kwargs):
            calls.append(kwargs["target_trade_date"])
            return StkFactorProSourceProbeResult(
                DAY,
                True,
                "test source ready",
                source_row_count=2,
                source_code_count=2,
                request_count=1,
                page_count=1,
            )

        monkeypatch.setattr(sensor, "probe_stk_factor_pro_source", source)
        context = SimpleNamespace(
            instance=instance,
            cursor=None,
            resources=SimpleNamespace(
                lake_root=SimpleNamespace(
                    root=lambda: lake, ensure_available_for_run=lambda: None
                ),
                duckdb=SimpleNamespace(connect=lambda: connection(tmp_path)),
            ),
        )
        yield env, context, clock, calls


def evaluate(environment):
    context = environment[1]
    result = sensor.evaluate_stk_factor_pro_update(context)
    context.cursor = result.cursor
    return result


@pytest.mark.parametrize(
    "time,slot",
    [("18:59", None), ("19:00", 0), ("23:30", 9), ("23:59", 9), ("00:00", None)],
)
def test_operating_slots_and_exact_request_contract(environment, time, slot):
    env, _, clock, calls = environment
    clock[0] = datetime.fromisoformat("2026-10-16T" + time + ":00+08:00")
    result = evaluate(environment)
    assert len(result.run_requests) == int(slot is not None)
    assert calls == ([] if slot is None else [DAY])
    if slot is not None:
        request = result.run_requests[0]
        assert request.partition_key == "2026-10-16"
        assert (
            request.run_key
            == f"raw_tushare_stk_factor_pro_update_job:2026-10-16/2026-10-16/{slot}"
        )
        assert request.tags == {
            "goldenshare/stk_factor_pro_execution_day": "2026-10-16",
            "goldenshare/stk_factor_pro_target_trade_date": "2026-10-16",
            "goldenshare/stk_factor_pro_scheduled_slot": str(slot),
        }
        assert request.run_config == {
            "ops": {
                "stk_factor_pro": {
                    "config": {
                        "execution_day": "2026-10-16",
                        "target_trade_date": "2026-10-16",
                        "purpose": "today",
                        "scheduled_slot": slot,
                        "bootstrap_operation_id": None,
                        "expected_bootstrap_approval_digest": None,
                        "expected_bootstrap_date_result_digest": None,
                    }
                }
            }
        }
    assert not list(env[3].glob("raw/tushare/stk_factor_pro/**/*"))


@pytest.mark.parametrize(
    "problem", ["closed", "missing_today", "missing_P", "missing_partition"]
)
def test_local_date_or_partition_not_ready_has_no_probe(environment, tmp_path, problem):
    env, context, _, calls = environment
    if problem == "missing_partition":
        context.instance.delete_dynamic_partition(C.STK_FACTOR_PRO_PARTITIONS, str(DAY))
    else:
        calendar = [("SSE", DAY, problem != "closed", PREVIOUS)]
        if problem != "missing_P":
            calendar.append(("SSE", PREVIOUS, True, PREVIOUS - timedelta(days=1)))
        if problem == "missing_today":
            calendar = calendar[1:]
        with connection(tmp_path) as conn:
            upstream(conn, env[3], (PREVIOUS, DAY), codes=(A, B), calendar=calendar)
    assert not evaluate(environment).run_requests
    assert not calls
    assert load_sensor_cursor(context.cursor)["details"]["last_probed_slot"] is None


@pytest.mark.parametrize(
    "status",
    [
        dg.DagsterRunStatus.SUCCESS,
        dg.DagsterRunStatus.FAILURE,
        dg.DagsterRunStatus.CANCELED,
        dg.DagsterRunStatus.QUEUED,
    ],
)
def test_persisted_slot_deduplicates_all_run_states_after_cursor_clear(
    environment, status
):
    env, context, _, calls = environment
    request = evaluate(environment).run_requests[0]
    context.instance.create_run_for_job(
        env[1],
        run_config=request.run_config,
        remote_job_origin=RemoteRepositoryOrigin(
            RegisteredCodeLocationOrigin("isolated-stock-factor"), "test_repository"
        ).get_job_origin(env[1].name),
        status=status,
        tags={
            **request.tags,
            PARTITION_NAME_TAG: request.partition_key,
            SENSOR_NAME_TAG: C.STK_FACTOR_PRO_UPDATE_SENSOR_NAME,
            RUN_KEY_TAG: request.run_key,
        },
    )
    context.cursor = None
    assert not evaluate(environment).run_requests
    assert calls == [DAY]


def test_reopened_instance_still_finds_persisted_submission(environment, tmp_path):
    env, context, _, calls = environment
    request = evaluate(environment).run_requests[0]
    context.instance.create_run_for_job(
        env[1],
        run_config=request.run_config,
        status=dg.DagsterRunStatus.SUCCESS,
        tags={
            **request.tags,
            SENSOR_NAME_TAG: C.STK_FACTOR_PRO_UPDATE_SENSOR_NAME,
            RUN_KEY_TAG: request.run_key,
        },
    )
    with _isolated_instance(tmp_path) as reopened:
        context.instance, context.cursor = reopened, None
        assert not evaluate(environment).run_requests
    context.instance = env[0]
    assert calls == [DAY]


def test_active_repair_stops_before_source_and_readiness(environment, monkeypatch):
    from orchestrator.defs.jobs.stk_factor_pro_history_repair import (
        raw_tushare_stk_factor_pro_repair_job,
    )
    from tests.test_stk_factor_pro_history_repair import repair_job_context

    env, context, _, calls = environment
    with repair_job_context(env[1]) as repair:
        assert repair.name == raw_tushare_stk_factor_pro_repair_job.name
        context.instance.create_run_for_job(
            repair,
            status=dg.DagsterRunStatus.QUEUED,
            remote_job_origin=RemoteRepositoryOrigin(
                RegisteredCodeLocationOrigin("isolated-stock-factor"), "test_repository"
            ).get_job_origin(repair.name),
            run_config={
                "ops": {
                    "repair_stk_factor_pro_history": {
                        "config": {
                            "target_trade_date": str(DAY),
                            "source_run_id": "authorized-source",
                            "expected_history_plan_digest": "a" * 64,
                            "expected_history_ranges_digest": "b" * 64,
                        }
                    }
                }
            },
        )
    monkeypatch.setattr(
        sensor.R,
        "read_stk_factor_pro_recorded_results",
        lambda *a, **k: pytest.fail("records read while writer active"),
    )
    assert not evaluate(environment).run_requests and not calls


def test_source_not_ready_consumes_slot_but_next_slot_can_probe(
    environment, monkeypatch
):
    _, context, clock, _ = environment
    calls = []

    def probe(*a, **k):
        calls.append(k["target_trade_date"])
        return StkFactorProSourceProbeResult(DAY, len(calls) > 1, "source waiting")

    monkeypatch.setattr(sensor, "probe_stk_factor_pro_source", probe)
    assert not evaluate(environment).run_requests
    assert not evaluate(environment).run_requests and len(calls) == 1
    clock[0] += timedelta(minutes=30)
    assert len(evaluate(environment).run_requests) == 1 and calls == [DAY, DAY]
    assert load_sensor_cursor(context.cursor)["details"]["last_probed_slot"] == 1


def test_local_wait_can_recover_in_same_slot(environment, monkeypatch):
    _, _, _, calls = environment
    read = sensor.R.read_stk_factor_pro_upstream_status
    with monkeypatch.context() as patch:
        patch.setattr(
            sensor.R,
            "read_stk_factor_pro_upstream_status",
            lambda *a, **k: SimpleNamespace(
                ready=False, reason="waiting local producer"
            ),
        )
        assert not evaluate(environment).run_requests
    assert sensor.R.read_stk_factor_pro_upstream_status is read
    assert len(evaluate(environment).run_requests) == 1 and calls == [DAY]


@pytest.mark.parametrize(
    "start,end", [("19:29:59", "19:30:01"), ("23:59:59", "00:00:01")]
)
def test_probe_crossing_slot_or_midnight_never_submits_new_slot(
    environment, monkeypatch, start, end
):
    _, context, clock, _ = environment
    clock[0] = datetime.fromisoformat("2026-10-16T" + start + "+08:00")
    old_slot = 0 if start.startswith("19") else 9

    def crossed(*a, **k):
        clock[0] = datetime.fromisoformat(
            ("2026-10-17" if end.startswith("00") else "2026-10-16")
            + "T"
            + end
            + "+08:00"
        )
        return StkFactorProSourceProbeResult(DAY, True, "ready after boundary")

    monkeypatch.setattr(sensor, "probe_stk_factor_pro_source", crossed)
    assert not evaluate(environment).run_requests
    assert load_sensor_cursor(context.cursor)["details"]["last_probed_slot"] == old_slot


@pytest.mark.parametrize("revised_day", [DAY, PREVIOUS], ids=["T", "P"])
def test_valid_day_no_action_skips_source_but_factor_revision_submits(
    environment, tmp_path, revised_day
):
    env, _, clock, calls = environment
    source = env[2]((row(A), row(B)))
    completed = env[1].execute_in_process(
        instance=env[0],
        partition_key=str(DAY),
        run_config=config(),
        raise_on_error=False,
    )
    assert completed.success, completed.failure_data_for_node("stk_factor_pro")
    assert len(source.calls) == 1
    assert not evaluate(environment).run_requests and not calls
    with connection(tmp_path) as conn:
        write_factor_file(conn, env[3], revised_day, ((A, 2), (B, 1)))
    clock[0] += timedelta(minutes=30)
    assert len(evaluate(environment).run_requests) == 1 and calls == [DAY]


def test_permanent_day_failure_does_not_start_another_job(environment):
    env, _, _, calls = environment
    env[2]((row(A), row(A)))
    failed = env[1].execute_in_process(
        instance=env[0],
        partition_key=str(DAY),
        run_config=config(),
        raise_on_error=False,
    )
    assert not failed.success
    metadata = failed.failure_data_for_node("stk_factor_pro").user_failure_data.metadata
    assert metadata["goldenshare/retryable"].value is False
    assert not evaluate(environment).run_requests and not calls


def test_history_pending_retries_without_changing_target_date(
    environment, tmp_path, monkeypatch
):
    env, _, _, calls = environment
    setup_failed_history(tmp_path, monkeypatch, env)
    assert len(evaluate(environment).run_requests) == 1 and calls == [DAY]


def test_previous_day_failure_does_not_block_today(environment):
    env, context, _, calls = environment
    context.instance.create_run_for_job(
        env[1],
        run_config=config(PREVIOUS),
        status=dg.DagsterRunStatus.FAILURE,
        tags={PARTITION_NAME_TAG: str(PREVIOUS)},
    )
    assert len(evaluate(environment).run_requests) == 1 and calls == [DAY]


def test_ready_day_uses_metadata_and_plan_without_technical_file_reads(
    environment, monkeypatch
):
    env, _, _, calls = environment
    env[2]((row(A), row(B)))
    done = env[1].execute_in_process(
        instance=env[0],
        partition_key=str(DAY),
        run_config=config(),
        raise_on_error=False,
    )
    assert done.success
    prohibited = {
        raw_stk_factor_pro_path(env[3], str(DAY)),
        silver_stock_factor_pro_path(env[3], str(DAY)),
    }
    opened = []
    original = Path.open

    def read(path, *args, **kwargs):
        assert path not in prohibited, "sensor reads technical-factor Parquet"
        opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", read)
    monkeypatch.setattr(
        sensor.R,
        "read_stk_factor_pro_day_factor_shas",
        lambda *a, **k: pytest.fail("sensor invokes physical job validator"),
    )
    assert not evaluate(environment).run_requests and not calls
    assert sum(p.name == "history-plan.json" for p in opened) == 1


@pytest.mark.parametrize("status", ["failed", "planned", "unbound", "wrong_sha"])
def test_new_bad_day_check_cannot_be_hidden_by_old_day_completion(environment, status):
    env, context, _, calls = environment
    env[2]((row(A), row(B)))
    done = env[1].execute_in_process(
        instance=env[0],
        partition_key=str(DAY),
        run_config=config(),
        raise_on_error=False,
    )
    assert done.success
    known = {}
    prior = sensor.R.read_stk_factor_pro_recorded_results(
        context.instance, target_trade_date=DAY, known_pg=known
    )
    _, checks = sensor.R.read_stk_factor_pro_day_publication(
        context.instance, prior=prior, lake_root=env[3], known_pg=known
    )
    old = checks[C.STK_FACTOR_PRO_RAW_ASSET_KEY]
    if status != "planned":
        metadata = dict(old.metadata)
        if status == "wrong_sha":
            metadata["goldenshare/file_sha256"] = dg.TextMetadataValue("0" * 64)
        context.instance.report_runless_asset_event(
            AssetCheckEvaluation(
                asset_key=old.asset_key,
                check_name=old.check_name,
                passed=status != "failed",
                blocking=True,
                partition=str(DAY),
                target_materialization_data=None
                if status == "unbound"
                else old.target_materialization_data,
                metadata=metadata,
            )
        )
    else:
        partitions = dg.StaticPartitionsDefinition(
            [str(DAY)]
        ).subset_with_partition_keys([str(DAY)])
        context.instance.report_dagster_event(
            dg.DagsterEvent(
                event_type_value="ASSET_CHECK_EVALUATION_PLANNED",
                job_name="isolated_day_check",
                event_specific_data=AssetCheckEvaluationPlanned(
                    asset_key=old.asset_key,
                    check_name=old.check_name,
                    partitions_subset=partitions,
                ),
            ),
            run_id="waiting-day-check",
        )
    assert len(evaluate(environment).run_requests) == 1 and calls == [DAY]


def test_completed_day_metadata_reads_are_bounded_and_cached(
    environment, monkeypatch, record_property
):
    env, context, _, _ = environment
    env[2]((row(A), row(B)))
    done = env[1].execute_in_process(
        instance=env[0],
        partition_key=str(DAY),
        run_config=config(),
        raise_on_error=False,
    )
    assert done.success
    known = {}
    prior = sensor.R.read_stk_factor_pro_recorded_results(
        context.instance, target_trade_date=DAY, known_pg=known
    )
    calls = []
    fetch = context.instance.fetch_materializations
    latest = context.instance.event_log_storage.get_latest_asset_check_execution_by_key

    def material(filter, **kwargs):
        calls.append(
            (filter.asset_key.to_user_string(), filter.asset_partitions, kwargs)
        )
        return fetch(filter, **kwargs)

    def checks(keys, *, partition_filter):
        calls.append((partition_filter.key, len(keys)))
        return latest(keys, partition_filter=partition_filter)

    monkeypatch.setattr(context.instance, "fetch_materializations", material)
    monkeypatch.setattr(
        context.instance.event_log_storage,
        "get_latest_asset_check_execution_by_key",
        checks,
    )
    result = sensor.R.read_stk_factor_pro_day_publication(
        context.instance, prior=prior, lake_root=env[3], known_pg=known
    )
    assert result is not None
    assert calls == [
        (C.STK_FACTOR_PRO_RAW_ASSET_KEY, [str(DAY)], {"limit": 1}),
        (C.STK_FACTOR_PRO_SILVER_ASSET_KEY, [str(DAY)], {"limit": 1}),
        (str(DAY), 2),
    ]
    assert (
        sensor.R.read_stk_factor_pro_day_publication(
            context.instance, prior=prior, lake_root=env[3], known_pg=known
        )
        is result
    )
    assert len(calls) == 3
    record_property("day_publication_api_calls", len(calls))


@pytest.mark.parametrize("completed", [False, True], ids=["new_day", "completed_day"])
def test_evaluation_read_costs(
    environment, tmp_path, monkeypatch, record_property, completed
):
    env, context, _, source_calls = environment
    if completed:
        env[2]((row(A), row(B)))
        done = env[1].execute_in_process(
            instance=env[0],
            partition_key=str(DAY),
            run_config=config(),
            raise_on_error=False,
        )
        assert done.success
    apis, batches, statements, duck_queries, opens = [], [], [], [], []
    for name in (
        "fetch_materializations",
        "fetch_observations",
        "get_run_records",
        "get_run_by_id",
    ):
        original = getattr(context.instance, name)

        def counted(*args, _name=name, _original=original, **kwargs):
            apis.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(context.instance, name, counted)
    latest = context.instance.event_log_storage.get_latest_asset_check_execution_by_key

    def checks(keys, *, partition_filter):
        batches.append((partition_filter.key, len(keys)))
        return latest(keys, partition_filter=partition_filter)

    monkeypatch.setattr(
        context.instance.event_log_storage,
        "get_latest_asset_check_execution_by_key",
        checks,
    )
    monkeypatch.setattr(
        context.instance.event_log_storage,
        "get_asset_check_execution_history",
        lambda *a, **k: pytest.fail("sensor scans old checks"),
    )
    original_open = Path.open

    def opened(path, *args, **kwargs):
        assert path not in {
            raw_stk_factor_pro_path(env[3], str(DAY)),
            silver_stock_factor_pro_path(env[3], str(DAY)),
        }
        opens.append(path.name)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)

    class TrackedConnection:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def execute(self, query, *args, **kwargs):
            duck_queries.append(query)
            return self.conn.execute(query, *args, **kwargs)

    @contextmanager
    def connect():
        with connection(tmp_path) as conn:
            yield TrackedConnection(conn)

    monkeypatch.setattr(context.resources.duckdb, "connect", connect)

    def sql(conn, cursor, statement, parameters, execution, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", sql)
    try:
        started = perf_counter()
        result = evaluate(environment)
        elapsed = perf_counter() - started
    finally:
        event.remove(Engine, "before_cursor_execute", sql)
    assert len(result.run_requests) == int(not completed)
    assert source_calls == ([] if completed else [DAY])
    assert apis.count("fetch_materializations") == (8 if completed else 6)
    assert apis.count("get_run_records") == 4  # exact slot, two writers, latest T
    assert batches == [(None, 5), (str(DAY), 8), (str(PREVIOUS), 3)] + (
        [(str(DAY), 2)] if completed else []
    )
    assert opens.count("history-plan.json") == int(completed)
    record_property("evaluation_seconds", round(elapsed, 6))
    record_property("native_api_calls", {name: apis.count(name) for name in set(apis)})
    record_property("latest_check_batches", batches)
    record_property("native_sql_statements", len(statements))
    record_property("duckdb_execute_calls", len(duck_queries))
    record_property(
        "duckdb_read_parquet_statements",
        sum("read_parquet" in query.lower() for query in duck_queries),
    )
    record_property("python_file_open_calls", opens)


@pytest.mark.parametrize(
    "source_case,allowed",
    [
        ("ready", True),
        ("missing", False),
        ("extra", False),
        ("same_count_wrong", False),
        ("wrong_date", False),
        ("source_error", False),
        ("first_missing", True),
        ("first_present", True),
    ],
)
def test_real_http_projected_archived_row_admits_only_today(
    environment, tmp_path, monkeypatch, record_property, source_case, allowed
):
    env, _, _, _ = environment
    input_files(tmp_path, env[3], changed=(), codes=(A,))
    if source_case in ("extra", "same_count_wrong", "first_missing", "first_present"):
        optional = source_case.startswith("first")
        life = [
            (
                A,
                A[:6],
                A,
                "SZSE",
                None,
                "CNY",
                True,
                "L",
                PREVIOUS.replace(year=2010),
                None,
            ),
            (
                B,
                B[:6],
                B,
                "SSE",
                None,
                "CNY",
                True,
                "L" if optional else "D",
                DAY if optional else PREVIOUS.replace(year=2010),
                None if optional else PREVIOUS,
            ),
        ]
        with connection(tmp_path) as conn:
            upstream(conn, env[3], (PREVIOUS, DAY), codes=(A, B), life=life)
    sample = saved_real_rows()[-1]
    assert sample[:2] == (A, "20261016")

    def respond(payload, attempt):
        assert payload["api_name"] == "stk_factor_pro"
        assert payload["fields"] == "ts_code,trade_date"
        assert payload["params"] == {
            "trade_date": "20261016",
            "limit": 10000,
            "offset": 0,
        }
        if source_case == "source_error":
            return Reply(200, b'{"code":-2002,"msg":"source not ready","data":null}')
        rows = [list(sample[:2])]
        if source_case == "missing":
            rows = []
        elif source_case in ("extra", "first_present"):
            rows.append([B, "20261016"])
        elif source_case == "same_count_wrong":
            rows = [[B, "20261016"]]
        elif source_case == "wrong_date":
            rows = [[A, "20261015"]]
        return success(rows)

    with localhost_source(respond) as (url, requests):
        monkeypatch.setattr(
            sensor.ConfigurationLoader,
            "load_configuration",
            lambda: ConfigurationSnapshot("isolated-token", url),
        )
        monkeypatch.setattr(
            sensor, "probe_stk_factor_pro_source", probe_stk_factor_pro_source
        )
        started = perf_counter()
        result = evaluate(environment)
        elapsed = perf_counter() - started
    assert len(requests) == 1 and len(result.run_requests) == int(allowed)
    if allowed:
        assert result.run_requests[0].partition_key == "2026-10-16"
    details = load_sensor_cursor(result.cursor)["details"]
    if source_case == "same_count_wrong":
        assert (details["missing_count"], details["extra_count"]) == (1, 1)
    if source_case.startswith("first"):
        assert details["optional_count"] == 1
        assert details["optional_present_count"] == int(source_case == "first_present")
    assert not list(env[3].glob("raw/tushare/stk_factor_pro/**/*"))
    record_property("projected_source_sensor_seconds", round(elapsed, 6))
