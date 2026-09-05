from types import SimpleNamespace
from unittest.mock import Mock, call

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import (
    stk_mins_qfq_bootstrap_events as qfq,
)
from orchestrator.defs.bootstrap import (
    stk_mins_qfq_derived_bootstrap_events as derived,
)
from orchestrator.defs.bootstrap import (
    stk_mins_qfq_macd_kdj_baseline_events as macd,
)
from orchestrator.defs.bootstrap import (
    stk_mins_silver_bootstrap_events as silver,
)
from orchestrator.defs.bootstrap.stk_mins_history_check_events import (
    count_succeeded_asset_check_executions,
)


def _record(status):
    return SimpleNamespace(status=SimpleNamespace(value=status))


def _readonly_instance(records):
    storage = Mock(spec_set=["get_asset_check_execution_history"])
    storage.get_asset_check_execution_history.return_value = records
    instance = Mock(
        spec_set=[
            "event_log_storage",
            "get_materialized_partitions",
            "get_dynamic_partitions",
        ]
    )
    instance.event_log_storage = storage
    instance.get_materialized_partitions.return_value = {"2026-09-04"}
    instance.get_dynamic_partitions.return_value = ["2026-09-04"]
    return instance


@pytest.mark.parametrize(
    ("statuses", "expected"),
    (
        ((), 0),
        (("FAILED", "PLANNED", "SKIPPED", "EXECUTION_FAILED"), 0),
        (("SUCCEEDED", "FAILED", "SUCCEEDED", "succeeded"), 2),
        (("SUCCEEDED", "FAILED") * 25000, 25000),
    ),
)
def test_count_preserves_status_filter_and_single_bounded_read(statuses, expected):
    instance = _readonly_instance([_record(status) for status in statuses])
    key = dg.AssetCheckKey(dg.AssetKey("silver_stock_mins_1m"), "contract_check")
    assert count_succeeded_asset_check_executions(instance, key) == expected
    instance.event_log_storage.get_asset_check_execution_history.assert_called_once_with(
        key, limit=50000
    )


def test_count_propagates_read_error_without_retry_or_false_zero():
    instance = _readonly_instance([])
    failure = RuntimeError("history unavailable")
    instance.event_log_storage.get_asset_check_execution_history.side_effect = failure
    key = dg.AssetCheckKey(dg.AssetKey("silver_stock_mins_1m"), "contract_check")
    with pytest.raises(RuntimeError) as exc:
        count_succeeded_asset_check_executions(instance, key)
    assert exc.value is failure
    instance.event_log_storage.get_asset_check_execution_history.assert_called_once()


def _assert_check_counts(instance, report, groups):
    expected_keys = [
        dg.AssetCheckKey(asset_key, check_name)
        for asset_keys, check_names in groups
        for asset_key in asset_keys
        for check_name in check_names
    ]
    assert report.check_success_counts == {
        f"{key.asset_key.to_user_string()}:{key.name}": 2 for key in expected_keys
    }
    assert (
        instance.event_log_storage.get_asset_check_execution_history.call_args_list
        == [call(key, limit=50000) for key in expected_keys]
    )


def test_silver_final_audit_uses_retained_count_helper(tmp_path):
    instance = _readonly_instance(
        [_record("SUCCEEDED"), _record("FAILED"), _record("SUCCEEDED")]
    )
    report = silver.audit_stk_mins_silver_final_state(
        instance=instance, lake_root=tmp_path
    )
    assert report.selected_partition_count == 0
    _assert_check_counts(
        instance,
        report,
        [
            (
                tuple(silver.SILVER_STK_MINS_ASSET_KEYS.values()),
                silver.SILVER_STK_MINS_CHECKS,
            )
        ],
    )
    assert list(tmp_path.iterdir()) == []


def _history_plan():
    return SimpleNamespace(
        selected_partition_keys=("2026-09-04",),
        selected_freqs=(1,),
        selected_target_freqs=(90,),
        selected_years=(2026,),
        batches=(),
        planned_target_file_count=1,
        existing_target_file_count=0,
        missing_input_count=0,
        missing_input_samples=(),
        planned_source_file_count=1,
        planned_source_row_count=4,
        planned_source_stock_day_count=1,
        planned_target_row_count=2,
    )


def test_qfq_event_plan_uses_retained_count_helper(tmp_path, monkeypatch):
    plan = _history_plan()
    planner = Mock(return_value=plan)
    monkeypatch.setattr(qfq, "plan_stk_mins_qfq_history", planner)
    instance = _readonly_instance(
        [_record("SUCCEEDED"), _record("FAILED"), _record("SUCCEEDED")]
    )
    report = qfq.plan_stk_mins_qfq_bootstrap_events(
        instance=instance, lake_root=tmp_path, registered_partition_keys=("2026-09-04",)
    )
    assert report.selected_partition_keys == ("2026-09-04",)
    assert report.materialized_partition_counts == {1: 1}
    _assert_check_counts(
        instance,
        report,
        [((qfq.GOLD_STK_MINS_QFQ_ASSET_KEYS[1],), qfq.GOLD_STK_MINS_QFQ_CHECKS)],
    )
    planner.assert_called_once()


@pytest.mark.parametrize("include_counts", (True, False))
@pytest.mark.parametrize("family", ("derived", "macd"))
def test_optional_event_count_preserves_full_and_quick_modes(
    tmp_path, monkeypatch, family, include_counts
):
    plan = _history_plan()
    instance = _readonly_instance(
        [_record("SUCCEEDED"), _record("FAILED"), _record("SUCCEEDED")]
    )
    if family == "derived":
        module = derived
        planner_name = "plan_stk_mins_qfq_derived_history"
        event_planner = derived.plan_stk_mins_qfq_derived_bootstrap_events
        groups = [
            (
                (derived.GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS[90],),
                derived.GOLD_STK_MINS_QFQ_DERIVED_CHECKS,
            )
        ]
    else:
        module = macd
        planner_name = "plan_stk_mins_qfq_macd_kdj_history"
        event_planner = macd.plan_stk_mins_qfq_macd_kdj_baseline_events
        groups = [
            (
                (macd.GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_KEYS[1],),
                macd.GOLD_STK_MINS_QFQ_MACD_KDJ_CHECKS,
            ),
            (
                (macd.GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_ASSET_KEYS[1],),
                macd.GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECKS,
            ),
        ]
    planner = Mock(return_value=plan)
    monkeypatch.setattr(module, planner_name, planner)
    report = event_planner(
        instance=instance,
        lake_root=tmp_path,
        registered_partition_keys=("2026-09-04",),
        include_check_success_counts=include_counts,
    )
    assert report.selected_partition_keys == ("2026-09-04",)
    _assert_check_counts(instance, report, groups if include_counts else [])
    planner.assert_called_once()
