from __future__ import annotations

from src.operations.specs.registry import DATASET_FRESHNESS_METADATA, JOB_SPEC_REGISTRY, WORKFLOW_SPEC_REGISTRY, get_job_spec
from src.services.sync.registry import SYNC_SERVICE_REGISTRY


def test_job_spec_registry_contains_key_operations() -> None:
    assert "sync_history.stock_basic" in JOB_SPEC_REGISTRY
    assert "sync_history.hk_basic" in JOB_SPEC_REGISTRY
    assert "sync_history.us_basic" in JOB_SPEC_REGISTRY
    assert "sync_daily.daily" in JOB_SPEC_REGISTRY
    assert "backfill_index_series.index_daily" in JOB_SPEC_REGISTRY
    assert "sync_history.ths_index" in JOB_SPEC_REGISTRY
    assert "sync_history.ths_member" in JOB_SPEC_REGISTRY
    assert "sync_daily.ths_daily" in JOB_SPEC_REGISTRY
    assert "sync_daily.dc_index" in JOB_SPEC_REGISTRY
    assert "sync_daily.dc_member" in JOB_SPEC_REGISTRY
    assert "sync_daily.dc_daily" in JOB_SPEC_REGISTRY
    assert "sync_daily.ths_hot" in JOB_SPEC_REGISTRY
    assert "sync_daily.dc_hot" in JOB_SPEC_REGISTRY
    assert "sync_daily.kpl_list" in JOB_SPEC_REGISTRY
    assert "sync_daily.kpl_concept_cons" in JOB_SPEC_REGISTRY
    assert "backfill_by_date_range.ths_daily" in JOB_SPEC_REGISTRY
    assert "backfill_by_date_range.dc_index" in JOB_SPEC_REGISTRY
    assert "backfill_by_date_range.dc_daily" in JOB_SPEC_REGISTRY
    assert "backfill_by_date_range.kpl_list" in JOB_SPEC_REGISTRY
    assert "backfill_by_trade_date.dc_member" in JOB_SPEC_REGISTRY
    assert "backfill_by_trade_date.top_list" in JOB_SPEC_REGISTRY
    assert "backfill_by_trade_date.block_trade" in JOB_SPEC_REGISTRY
    assert "backfill_by_trade_date.ths_hot" in JOB_SPEC_REGISTRY
    assert "backfill_by_trade_date.dc_hot" in JOB_SPEC_REGISTRY
    assert "backfill_by_trade_date.kpl_concept_cons" in JOB_SPEC_REGISTRY
    assert "backfill_index_series.index_weekly" in JOB_SPEC_REGISTRY
    assert "maintenance.rebuild_dm" in JOB_SPEC_REGISTRY


def test_trade_cal_and_index_weight_job_specs_expose_expected_params() -> None:
    hk_basic_spec = get_job_spec("sync_history.hk_basic")
    assert hk_basic_spec is not None
    assert [param.key for param in hk_basic_spec.supported_params] == ["ts_code", "list_status"]
    assert next(param for param in hk_basic_spec.supported_params if param.key == "list_status").options == ("L", "D", "P")

    us_basic_spec = get_job_spec("sync_history.us_basic")
    assert us_basic_spec is not None
    assert [param.key for param in us_basic_spec.supported_params] == ["ts_code", "classify"]
    assert next(param for param in us_basic_spec.supported_params if param.key == "classify").options == ("ADR", "GDR", "EQ")

    trade_cal_spec = get_job_spec("sync_history.trade_cal")
    assert trade_cal_spec is not None
    assert [param.key for param in trade_cal_spec.supported_params] == ["start_date", "end_date", "exchange"]

    index_weight_spec = get_job_spec("sync_history.index_weight")
    assert index_weight_spec is not None
    assert [param.key for param in index_weight_spec.supported_params] == ["index_code", "start_date", "end_date"]

    dc_index_spec = get_job_spec("backfill_by_date_range.dc_index")
    assert dc_index_spec is not None
    assert [param.key for param in dc_index_spec.supported_params] == ["start_date", "end_date", "ts_code", "idx_type"]

    dc_hot_daily_spec = get_job_spec("sync_daily.dc_hot")
    assert dc_hot_daily_spec is not None
    assert [param.key for param in dc_hot_daily_spec.supported_params] == ["trade_date", "ts_code", "market", "hot_type", "is_new"]

    dc_hot_backfill_spec = get_job_spec("backfill_by_trade_date.dc_hot")
    assert dc_hot_backfill_spec is not None
    assert [param.key for param in dc_hot_backfill_spec.supported_params] == [
        "start_date",
        "end_date",
        "ts_code",
        "market",
        "hot_type",
        "is_new",
        "offset",
        "limit",
    ]

    market_param = next(param for param in dc_hot_backfill_spec.supported_params if param.key == "market")
    assert market_param.options == ("A股市场", "ETF基金", "港股市场", "美股市场")
    assert market_param.multi_value is True

    hot_type_param = next(param for param in dc_hot_backfill_spec.supported_params if param.key == "hot_type")
    assert hot_type_param.options == ("人气榜", "飙升榜")
    assert hot_type_param.multi_value is True


def test_ths_reference_sync_history_specs_are_schedulable() -> None:
    ths_index_spec = get_job_spec("sync_history.ths_index")
    assert ths_index_spec is not None
    assert ths_index_spec.supports_schedule is True

    ths_member_spec = get_job_spec("sync_history.ths_member")
    assert ths_member_spec is not None
    assert ths_member_spec.supports_schedule is True


def test_workflow_specs_reference_existing_job_specs() -> None:
    assert "daily_market_close_sync" in WORKFLOW_SPEC_REGISTRY
    for workflow in WORKFLOW_SPEC_REGISTRY.values():
        for step in workflow.steps:
            assert step.job_key in JOB_SPEC_REGISTRY


def test_all_sync_resources_are_included_in_data_status_metadata() -> None:
    assert set(SYNC_SERVICE_REGISTRY) == set(DATASET_FRESHNESS_METADATA)
