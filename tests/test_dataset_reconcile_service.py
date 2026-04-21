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
    assert len(report.daily_diffs) == 1
    assert report.daily_diffs[0].trade_date == date(2026, 4, 2)
    assert report.daily_diffs[0].diff == 2


def test_dataset_reconcile_service_rejects_unknown_dataset(mocker) -> None:
    service = DatasetReconcileService()
    session = mocker.Mock()

    with pytest.raises(ValueError, match="not supported"):
        service.run(session, dataset_key="unknown_dataset")


def test_dataset_reconcile_service_supports_daily_basic_dataset() -> None:
    assert "daily_basic" in DatasetReconcileService.SUPPORTED_DATASETS


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
