from __future__ import annotations

from src.operations.specs.registry import JOB_SPEC_REGISTRY, WORKFLOW_SPEC_REGISTRY, get_job_spec


def test_job_spec_registry_contains_key_operations() -> None:
    assert "sync_history.stock_basic" in JOB_SPEC_REGISTRY
    assert "sync_daily.daily" in JOB_SPEC_REGISTRY
    assert "backfill_index_series.index_daily" in JOB_SPEC_REGISTRY
    assert "backfill_index_series.index_weekly" in JOB_SPEC_REGISTRY
    assert "maintenance.rebuild_dm" in JOB_SPEC_REGISTRY


def test_trade_cal_and_index_weight_job_specs_expose_expected_params() -> None:
    trade_cal_spec = get_job_spec("sync_history.trade_cal")
    assert trade_cal_spec is not None
    assert [param.key for param in trade_cal_spec.supported_params] == ["start_date", "end_date", "exchange"]

    index_weight_spec = get_job_spec("sync_history.index_weight")
    assert index_weight_spec is not None
    assert [param.key for param in index_weight_spec.supported_params] == ["index_code", "start_date", "end_date"]


def test_workflow_specs_reference_existing_job_specs() -> None:
    assert "daily_market_close_sync" in WORKFLOW_SPEC_REGISTRY
    for workflow in WORKFLOW_SPEC_REGISTRY.values():
        for step in workflow.steps:
            assert step.job_key in JOB_SPEC_REGISTRY
