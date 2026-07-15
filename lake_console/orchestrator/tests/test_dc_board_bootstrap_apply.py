from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap import dc_board_bootstrap_apply_cli
from orchestrator.defs.bootstrap.dc_board_bootstrap_apply import (
    run_raw_bootstrap,
    run_raw_reconciliation,
    run_silver_bootstrap,
    run_silver_reconciliation,
    write_phase_report,
    write_reconciliation_report,
)
from orchestrator.defs.bootstrap.dc_board_bootstrap_plan import build_date_plans
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource, TushareResult
from orchestrator.defs.run_contracts.dc_board import DC_INDEX_TYPES


class _FakeTushare:
    def call(self, api_name, params, fields):
        if api_name != "dc_index":
            raise AssertionError(api_name)
        if params["offset"]:
            return TushareResult(rows=[], columns=tuple(fields), metadata={})
        idx_type = params["idx_type"]
        return TushareResult(
            rows=[
                {
                    "ts_code": f"BK{DC_INDEX_TYPES.index(idx_type) + 1:04d}.DC",
                    "trade_date": params["trade_date"],
                    "name": "板块",
                    "leading": "股票",
                    "leading_code": "000001.SZ",
                    "pct_change": 1.0,
                    "leading_pct": 1.0,
                    "total_mv": 100.0,
                    "turnover_rate": 1.0,
                    "up_num": 1,
                    "down_num": 1,
                    "idx_type": idx_type,
                    "level": "L1",
                }
            ],
            columns=tuple(fields),
            metadata={},
        )


class _NoProd:
    def connect_readonly_transaction(self):
        raise AssertionError("dc_index apply must not access Prod DB")


def _calendar(root: Path, dates: tuple[str, ...]) -> Path:
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        f"('SSE', DATE '{value}', TRUE, NULL::DATE)" for value in dates
    )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(exchange, trade_date, is_open, pretrade_date)) "
            "TO ? (FORMAT PARQUET)",
            [str(path)],
        )
    return path


def _baseline(root: Path, dates: tuple[str, ...], path: Path) -> None:
    with duckdb.connect(":memory:") as connection:
        plans = build_date_plans(
            connection=connection,
            calendar_path=silver_trade_calendar_path(root),
            start_date=dates[0],
            end_date=dates[-1],
        )
    payload = {
        "schema_version": 1,
        "lake_root": str(root),
        "should_stop": False,
        "stop_reason_codes": [],
        "source_row_count_by_dataset": {
            plan.dataset: len(dates) * 3 for plan in plans
        },
        "date_plans": [plan.to_dict() for plan in plans],
        "source_audits": [{"failed": False} for _ in range(3)],
        "target_audits": [{"invalid_existing_count": 0} for _ in range(6)],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_apply_cli_requires_explicit_lake_write_confirmation():
    with pytest.raises(SystemExit):
        dc_board_bootstrap_apply_cli._parser().parse_args(
            [
                "raw",
                "--lake-root",
                "/tmp/lake",
                "--baseline-report",
                "/tmp/baseline.json",
            ]
        )


def test_raw_apply_and_reconciliation_are_resumable(tmp_path):
    dates = ("2024-12-20", "2024-12-23")
    _calendar(tmp_path, dates)
    baseline = tmp_path / "baseline.json"
    _baseline(tmp_path, dates, baseline)
    reports = tmp_path / "reports"

    report = run_raw_bootstrap(
        lake_root=tmp_path,
        duckdb_resource=DuckDBResource(),
        tushare=_FakeTushare(),
        prod_postgres=_NoProd(),
        baseline_report=baseline,
        report_dir=reports,
        datasets=("dc_index",),
        batch_size=1,
    )
    assert report.totals == {"expected_dates": 2, "written_count": 2, "skipped_count": 0, "entry_count": 2}
    raw_report = tmp_path / "raw.json"
    write_phase_report(report, raw_report)

    audit = run_raw_reconciliation(
        lake_root=tmp_path,
        duckdb_resource=DuckDBResource(),
        baseline_report=baseline,
        batch_report=raw_report,
        datasets=("dc_index",),
        start_date=dates[0],
        end_date=dates[-1],
    )
    assert not audit.should_stop
    raw_audit = tmp_path / "raw_audit.json"
    write_reconciliation_report(audit, raw_audit)

    resumed = run_raw_bootstrap(
        lake_root=tmp_path,
        duckdb_resource=DuckDBResource(),
        tushare=_FakeTushare(),
        prod_postgres=_NoProd(),
        baseline_report=baseline,
        report_dir=reports,
        datasets=("dc_index",),
        batch_size=1,
    )
    assert resumed.totals["written_count"] == 0
    assert resumed.totals["skipped_count"] == 2

    silver = run_silver_bootstrap(
        lake_root=tmp_path,
        duckdb_resource=DuckDBResource(),
        baseline_report=baseline,
        raw_audit_report=raw_audit,
        report_dir=reports,
        datasets=("dc_index",),
        batch_size=1,
    )
    assert silver.totals["written_count"] == 2
    silver_report = tmp_path / "silver.json"
    write_phase_report(silver, silver_report)
    silver_audit = run_silver_reconciliation(
        lake_root=tmp_path,
        duckdb_resource=DuckDBResource(),
        baseline_report=baseline,
        batch_report=silver_report,
        datasets=("dc_index",),
        start_date=dates[0],
        end_date=dates[-1],
    )
    assert not silver_audit.should_stop


def test_invalid_existing_target_stops_before_writer(tmp_path):
    dates = ("2024-12-20",)
    _calendar(tmp_path, dates)
    baseline = tmp_path / "baseline.json"
    _baseline(tmp_path, dates, baseline)
    target = tmp_path / "raw/board/dc_index/trade_date=2024-12-20/part-000.parquet"
    target.parent.mkdir(parents=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "COPY (SELECT NULL::VARCHAR AS ts_code, '20241220' AS trade_date) TO ? (FORMAT PARQUET)",
            [str(target)],
        )
    with pytest.raises(Exception, match="target conflict"):
        run_raw_bootstrap(
            lake_root=tmp_path,
            duckdb_resource=DuckDBResource(),
            tushare=_FakeTushare(),
            prod_postgres=_NoProd(),
            baseline_report=baseline,
            report_dir=tmp_path / "reports",
            datasets=("dc_index",),
        )
