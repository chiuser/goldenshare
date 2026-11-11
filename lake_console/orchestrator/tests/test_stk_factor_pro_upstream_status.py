"""Native temporary records for step-five bounded upstream status reading.

The producer-shaped event fixture is shared with the actual update-job replay.
Injected bad records are deliberate counterexamples, never formal DG events.
"""

from time import perf_counter

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationPlanned,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.event_api import PartitionKeyFilter
from sqlalchemy import event
from sqlalchemy.engine import Engine

from orchestrator.defs.asset_guards import stk_factor_pro_readiness as R
from orchestrator.defs.assets import stk_factor_pro as asset
from orchestrator.defs.sensors import readiness as upstream
from tests.stk_factor_pro_test_support import row
from tests.test_stk_factor_pro_batch5_job_integration import seed_upstream_events
from tests.test_stk_factor_pro_dagster_events import _isolated_instance
from tests.test_stk_factor_pro_jobs import (
    DAY,
    PREVIOUS,
    A,
    B,
    config,
    input_files,
    isolated_update_environment,
)


@pytest.fixture
def native(tmp_path):
    with _isolated_instance(tmp_path) as instance:
        seed_upstream_events(instance)
        yield instance


def read(instance, known=None):
    return R.read_stk_factor_pro_upstream_status(
        instance,
        target_trade_date=DAY,
        previous_trade_date=PREVIOUS,
        known_pg={} if known is None else known,
    )


def latest(instance, spec, partition):
    key = dg.AssetCheckKey(spec.asset_key, spec.blocking_check_names[0])
    return instance.event_log_storage.get_latest_asset_check_execution_by_key(
        (key,), partition_filter=PartitionKeyFilter(key=partition)
    )[key].event.dagster_event.event_specific_data


def test_exact_partition_groups_latest_only_and_zero_repeat(
    native, monkeypatch, record_property
):
    calls, batches = [], []
    fetch = native.fetch_materializations
    checks = native.event_log_storage.get_latest_asset_check_execution_by_key

    def material(filter, **kwargs):
        calls.append(
            (
                filter.asset_key.to_user_string(),
                filter.asset_partitions,
                kwargs["limit"],
            )
        )
        return fetch(filter, **kwargs)

    def batch(keys, *, partition_filter):
        batches.append((partition_filter.key, len(keys)))
        return checks(keys, partition_filter=partition_filter)

    monkeypatch.setattr(native, "fetch_materializations", material)
    monkeypatch.setattr(
        native.event_log_storage, "get_latest_asset_check_execution_by_key", batch
    )
    monkeypatch.setattr(
        native.event_log_storage,
        "get_asset_check_execution_history",
        lambda *a, **k: pytest.fail("deep check history"),
    )
    known = {}
    statements = []

    def executed(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", executed)
    try:
        started = perf_counter()
        result = read(native, known)
        elapsed = perf_counter() - started
        count = len(statements)
        assert result.ready and read(native, known) is result
        assert len(statements) == count
    finally:
        event.remove(Engine, "before_cursor_execute", executed)
    record_property("upstream_seconds", round(elapsed, 6))
    record_property("upstream_sql_statements", count)
    assert calls == [
        ("raw_tushare_stock_basic", None, 1),
        ("silver_stock_lifecycle", None, 1),
        ("raw_tushare_adj_factor", [str(DAY)], 1),
        ("raw_tushare_suspend_d", [str(DAY)], 1),
        ("silver_stock_suspend_daily", [str(DAY)], 1),
        ("raw_tushare_adj_factor", [str(PREVIOUS)], 1),
    ]
    assert batches == [(None, 5), (str(DAY), 8), (str(PREVIOUS), 3)]
    assert len(result.statuses) == 6
    assert known[("suspend_readiness", DAY)].ready
    assert len(known[("suspend_readiness", DAY)].statuses) == 2


@pytest.mark.parametrize("day", [DAY, PREVIOUS], ids=["T", "P"])
@pytest.mark.parametrize(
    "bad", ["failed", "unbound", "wrong_run", "wrong_timestamp", "nonblocking"]
)
def test_new_bad_check_cannot_reuse_older_success_or_other_partition(native, day, bad):
    spec = upstream.RAW_ADJ_FACTOR_READINESS_SPEC
    evaluation = latest(native, spec, str(day))
    target = evaluation.target_materialization_data
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=target.storage_id,
        run_id="wrong-producer" if bad == "wrong_run" else target.run_id,
        timestamp=target.timestamp + 1
        if bad == "wrong_timestamp"
        else target.timestamp,
    )
    native.report_runless_asset_event(
        AssetCheckEvaluation(
            asset_key=spec.asset_key,
            check_name=evaluation.check_name,
            passed=bad != "failed",
            blocking=bad != "nonblocking",
            partition=str(day),
            target_materialization_data=None if bad == "unbound" else target,
        )
    )
    result = read(native)
    assert not result.ready
    by_day = {
        s.partition_key: s
        for s in result.statuses
        if s.asset_key == "raw_tushare_adj_factor"
    }
    assert not by_day[str(day)].ready
    assert by_day[str(PREVIOUS if day == DAY else DAY)].ready


def test_planned_latest_check_does_not_fall_back_to_green(native):
    spec = upstream.RAW_STOCK_BASIC_READINESS_SPEC
    native.report_dagster_event(
        dg.DagsterEvent(
            event_type_value="ASSET_CHECK_EVALUATION_PLANNED",
            job_name="isolated_check",
            event_specific_data=AssetCheckEvaluationPlanned(
                asset_key=spec.asset_key, check_name=spec.blocking_check_names[0]
            ),
        ),
        run_id="waiting-check",
    )
    result = read(native)
    assert not result.ready and not result.statuses[0].ready


def test_new_materialization_requires_its_own_checks_then_normal_update_passes(native):
    spec = upstream.RAW_ADJ_FACTOR_READINESS_SPEC
    native.report_runless_asset_event(
        dg.AssetMaterialization(spec.asset_key, partition=str(DAY))
    )
    assert not read(native).ready
    # A normal complete producer update is accepted; no cached prior assessment
    # is reused across tasks, and P still has its independently bound checks.
    seed_upstream_events(native)
    assert read(native).ready


def test_unpartitioned_inputs_use_T_freshness_but_partitioned_inputs_keep_original_rule(
    native,
):
    result = R.read_stk_factor_pro_upstream_status(
        native,
        target_trade_date=DAY.replace(year=2099),
        previous_trade_date=PREVIOUS,
        known_pg={},
    )
    assert all(
        not s.freshness_passed for s in result.statuses if s.partition_key is None
    )
    assert next(
        s for s in result.statuses if s.partition_key == str(PREVIOUS)
    ).freshness_passed


def test_empty_instance_is_not_ready_and_no_history_scan(tmp_path, monkeypatch):
    with _isolated_instance(tmp_path) as instance:
        monkeypatch.setattr(
            instance.event_log_storage,
            "get_asset_check_execution_history",
            lambda *a, **k: pytest.fail("deep check history"),
        )
        result = read(instance)
        assert not result.ready and all(not s.materialized for s in result.statuses)


def test_actual_job_reuses_T_suspend_status_without_generic_deep_reads(
    tmp_path, monkeypatch
):
    with isolated_update_environment(
        tmp_path, monkeypatch, substitute_upstream=False
    ) as env:
        instance, job, source, lake, _, _ = env
        input_files(tmp_path, lake, changed=())
        seed_upstream_events(instance)
        source((row(A), row(B)))
        monkeypatch.setattr(
            asset,
            "suspend_d_ready_for_trade_date",
            lambda *a: pytest.fail("T suspend read twice"),
        )
        monkeypatch.setattr(
            instance.event_log_storage,
            "get_asset_check_execution_history",
            lambda *a, **k: pytest.fail("deep check history"),
        )
        result = job.execute_in_process(
            instance=instance,
            partition_key=str(DAY),
            run_config=config(),
            raise_on_error=False,
        )
        assert result.success, result.failure_data_for_node("stk_factor_pro")
        assert len(result.get_asset_materialization_events()) == 2
