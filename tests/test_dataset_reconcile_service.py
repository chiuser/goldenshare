from __future__ import annotations

from datetime import date

import pytest

from src.ops.services.operations_dataset_reconcile_service import DatasetReconcileService


def test_dataset_reconcile_service_builds_diff_report(mocker) -> None:
    service = DatasetReconcileService()
    session = mocker.Mock()
    mocker.patch.object(service, "_count_rows", side_effect=[10, 8])
    mocker.patch.object(
        service,
        "_load_daily_counts",
        side_effect=[
            {date(2026, 4, 1): 4, date(2026, 4, 2): 6},
            {date(2026, 4, 1): 4, date(2026, 4, 2): 4},
        ],
    )

    report = service.run(
        session,
        dataset_key="trade_cal",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 2),
        sample_limit=10,
    )

    assert report.dataset_key == "trade_cal"
    assert report.raw_rows == 10
    assert report.serving_rows == 8
    assert report.abs_diff == 2
    assert report.reconcile_mode == "daily"
    assert len(report.daily_diffs) == 1
    assert report.daily_diffs[0].trade_date == date(2026, 4, 2)
    assert report.daily_diffs[0].diff == 2


def test_dataset_reconcile_service_rejects_unknown_dataset(mocker) -> None:
    service = DatasetReconcileService()
    session = mocker.Mock()

    with pytest.raises(ValueError, match="not supported"):
        service.run(session, dataset_key="unknown_dataset")


def test_dataset_reconcile_service_supports_daily_basic_dataset() -> None:
    assert "adj_factor" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "daily" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "daily_basic" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "cyq_perf" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "dc_index" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "fund_daily" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "index_daily" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "index_daily_basic" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "limit_list_d" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "limit_list_ths" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "suspend_d" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "limit_step" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "limit_cpt_list" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "moneyflow" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "moneyflow_ths" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "moneyflow_dc" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "moneyflow_cnt_ths" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "moneyflow_ind_ths" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "moneyflow_ind_dc" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "moneyflow_mkt_dc" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "top_list" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "block_trade" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "stock_st" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "stk_nineturn" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "dc_member" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "ths_member" in DatasetReconcileService.SUPPORTED_DATASETS
    assert DatasetReconcileService.SUPPORTED_DATASETS["ths_member"].mode == "snapshot"
    assert "ths_daily" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "dc_daily" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "ths_hot" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "dc_hot" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "stk_period_bar_week" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "stk_period_bar_month" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "stk_period_bar_adj_week" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "stk_period_bar_adj_month" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "fund_adj" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "index_basic" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "etf_basic" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "etf_index" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "hk_basic" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "us_basic" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "ths_index" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "kpl_list" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "kpl_concept_cons" in DatasetReconcileService.SUPPORTED_DATASETS
    assert "broker_recommend" in DatasetReconcileService.SUPPORTED_DATASETS
    assert DatasetReconcileService.SUPPORTED_DATASETS["broker_recommend"].mode == "snapshot"


def test_dataset_reconcile_service_rejects_invalid_date_range(mocker) -> None:
    service = DatasetReconcileService()
    session = mocker.Mock()

    with pytest.raises(ValueError, match="start_date must be <= end_date"):
        service.run(
            session,
            dataset_key="trade_cal",
            start_date=date(2026, 4, 3),
            end_date=date(2026, 4, 1),
        )


def test_dataset_reconcile_service_builds_snapshot_diff_report(mocker) -> None:
    service = DatasetReconcileService()
    session = mocker.Mock()
    mocker.patch.object(service, "_count_rows", side_effect=[120, 118])
    mocker.patch.object(service, "_count_distinct_keys", side_effect=[120, 118])
    mocker.patch.object(
        service,
        "_load_key_diff_samples",
        return_value=["raw_only:000001.SZ", "serving_only:000002.SZ"],
    )

    report = service.run(
        session,
        dataset_key="index_basic",
        sample_limit=10,
    )

    assert report.dataset_key == "index_basic"
    assert report.reconcile_mode == "snapshot"
    assert report.raw_rows == 120
    assert report.serving_rows == 118
    assert report.abs_diff == 2
    assert report.raw_distinct_keys == 120
    assert report.serving_distinct_keys == 118
    assert report.distinct_abs_diff == 2
    assert report.daily_diffs == []
    assert report.snapshot_key_diffs == ["raw_only:000001.SZ", "serving_only:000002.SZ"]
