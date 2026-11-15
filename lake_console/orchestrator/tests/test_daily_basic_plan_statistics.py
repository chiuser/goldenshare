"""LLD36: real CLI planning and temporary files; only Prod and roots are replaced."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from orchestrator.defs.bootstrap import daily_basic_history as history
from orchestrator.defs.bootstrap import daily_basic_history_cli as cli
from orchestrator.defs.daily_basic_contract import DailyBasicValidationError
from orchestrator.defs.paths import silver_trade_calendar_path
from tests.test_daily_basic_history import DAYS, Source

# LLD35: actual aggregate count and observation date; no performance measurements.
STATISTICS = {
    "basis": "statistics",
    "row_baseline": 14499459,
    "row_baseline_asof": "2026-11-15",
}
# Original P0 input already covered by test_daily_basic_history.py.
LEGACY_P0 = {
    "row_baseline": 14288011,
    "row_baseline_asof": "2026-09-14",
    "one_export_minutes_linear_scenarios": [31.6, 117.8],
    "estimated_chunk_GiB": [0.4],
    "estimated_date_files_GiB": [0.7],
}
# Existing two-row history fixture budgets, not production defaults or approvals.
LIMITS = {
    "max_source_rows": 50000,
    "max_source_seconds": 60,
    "max_stage_seconds": 60,
    "max_spill_bytes": 100000000,
}


def test_statistics_costs_have_no_unmeasured_estimates():
    assert history.history_cost_estimate(STATISTICS) == {
        "basis": "statistics",
        "baseline_rows": 14499459,
        "baseline_asof": "2026-11-15",
        "estimated_pages_per_pass": 1451,
        "source_policy": "operator_confirmed_stable_single_pass",
        "source_pass_count": 1,
        "full_execution_approved": False,
    }


def test_legacy_costs_remain_exactly_unchanged():
    assert history.history_cost_estimate(LEGACY_P0) == {
        "basis": "P0 measured samples; extrapolation, not SLA",
        "baseline_rows": 14288011,
        "baseline_asof": "2026-09-14",
        "estimated_pages_per_pass": 1430,
        "source_policy": "operator_confirmed_stable_single_pass",
        "source_pass_count": 1,
        "export_minutes": [31.6, 117.8],
        "source_recheck_minutes": 0,
        "chunk_gib": [0.4],
        "formal_gib": [0.7],
        "candidate_gib": [0.7],
        "fragment_gib": [0.7],
        "annual_intermediate_gib": [0.4],
        "build_audit_promote_seconds": None,
        "spill_peak_bytes": None,
        "full_execution_approved": False,
    }


def test_statistics_input_requires_explicit_marker():
    # Missing P0 measurements must not silently switch an old input to statistics.
    with pytest.raises(KeyError, match="one_export_minutes_linear_scenarios"):
        history.history_cost_estimate(
            {"row_baseline": 14499459, "row_baseline_asof": "2026-11-15"}
        )


@pytest.fixture
def cli_workspace(tmp_path, monkeypatch):
    lake, staging = tmp_path / "lake", tmp_path / "staging"
    calendar = silver_trade_calendar_path(lake)
    calendar.parent.mkdir(parents=True)
    # Producer: silver_trade_calendar_select / SILVER_TRADE_CALENDAR_SCHEMA.
    # Include closed, other-exchange and out-of-range dates as negative cases.
    with duckdb.connect() as connection:
        connection.execute(
            "COPY (SELECT * FROM (VALUES "
            "('SSE', DATE '2024-12-30', true, DATE '2024-12-27'), "
            "('SSE', DATE '2024-12-31', true, DATE '2024-12-30'), "
            "('SSE', DATE '2025-01-01', false, DATE '2024-12-31'), "
            "('SSE', DATE '2025-01-02', true, DATE '2024-12-31'), "
            "('SZSE', DATE '2025-01-02', true, DATE '2024-12-31'), "
            "('SSE', DATE '2025-01-03', true, DATE '2025-01-02')"
            ") AS c(exchange, trade_date, is_open, pretrade_date)) "
            "TO ? (FORMAT PARQUET)",
            [str(calendar)],
        )
    source = Source()
    monkeypatch.setattr(cli, "DEFAULT_LAKE_ROOT", str(lake))
    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(cli, "ProdPostgresResource", lambda: None)
    monkeypatch.setattr(cli, "DailyBasicHistorySource", lambda resource: source)
    return lake, staging, source


def make_cli_plan(tmp_path, evidence, *, limits=None, replace=False):
    cost_path = tmp_path / "cost.json"
    cost_path.write_text(json.dumps(evidence))
    report = tmp_path / "plan.json"
    argv = [
        "plan",
        "--start",
        DAYS[0],
        "--end",
        DAYS[-1],
        "--batch-id",
        "statistics-fixture",
        "--cost-evidence",
        str(cost_path),
        "--report",
        str(report),
    ]
    for name, value in (limits or {}).items():
        argv.extend(["--" + name.replace("_", "-"), str(value)])
    if replace:
        argv.append("--replace-existing")
    result = cli.run_history_cli(cli.history_parser().parse_args(argv))
    assert history.load_history_report(report) == result
    return result, report, cost_path


@pytest.mark.parametrize("evidence", [STATISTICS, LEGACY_P0], ids=["statistics", "p0"])
@pytest.mark.parametrize("replace", [False, True], ids=["ordinary", "replacement"])
def test_cli_plan_export_build_with_original_limits(
    cli_workspace, tmp_path, monkeypatch, evidence, replace
):
    lake, staging, source = cli_workspace
    plan, plan_path, cost_path = make_cli_plan(
        tmp_path, evidence, limits=LIMITS, replace=replace
    )
    assert source.calls == 0
    assert not staging.exists()
    assert plan["dates"] == ["2024-12-31", "2025-01-02"]
    assert plan["stop_reasons"] == []
    assert plan["replace_existing"] is replace
    assert plan["execution_budget_frozen"] is True
    assert plan["limits"] == LIMITS
    assert len(plan["source_fields"]) == 19
    assert plan["source_fields"][-1] == "limit_status"
    assert plan["cost_evidence"]["evidence_path"] == str(cost_path)
    assert (
        plan["cost_evidence"]["evidence_sha256"]
        == hashlib.sha256(cost_path.read_bytes()).hexdigest()
    )
    assert plan["cost_evidence"]["full_execution_approved"] is False

    # Only the volume availability boundary is replaced, never real formal roots.
    monkeypatch.setattr(cli.os.path, "ismount", lambda path: True)
    results = {}
    for stage in ("export", "build"):
        results[stage] = cli.run_history_cli(
            cli.history_parser().parse_args(
                [
                    stage,
                    "--plan",
                    str(plan_path),
                    "--apply",
                    "--fingerprint",
                    plan["fingerprint"],
                    "--report",
                    str(tmp_path / f"{stage}-report.json"),
                ]
            )
        )
    assert results["export"]["rows"] == 2
    assert source.calls == 2  # One two-row batch, then the terminal empty batch.
    assert len(results["build"]["files"]) == 2
    assert [item["rows"] for item in results["build"]["files"]] == [1, 1]
    with duckdb.connect() as connection:
        for item in results["build"]["files"]:
            path = Path(item["path"])
            assert path.is_relative_to(staging)
            assert connection.execute(
                "SELECT ts_code, trade_date, limit_status, typeof(limit_status) "
                "FROM read_parquet(?, hive_partitioning=false)",
                [str(path)],
            ).fetchall() == [("000001.SZ", item["date"].replace("-", ""), 1, "INTEGER")]
    assert not (lake / "raw").exists()


@pytest.mark.parametrize("evidence", [STATISTICS, LEGACY_P0], ids=["statistics", "p0"])
def test_cli_draft_still_allowed_but_not_executable(cli_workspace, tmp_path, evidence):
    _, staging, source = cli_workspace
    plan, _, _ = make_cli_plan(tmp_path, evidence)
    assert plan["limits"] is None
    assert plan["execution_budget_frozen"] is False
    with pytest.raises(
        DailyBasicValidationError, match="history_execution_budget_not_frozen"
    ):
        history.export_daily_basic_history(plan, source, apply=True)
    assert source.calls == 0
    assert not staging.exists()


@pytest.mark.parametrize("evidence", [STATISTICS, LEGACY_P0], ids=["statistics", "p0"])
@pytest.mark.parametrize(
    "limits",
    [
        {"max_source_rows": 50000},
        {**LIMITS, "max_stage_seconds": 0},
        {**LIMITS, "max_source_rows": -1},
    ],
    ids=["partial", "zero", "negative"],
)
def test_cli_keeps_original_invalid_limit_rejection(
    cli_workspace, tmp_path, evidence, limits
):
    _, staging, source = cli_workspace
    with pytest.raises(DailyBasicValidationError, match="history_execution_limits"):
        make_cli_plan(tmp_path, evidence, limits=limits)
    assert source.calls == 0
    assert not staging.exists()
    assert not (tmp_path / "plan.json").exists()


@pytest.mark.parametrize("evidence", [STATISTICS, LEGACY_P0], ids=["statistics", "p0"])
def test_cli_keeps_explicit_source_row_cap(cli_workspace, tmp_path, evidence):
    _, _, source = cli_workspace
    plan, _, _ = make_cli_plan(
        tmp_path, evidence, limits={**LIMITS, "max_source_rows": 1}
    )
    with pytest.raises(DailyBasicValidationError, match="history_row_budget"):
        history.export_daily_basic_history(plan, source, apply=True)
    assert source.calls == 1
    assert not list(tmp_path.rglob("chunks/*.parquet"))


@pytest.mark.parametrize("evidence", [STATISTICS, LEGACY_P0], ids=["statistics", "p0"])
def test_original_disk_check_only_uses_available_estimates(
    cli_workspace, tmp_path, monkeypatch, evidence
):
    plan, _, _ = make_cli_plan(tmp_path, evidence, limits=LIMITS)
    # Legacy estimates total 0.4 + 0.7 + 0.4 + 0.7 + 0.7 = 2.9 GiB, plus spill.
    # Statistics has no file-size estimate; the unchanged check only knows spill.
    monkeypatch.setattr(
        history.shutil, "disk_usage", lambda path: SimpleNamespace(free=2 * 1024**3)
    )
    if evidence is LEGACY_P0:
        with pytest.raises(DailyBasicValidationError, match="history_disk_budget"):
            history._validate_plan(plan, apply=True)
    else:
        history._validate_plan(plan, apply=True)
    monkeypatch.setattr(
        history.shutil, "disk_usage", lambda path: SimpleNamespace(free=0)
    )
    with pytest.raises(DailyBasicValidationError, match="history_disk_budget"):
        history._validate_plan(plan, apply=True)
