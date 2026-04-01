from __future__ import annotations

from src.operations.specs.registry import DATASET_FRESHNESS_METADATA, JOB_SPEC_REGISTRY, WORKFLOW_SPEC_REGISTRY, get_job_spec
from src.services.sync.registry import SYNC_SERVICE_REGISTRY


def test_job_spec_registry_contains_key_operations() -> None:
    assert "sync_history.stock_basic" in JOB_SPEC_REGISTRY
    assert "sync_daily.daily" in JOB_SPEC_REGISTRY
    assert "backfill_index_series.index_daily" in JOB_SPEC_REGISTRY
    assert "sync_history.ths_index" in JOB_SPEC_REGISTRY
    assert "sync_history.ths_member" in JOB_SPEC_REGISTRY
    assert "sync_daily.ths_daily" in JOB_SPEC_REGISTRY
    assert "sync_daily.dc_index" in JOB_SPEC_REGISTRY
    assert "sync_daily.dc_member" in JOB_SPEC_REGISTRY
    assert "sync_daily.dc_daily" in JOB_SPEC_REGISTRY
    assert "backfill_by_date_range.ths_daily" in JOB_SPEC_REGISTRY
    assert "backfill_by_date_range.dc_index" in JOB_SPEC_REGISTRY
    assert "backfill_by_date_range.dc_daily" in JOB_SPEC_REGISTRY
    assert "backfill_by_trade_date.dc_member" in JOB_SPEC_REGISTRY
    assert "backfill_index_series.index_weekly" in JOB_SPEC_REGISTRY
    assert "maintenance.rebuild_dm" in JOB_SPEC_REGISTRY


def test_trade_cal_and_index_weight_job_specs_expose_expected_params() -> None:
    trade_cal_spec = get_job_spec("sync_history.trade_cal")
    assert trade_cal_spec is not None
    assert [param.key for param in trade_cal_spec.supported_params] == ["start_date", "end_date", "exchange"]

    index_weight_spec = get_job_spec("sync_history.index_weight")
    assert index_weight_spec is not None
    assert [param.key for param in index_weight_spec.supported_params] == ["index_code", "start_date", "end_date"]

    dc_index_spec = get_job_spec("backfill_by_date_range.dc_index")
    assert dc_index_spec is not None
    assert [param.key for param in dc_index_spec.supported_params] == ["start_date", "end_date", "ts_code", "idx_type"]


def test_workflow_specs_reference_existing_job_specs() -> None:
    assert "daily_market_close_sync" in WORKFLOW_SPEC_REGISTRY
    for workflow in WORKFLOW_SPEC_REGISTRY.values():
        for step in workflow.steps:
            assert step.job_key in JOB_SPEC_REGISTRY


def test_all_sync_resources_are_included_in_data_status_metadata() -> None:
    assert set(SYNC_SERVICE_REGISTRY) == set(DATASET_FRESHNESS_METADATA)
