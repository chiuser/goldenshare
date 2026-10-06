"""Current partition contracts ignore historical proof paths and content versions."""

from types import SimpleNamespace as NS

import dagster as dg
import pytest

from orchestrator.defs import stock_monthly_update_state as monthly_state
from orchestrator.defs import stock_weekly_update_state as weekly_state
from orchestrator.defs.bootstrap.stock_weekly_candidates import partition_path
from orchestrator.defs.paths import raw_stock_monthly_path
from orchestrator.defs.run_contracts.stock_monthly import StockMonthlySource
from orchestrator.defs.run_contracts.stock_weekly import StockWeeklySource
from orchestrator.defs.stock_monthly_update_state import monthly_period_status
from orchestrator.defs.stock_period_checks import verify_period_materialization


def record(path, partition, rows=7, **metadata):
    return NS(
        asset_materialization=dg.AssetMaterialization(
            asset_key="current_partition",
            partition=partition,
            metadata={"dagster/uri": str(path), "dagster/row_count": rows, **metadata},
        )
    )


def test_old_proof_paths_do_not_freeze_later_legitimate_corrections(tmp_path):
    path = tmp_path / "data.parquet"
    r = record(
        path,
        "2026-10-02",
        **{
            "goldenshare/weekly_delivery": {
                "audit_path": "/deleted/reports/old.json",
                "sha256": "old-version",
            }
        },
    )
    assert verify_period_materialization(r, "2026-10-02", path, rows=7) == 7
    corrected = record(path, "2026-10-02", rows=9)
    assert verify_period_materialization(corrected, "2026-10-02", path, rows=9) == 9


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "partition",
        "path",
        "rows",
        "negative",
        "missing_rows",
        "boolean_rows",
    ],
)
def test_invalid_current_receipt_is_rejected(tmp_path, mutation):
    path = tmp_path / "data.parquet"
    r = record(path, "2026-10-02")
    if mutation == "missing":
        r = None
    elif mutation == "partition":
        r = record(path, "2026-09-25")
    elif mutation == "path":
        r = record(tmp_path / "other.parquet", "2026-10-02")
    elif mutation == "rows":
        r = record(path, "2026-10-02", rows=8)
    elif mutation == "negative":
        r = record(path, "2026-10-02", rows=-1)
    elif mutation == "missing_rows":
        r = NS(
            asset_materialization=dg.AssetMaterialization(
                asset_key="current_partition",
                partition="2026-10-02",
                metadata={"dagster/uri": str(path)},
            )
        )
    else:
        r = record(path, "2026-10-02", rows=True)
    with pytest.raises(ValueError):
        verify_period_materialization(r, "2026-10-02", path, rows=7)


@pytest.mark.parametrize("frequency", ["week", "month"])
def test_period_status_requires_file_and_bound_checks_only(
    tmp_path, monkeypatch, frequency
):
    if frequency == "week":
        source, period = StockWeeklySource.PRIMARY_UNADJUSTED, "2026-10-02"
        path = partition_path(tmp_path, source, period)
        status = weekly_state.weekly_period_status
    else:
        source, period = StockMonthlySource.PRIMARY_UNADJUSTED, "2026-09"
        path = raw_stock_monthly_path(tmp_path, source, period)
        status = monthly_period_status
    r = record(
        path,
        period,
        **{
            f"goldenshare/{'weekly' if frequency == 'week' else 'monthly'}_delivery": {
                "audit_path": "/deleted/reports/history.json"
            }
        },
    )
    binding = [r, True]
    monkeypatch.setattr(
        weekly_state if frequency == "week" else monthly_state,
        "weekly_event_binding",
        lambda *a: tuple(binding),
    )
    assert status(object(), tmp_path, source, period) == "formal_file_missing"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not read by scheduling")
    assert status(object(), tmp_path, source, period) == "ready"
    binding[1] = False
    assert status(object(), tmp_path, source, period) == "checks_failed_or_stale"
    binding[:] = [None, False]
    assert status(object(), tmp_path, source, period) == "orphan_file"
