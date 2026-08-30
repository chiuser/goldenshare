from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap.etf_mins_bootstrap import (
    ETF_MINS_BOOTSTRAP_PROTECTION_2026,
    EtfMinsBootstrapError,
    apply_etf_mins_bootstrap_raw,
    build_etf_mins_bootstrap_plan,
    operation_root_for_etf_mins_bootstrap,
    write_etf_mins_bootstrap_plan,
)
from orchestrator.defs.paths import raw_etf_mins_path
from tests.etf_mins_bootstrap_support import (
    FakeProdPostgres,
    TestDuckDBResource,
    coverages,
    minute_row,
    roots,
    write_basic_pair,
    write_minute_file,
)


def _historical_plan(
    *,
    lake_root: Path,
    staging_root: Path,
    requested_end_date: str,
    protect_from_date: str | None,
):  # type: ignore[no-untyped-def]
    reference, targets = write_basic_pair(lake_root=lake_root)
    return build_etf_mins_bootstrap_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        operation_id="pre2026",
        requested_start_date="2025-12-31",
        requested_end_date=requested_end_date,
        created_at=datetime(2026, 9, 30, 8, tzinfo=UTC),
        basic_reference=reference,  # type: ignore[arg-type]
        requestable_targets=targets,
        calendar_trade_dates=("2025-12-31", "2026-01-01"),
        watermark_coverages=coverages((requested_end_date,)),
        free_bytes=10**12,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        protect_from_date=protect_from_date,
    )


def test_pre2026_plan_requires_the_fixed_protection_cutoff(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    with pytest.raises(EtfMinsBootstrapError, match="protection_required"):
        _historical_plan(
            lake_root=lake_root,
            staging_root=staging_root,
            requested_end_date="2025-12-31",
            protect_from_date=None,
        )
    with pytest.raises(EtfMinsBootstrapError, match="protect_from_date_invalid"):
        _historical_plan(
            lake_root=lake_root,
            staging_root=staging_root,
            requested_end_date="2025-12-31",
            protect_from_date="2026-02-01",
        )
    with pytest.raises(EtfMinsBootstrapError, match="protected_range_overlap"):
        _historical_plan(
            lake_root=lake_root,
            staging_root=staging_root,
            requested_end_date="2026-01-01",
            protect_from_date="2026-01-01",
        )


def test_pre2026_plan_hashes_protected_files_and_apply_fails_on_any_change(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    protected_path = raw_etf_mins_path(lake_root, "1min", "2026-01-02")
    write_minute_file(
        protected_path,
        [minute_row(source_freq="1min", trade_date="2026-01-02")],
    )
    plan = _historical_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        requested_end_date="2025-12-31",
        protect_from_date="2026-01-01",
    )
    assert plan.historical_protection_mode == ETF_MINS_BOOTSTRAP_PROTECTION_2026
    assert plan.protected_file_manifest_hash is not None
    assert len(plan.protected_file_manifest) == 1
    operation_root = operation_root_for_etf_mins_bootstrap(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    )
    plan_path = operation_root / "plan.json"
    checkpoint_path = operation_root / "raw_checkpoint.json"
    report_path = operation_root / "raw_final_report.json"
    write_etf_mins_bootstrap_plan(plan_path, plan)

    write_minute_file(
        protected_path,
        [
            minute_row(
                source_freq="1min",
                trade_date="2026-01-02",
                close=11.5,
            )
        ],
    )
    with pytest.raises(EtfMinsBootstrapError, match="protected_files_changed"):
        apply_etf_mins_bootstrap_raw(
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
            plan_path=plan_path,
            checkpoint_path=checkpoint_path,
            raw_final_report_path=report_path,
            confirm_raw_lake_write=True,
        )
    assert not checkpoint_path.exists()
    assert not report_path.exists()
