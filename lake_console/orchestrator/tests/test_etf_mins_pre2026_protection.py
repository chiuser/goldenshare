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
from orchestrator.defs.paths import raw_etf_mins_path, silver_etf_mins_path
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


def _write_protected_raw_and_silver(lake_root: Path) -> dict[str, Path]:
    paths = {
        "raw": raw_etf_mins_path(lake_root, "1min", "2026-01-02"),
        "silver": silver_etf_mins_path(lake_root, "1min", "2026-01-02"),
    }
    rows = [minute_row(source_freq="1min", trade_date="2026-01-02")]
    for path in paths.values():
        write_minute_file(path, rows)
    return paths


def test_pre2026_plan_hashes_raw_and_silver_with_row_counts(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    _write_protected_raw_and_silver(lake_root)
    plan = _historical_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        requested_end_date="2025-12-31",
        protect_from_date="2026-01-01",
    )
    assert plan.historical_protection_mode == ETF_MINS_BOOTSTRAP_PROTECTION_2026
    assert plan.protected_file_manifest_hash is not None
    assert len(plan.protected_file_manifest) == 2
    assert {row["layer"] for row in plan.protected_file_manifest} == {
        "raw",
        "silver",
    }
    assert {row["row_count"] for row in plan.protected_file_manifest} == {1}
    assert all(int(row["size_bytes"]) > 0 for row in plan.protected_file_manifest)
    assert all(len(str(row["sha256"])) == 64 for row in plan.protected_file_manifest)


@pytest.mark.parametrize("changed_layer", ["raw", "silver"])
def test_pre2026_apply_fails_when_any_protected_layer_changes(
    tmp_path: Path,
    changed_layer: str,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    protected_paths = _write_protected_raw_and_silver(lake_root)
    plan = _historical_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        requested_end_date="2025-12-31",
        protect_from_date="2026-01-01",
    )
    operation_root = operation_root_for_etf_mins_bootstrap(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    )
    plan_path = operation_root / "plan.json"
    checkpoint_path = operation_root / "raw_checkpoint.json"
    report_path = operation_root / "raw_final_report.json"
    write_etf_mins_bootstrap_plan(plan_path, plan)

    write_minute_file(
        protected_paths[changed_layer],
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


def test_pre2026_plan_records_zero_row_protected_files(tmp_path: Path) -> None:
    lake_root, staging_root = roots(tmp_path)
    write_minute_file(
        raw_etf_mins_path(lake_root, "1min", "2026-01-02"),
        [],
    )
    write_minute_file(
        silver_etf_mins_path(lake_root, "1min", "2026-01-02"),
        [],
    )

    plan = _historical_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        requested_end_date="2025-12-31",
        protect_from_date="2026-01-01",
    )

    assert len(plan.protected_file_manifest) == 2
    assert {row["row_count"] for row in plan.protected_file_manifest} == {0}
