from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap import etf_mins_bootstrap as bootstrap
from orchestrator.defs.bootstrap.etf_mins_bootstrap import (
    EtfMinsBootstrapError,
    apply_etf_mins_bootstrap_raw,
    build_etf_mins_bootstrap_plan,
    operation_root_for_etf_mins_bootstrap,
    write_etf_mins_bootstrap_plan,
)
from orchestrator.defs.bootstrap.etf_mins_raw_observation import (
    ETF_MINS_RAW_OBSERVATION_REASON_CODES,
    observe_etf_mins_raw,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import raw_etf_mins_path, silver_trade_calendar_path
from orchestrator.defs.run_contracts.etf_mins import ETF_MINS_SOURCE_FREQS
from tests.etf_mins_bootstrap_support import (
    FakeProdPostgres,
    TestDuckDBResource,
    coverages,
    install_fake_prod_source,
    minute_row,
    roots,
    write_basic_pair,
)


def _write_trade_calendar(lake_root: Path, trade_dates: Sequence[str]) -> None:
    target = silver_trade_calendar_path(lake_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE calendar(exchange VARCHAR, trade_date DATE, is_open BOOLEAN)"
        )
        connection.executemany(
            "INSERT INTO calendar VALUES ('SSE', CAST(? AS DATE), true)",
            [(trade_date,) for trade_date in trade_dates],
        )
        connection.execute(copy_query_to_parquet("SELECT * FROM calendar", target))


def _complete_tiny_raw_operation(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[tuple[object, ...]],
    operation_id: str,
    trade_dates: tuple[str, ...] = ("2026-01-02",),
) -> tuple[Path, Path, Path]:
    lake_root, staging_root = roots(tmp_path)
    reference, targets = write_basic_pair(lake_root=lake_root)
    _write_trade_calendar(lake_root, trade_dates)
    plan = build_etf_mins_bootstrap_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        operation_id=operation_id,
        requested_start_date=trade_dates[0],
        requested_end_date=trade_dates[-1],
        created_at=datetime(2026, 9, 30, 8, tzinfo=UTC),
        basic_reference=reference,  # type: ignore[arg-type]
        requestable_targets=targets,
        calendar_trade_dates=trade_dates,
        watermark_coverages=coverages(trade_dates),
        free_bytes=10**12,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
    )
    operation_root = operation_root_for_etf_mins_bootstrap(
        staging_root=staging_root,
        operation_id=operation_id,
    )
    plan_path = operation_root / "plan.json"
    checkpoint_path = operation_root / "raw_checkpoint.json"
    report_path = operation_root / "raw_final_report.json"
    write_etf_mins_bootstrap_plan(plan_path, plan)
    install_fake_prod_source(bootstrap, monkeypatch, rows=rows)
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
    return lake_root, operation_root, report_path


def test_raw_observation_profiles_only_tiny_local_raw_and_remains_unclassified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade_date = "2026-01-02"
    lake_root, operation_root, report_path = _complete_tiny_raw_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        rows=[
            minute_row(source_freq=source_freq, trade_date=trade_date)
            for source_freq in ETF_MINS_SOURCE_FREQS
        ],
        operation_id="raw-observe-local",
    )
    output_dir = operation_root / "raw-observe"
    result = observe_etf_mins_raw(
        lake_root=lake_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        raw_bootstrap_report_path=report_path,
        output_dir=output_dir,
    )

    assert result.scanned_file_count == 5
    assert result.scanned_row_count == 5
    assert result.raw_scan_query_count == 2
    assert result.issue_row_count == 0
    assert result.peak_temp_dir_size_bytes >= 0
    assert {path.name for path in output_dir.iterdir()} == {
        "raw_file_manifest.parquet",
        "raw_code_day_freq_profile.parquet",
        "raw_grid_profile.parquet",
        "raw_domain_profile.parquet",
        "raw_issue_details.parquet",
        "raw_partition_observation_manifest.parquet",
        "raw_observation_summary.json",
        "proposed_policy.json",
    }
    summary = json.loads(result.raw_observation_summary_path.read_text())
    proposal = json.loads(result.proposed_policy_path.read_text())
    assert summary["partition_state"] == "unclassified"
    assert summary["observed_distributions"]["partition_count"] == 5
    assert "decision" not in summary
    assert "silver_eligible" not in summary
    assert proposal["effective"] is False
    assert proposal["requires_admin_approval"] is True
    assert "decision" not in proposal
    assert "silver_eligible" not in proposal
    with duckdb.connect(":memory:") as connection:
        counts = connection.execute(
            "SELECT "
            f"(SELECT count(*) FROM {read_parquet(output_dir / 'raw_file_manifest.parquet')}), "
            f"(SELECT count(*) FROM {read_parquet(output_dir / 'raw_code_day_freq_profile.parquet')}), "
            f"(SELECT count(*) FROM {read_parquet(output_dir / 'raw_grid_profile.parquet')}), "
            f"(SELECT count(*) FROM {read_parquet(output_dir / 'raw_domain_profile.parquet')}), "
            f"(SELECT count(*) FROM {read_parquet(output_dir / 'raw_partition_observation_manifest.parquet')})"
        ).fetchone()
    assert counts == (5, 5, 5, 5, 5)

    reused = observe_etf_mins_raw(
        lake_root=lake_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        raw_bootstrap_report_path=report_path,
        output_dir=output_dir,
    )
    assert reused.observation_summary_hash == result.observation_summary_hash


def test_raw_observation_classifies_explicit_zero_rows_without_a_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, operation_root, report_path = _complete_tiny_raw_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        rows=[],
        operation_id="raw-observe-zero",
    )
    output_dir = operation_root / "raw-observe"
    result = observe_etf_mins_raw(
        lake_root=lake_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        raw_bootstrap_report_path=report_path,
        output_dir=output_dir,
    )

    assert result.scanned_file_count == 5
    assert result.scanned_row_count == 0
    with duckdb.connect(":memory:") as connection:
        issues = connection.execute(
            "SELECT reason_code, count(*), sum(issue_count) "
            f"FROM {read_parquet(output_dir / 'raw_issue_details.parquet')} "
            "GROUP BY reason_code ORDER BY reason_code"
        ).fetchall()
        observation_columns = {
            row[0]
            for row in connection.execute(
                "DESCRIBE SELECT * FROM "
                f"{read_parquet(output_dir / 'raw_partition_observation_manifest.parquet')}"
            ).fetchall()
        }
    assert issues == [
        ("all_frequencies_empty", 5, 5),
        ("expected_code_missing", 5, 5),
    ]
    assert "policy_state" in observation_columns
    assert "decision" not in observation_columns
    assert "silver_eligible" not in observation_columns
    assert result.issue_row_count <= 5 * len(ETF_MINS_RAW_OBSERVATION_REASON_CODES)


def test_raw_observation_compares_boundary_clock_times_across_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade_dates = ("2026-01-02", "2026-01-05")
    lake_root, operation_root, report_path = _complete_tiny_raw_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        rows=[
            minute_row(source_freq=source_freq, trade_date=trade_date)
            for source_freq in ETF_MINS_SOURCE_FREQS
            for trade_date in trade_dates
        ],
        operation_id="raw-observe-clock-boundary",
        trade_dates=trade_dates,
    )
    output_dir = operation_root / "raw-observe"
    observe_etf_mins_raw(
        lake_root=lake_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        raw_bootstrap_report_path=report_path,
        output_dir=output_dir,
    )

    with duckdb.connect(":memory:") as connection:
        boundary_issue_count = connection.execute(
            "SELECT count(*) FROM "
            f"{read_parquet(output_dir / 'raw_issue_details.parquet')} "
            "WHERE reason_code = 'boundary_time_variant_candidate'"
        ).fetchone()[0]
    assert boundary_issue_count == 0


def test_raw_observation_records_value_and_gap_facts_without_enforcing_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade_date = "2026-01-02"
    rows = [
        minute_row(source_freq=source_freq, trade_date=trade_date)
        for source_freq in ETF_MINS_SOURCE_FREQS
    ]
    rows.append(
        (
            "510300.SH",
            "1min",
            datetime.fromisoformat("2026-01-02T10:00:00"),
            -1.0,
            10.0,
            10.1,
            -2.0,
            0,
            -5.0,
            -1.0,
            "XSHG",
        )
    )
    lake_root, operation_root, report_path = _complete_tiny_raw_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        rows=rows,
        operation_id="raw-observe-facts",
    )
    output_dir = operation_root / "raw-observe"
    result = observe_etf_mins_raw(
        lake_root=lake_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        raw_bootstrap_report_path=report_path,
        output_dir=output_dir,
    )

    with duckdb.connect(":memory:") as connection:
        reasons = {
            row[0]
            for row in connection.execute(
                "SELECT reason_code FROM "
                f"{read_parquet(output_dir / 'raw_issue_details.parquet')}"
            ).fetchall()
        }
    assert {
        "internal_grid_gap_candidate",
        "zero_volume_bar_observed",
        "price_domain_anomaly",
        "volume_amount_domain_anomaly",
        "vwap_domain_anomaly",
    }.issubset(reasons)
    summary = json.loads(result.raw_observation_summary_path.read_text())
    assert summary["partition_state"] == "unclassified"
    assert summary["prod_callback_candidates"]


def test_raw_observation_stops_on_changed_raw_or_wrong_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade_date = "2026-01-02"
    lake_root, operation_root, report_path = _complete_tiny_raw_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        rows=[
            minute_row(source_freq=source_freq, trade_date=trade_date)
            for source_freq in ETF_MINS_SOURCE_FREQS
        ],
        operation_id="raw-observe-evidence",
    )
    with pytest.raises(EtfMinsBootstrapError, match="output_path_invalid"):
        observe_etf_mins_raw(
            lake_root=lake_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            raw_bootstrap_report_path=report_path,
            output_dir=operation_root / "different",
        )

    raw_etf_mins_path(lake_root, "1min", trade_date).write_bytes(b"changed")
    with pytest.raises(EtfMinsBootstrapError, match="finalized_raw_file_changed"):
        observe_etf_mins_raw(
            lake_root=lake_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            raw_bootstrap_report_path=report_path,
            output_dir=operation_root / "raw-observe",
        )
