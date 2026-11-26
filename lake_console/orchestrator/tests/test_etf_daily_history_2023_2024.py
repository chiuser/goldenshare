from __future__ import annotations

import csv
from datetime import date
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import etf_daily_bootstrap_apply as apply
from orchestrator.defs.bootstrap import etf_daily_bootstrap_cli as cli
from orchestrator.defs.bootstrap import etf_daily_history_source as source
from orchestrator.defs.bootstrap.etf_daily_bootstrap_audit import (
    EtfDailyBootstrapAuditError,
    run_physical_post_audit,
    run_raw_audit,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_events import (
    EtfDailyBootstrapEventsError,
    build_event_plan,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_plan import (
    EtfDailyBootstrapPlanError,
    build_etf_daily_raw_bootstrap_plan,
    build_etf_daily_silver_bootstrap_plan,
    load_etf_daily_raw_bootstrap_plan,
    load_etf_daily_silver_bootstrap_plan,
    write_raw_bootstrap_plan,
    write_silver_bootstrap_plan,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_DAILY_RAW_SPEC,
    EtfDailyRawValidationError,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_basic import (
    RAW_ETF_BASIC_CHECKS,
    SILVER_ETF_BASIC_CHECKS,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_COVERAGE_POLICY_REVISION,
    FUND_DAILY_SOURCE_COLUMNS,
)
from tests.etf_daily_test_support import basic_row, make_roots, write_basic_reference
from tests.test_etf_basic_readiness import _ready_fixture, _report_basic_run
from tests.test_etf_daily_bootstrap import _daily_row, _FakeTushare, _PartitionInstance


def _plan(tmp_path, *, first_count=20):
    lake, staging = make_roots(tmp_path)
    calendar = silver_trade_calendar_path(lake)
    calendar.parent.mkdir(parents=True)
    first_dates = (
        "2023-01-03",
        "2023-01-04",
        "2023-01-05",
        "2023-01-06",
        "2023-01-09",
        "2023-01-10",
        "2023-01-11",
        "2023-01-12",
        "2023-01-13",
        "2023-01-16",
        "2023-01-17",
        "2023-01-18",
        "2023-01-19",
        "2023-01-20",
        "2023-01-30",
        "2023-01-31",
        "2023-02-01",
        "2023-02-02",
        "2023-02-03",
        "2023-02-06",
    )[:first_count]
    dates = (*first_dates, "2024-12-31")
    values = ", ".join(f"('SSE', true, DATE '{day}')" for day in (*dates, "2025-01-02"))
    duckdb = DuckDBResource()
    with duckdb.connect() as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) t(exchange, is_open, trade_date)) "
            f"TO {duckdb_string(calendar)} (FORMAT PARQUET)"
        )
    instance = _PartitionInstance((*dates, "2025-01-02"))
    plan = build_etf_daily_raw_bootstrap_plan(
        instance=instance,
        lake_root=lake,
        staging_root=staging,
        duckdb_resource=duckdb,
        code_revision="test",
        operation_id="history-test",
        historical=True,
    )
    raw_path = tmp_path / "raw-plan.json"
    write_raw_bootstrap_plan(plan, raw_path)
    assert (
        load_etf_daily_raw_bootstrap_plan(
            raw_path, expected_plan_hash=plan.raw_plan_hash
        )
        == plan
    )
    assert plan.trade_dates == dates
    assert all(row.trade_date != "2025-01-02" for row in plan.raw_targets)
    return lake, staging, duckdb, plan, instance


def _fake_export(monkeypatch, dates):
    calls = []

    def export(path, _timeout):
        calls.append(path)
        with path.open("w", newline="") as file:
            out = csv.DictWriter(file, fieldnames=FUND_DAILY_SOURCE_COLUMNS)
            out.writeheader()
            for day in dates:
                row = _daily_row("510330.SH", day)
                row.update(close=4.02, change=0.02, pct_chg=0.5)
                out.writerow(row)

    monkeypatch.setattr(source, "_export_prod_csv", export)
    return calls


def test_history_first_batch_and_full_resume_keep_source_and_basic(
    tmp_path, monkeypatch
):
    lake, staging, duckdb, raw_plan, instance = _plan(tmp_path)
    dates = raw_plan.trade_dates
    calls = _fake_export(monkeypatch, dates)
    export_options = {
        "staging_root": staging,
        "plan": raw_plan,
        "duckdb": duckdb,
        "tushare_dates": (dates[0],),
        "timeout_seconds": 10,
    }
    frozen = source.prepare_history_source(**export_options)
    assert source.prepare_history_source(**export_options) == frozen
    assert len(calls) == 1

    sentinel = FUND_DAILY_RAW_SPEC.target_path_builder(lake, "2025-01-02")
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b"outside this historical operation")
    checkpoint = tmp_path / "checkpoint.json"
    common = {
        "raw_plan": raw_plan,
        "lake_root": lake,
        "duckdb_resource": duckdb,
        "checkpoint_path": checkpoint,
    }
    raw_apply = dict(
        **common, staging_root=staging, instance=instance, confirm_raw_apply=True
    )
    original_append = apply.append_checkpoint

    def interrupt_after_publish(*args, **kwargs):
        raise InterruptedError("published before checkpoint")

    monkeypatch.setattr(apply, "append_checkpoint", interrupt_after_publish)
    with pytest.raises(InterruptedError, match="before checkpoint"):
        apply.run_raw_apply(
            **raw_apply,
            first_batch=True,
            tushare=_FakeTushare(),
            output_path=tmp_path / "crash.json",
        )
    assert FUND_DAILY_RAW_SPEC.target_path_builder(lake, dates[0]).is_file()
    assert apply.load_checkpoint(checkpoint) == ()
    monkeypatch.setattr(apply, "append_checkpoint", original_append)

    class ChangedSource(_FakeTushare):
        def call(self, *args, **kwargs):
            response = super().call(*args, **kwargs)
            response.rows[0]["amount"] = 401.0
            return response

    with pytest.raises(EtfDailyRawValidationError, match="refusing overwrite"):
        apply.run_raw_apply(
            **raw_apply,
            first_batch=True,
            tushare=ChangedSource(),
            output_path=tmp_path / "conflict.json",
        )
    assert apply.load_checkpoint(checkpoint) == ()

    tushare = _FakeTushare()
    report = apply.run_raw_apply(
        **raw_apply,
        first_batch=True,
        tushare=tushare,
        output_path=tmp_path / "first-raw.json",
    )
    assert report["completed_file_count"] == 40
    first, other = [
        entry
        for entry in apply.load_checkpoint(checkpoint)
        if entry.asset_key == FUND_DAILY_RAW_SPEC.asset_key
    ][:2]
    assert first.write_mode == "reuse_existing"
    assert first.source["name"] == "fund_daily"
    assert other.source["name"] == "raw_tushare.fund_daily"
    assert [
        params["trade_date"] for api, params, _ in tushare.calls if api == "fund_daily"
    ] == ["20230103"]
    assert not FUND_DAILY_RAW_SPEC.target_path_builder(lake, dates[-1]).exists()

    basic = write_basic_reference(
        lake_root=lake,
        staging_root=staging,
        rows=(
            basic_row("510330.SH"),
            basic_row("159919.SZ", list_date="20241231"),
        ),
    )

    def silver_plan_for(first_batch):
        audit = run_raw_audit(
            **common,
            latest_basic_reference=basic,
            first_batch=first_batch,
            output_path=tmp_path / f"raw-audit-{first_batch}.json",
        )
        silver = build_etf_daily_silver_bootstrap_plan(
            raw_plan=raw_plan,
            raw_audit_report=audit,
            basic_reference=basic,
            basic_storage_ids=(101, 102),
            lake_root=lake,
            staging_root=staging,
            duckdb_resource=duckdb,
            code_revision="test",
            coverage_policy_revision=ETF_DAILY_COVERAGE_POLICY_REVISION,
            coverage_review_confirmed=True,
            first_batch=first_batch,
        )
        path = tmp_path / f"silver-{first_batch}.json"
        write_silver_bootstrap_plan(silver, path)
        silver = load_etf_daily_silver_bootstrap_plan(
            path, expected_plan_hash=silver.silver_plan_hash
        )
        report = apply.run_silver_apply(
            **common,
            silver_plan=silver,
            latest_basic_reference=basic,
            staging_root=staging,
            output_path=tmp_path / f"silver-apply-{first_batch}.json",
            confirm_silver_apply=True,
        )
        assert report["completed_file_count"] == 2 * len(silver.trade_dates)
        return silver

    first_silver = silver_plan_for(True)
    assert first_silver.trade_dates == dates[:20]
    first_audit = run_physical_post_audit(
        **common,
        silver_plan=first_silver,
        staging_root=staging,
        output_path=tmp_path / "first-physical.json",
        liquidating_codes_by_date={},
    )
    assert first_audit["passed"] is True
    with pytest.raises(EtfDailyBootstrapEventsError, match="requires the full"):
        build_event_plan(
            instance=instance,
            silver_plan=first_silver,
            physical_report_path=tmp_path / "first-physical.json",
        )

    resumed = _FakeTushare()
    apply.run_raw_apply(
        **raw_apply,
        tushare=resumed,
        tushare_dates=(dates[-1],),
        output_path=tmp_path / "all-raw.json",
    )
    assert [(api, params["trade_date"]) for api, params, _ in resumed.calls] == [
        ("fund_daily", "20241231"),
        ("fund_adj", "20241231"),
    ]
    full = silver_plan_for(False)
    assert full.checkpoint_hash == first_silver.checkpoint_hash
    assert full.silver_plan_hash != first_silver.silver_plan_hash
    with pytest.raises(EtfDailyBootstrapAuditError, match="did not pass"):
        run_physical_post_audit(
            **common,
            silver_plan=full,
            staging_root=staging,
            output_path=tmp_path / "uncovered.json",
            liquidating_codes_by_date={},
        )
    result = run_physical_post_audit(
        **common,
        silver_plan=full,
        staging_root=staging,
        output_path=tmp_path / "all-physical.json",
        liquidating_codes_by_date={dates[-1]: ("159919.SZ", "510330.SH")},
    )
    assert result["passed"] is True
    assert result["expected_file_count"] == 84
    assert result["actual_file_count"] == 84
    factors = next(
        row
        for row in result["file_evidence"]
        if row["trade_date"] == dates[-1]
        and row["asset_key"] == "silver_etf_adj_factor"
    )
    assert factors["silver_extra_code_count"] == 0
    assert factors["written_row_count"] == 1
    assert sentinel.read_bytes() == b"outside this historical operation"
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path)) as events:
        event_plan = build_event_plan(
            instance=events,
            silver_plan=full,
            physical_report_path=tmp_path / "all-physical.json",
        )
    assert len(event_plan.materializations) == 84
    assert len(event_plan.checks) == 340
    prod_result = next(
        item
        for item in event_plan.materializations
        if item.asset_key == FUND_DAILY_RAW_SPEC.asset_key
        and item.trade_date == dates[1]
    )
    assert (
        prod_result.metadata["goldenshare/source"]["name"] == "raw_tushare.fund_daily"
    )


def test_historical_source_checks_scope_integrity_and_read_only_sql(
    tmp_path, monkeypatch
):
    _, staging, duckdb, plan, _ = _plan(tmp_path, first_count=1)
    _fake_export(monkeypatch, plan.trade_dates)
    common = {
        "staging_root": staging,
        "plan": plan,
        "duckdb": duckdb,
        "timeout_seconds": 10,
    }
    with pytest.raises(EtfDailyBootstrapPlanError, match="outside"):
        source.prepare_history_source(**common, tushare_dates=("2025-01-02",))
    artifact = source.prepare_history_source(**common, tushare_dates=())
    with artifact.path.open("ab") as output:
        output.write(b"drift")
    with pytest.raises(EtfDailyBootstrapPlanError, match="fingerprint differs"):
        source.load_history_source(staging, plan)
    args = cli._parser().parse_args(
        [
            "history-source",
            "--raw-plan",
            "/tmp/plan.json",
            "--expected-raw-plan-hash",
            "test",
            "--lake-root",
            "/tmp/lake",
            "--staging-root",
            "/tmp/staging",
            "--prod-timeout-seconds",
            "10",
        ]
    )
    assert (
        cli._confirmation_error(args) == "history-source requires --confirm-prod-export"
    )


def test_prod_history_extract_is_a_single_read_only_whitelisted_copy(
    tmp_path, monkeypatch
):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs["input"].decode()))
        kwargs["stdout"].write(b"isolated")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(source.subprocess, "run", run)
    target = tmp_path / "raw.csv"
    source._export_prod_csv(target, 10)
    assert len(calls) == 1
    command, sql = calls[0]
    assert command == ["bash", "scripts/psql-remote.sh", "--", "-q"]
    assert "BEGIN READ ONLY" in sql and "statement_timeout = '10s'" in sql
    assert sql.count("COPY (") == 1
    assert (
        "SELECT ts_code, trade_date, pre_close, open, high, low, close, change, pct_chg, vol, amount FROM raw_tushare.fund_daily"
        in sql
    )
    assert "trade_date >= DATE '2023-01-03' AND trade_date < DATE '2025-01-01'" in sql
    assert target.read_bytes() == b"isolated"


def test_frozen_historical_basic_reads_original_checks_after_new_materialization(
    tmp_path,
):
    fixture, lake, _ = _ready_fixture(tmp_path)
    raw, silver = dg.AssetKey("raw_tushare_etf_basic"), dg.AssetKey("silver_etf_basic")
    raw_metadata = fixture.records_by_asset[raw][0].asset_materialization.metadata
    silver_metadata = fixture.records_by_asset[silver][0].asset_materialization.metadata
    duckdb = DuckDBResource()
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path)) as instance:
        raw_id = _report_basic_run(
            instance, raw, raw_metadata, RAW_ETF_BASIC_CHECKS, "original-raw"
        )
        silver_id = _report_basic_run(
            instance,
            silver,
            silver_metadata,
            SILVER_ETF_BASIC_CHECKS,
            "original-silver",
        )
        reference = cli.select_historical_etf_basic_snapshot_reference(
            instance=instance,
            lake_root_path=lake,
            duckdb_resource=duckdb,
            trade_date=date(2026, 8, 30),
            raw_storage_id=raw_id,
            silver_storage_id=silver_id,
        )
        new_raw_id = _report_basic_run(
            instance, raw, raw_metadata, RAW_ETF_BASIC_CHECKS[:-1], "new-incomplete-raw"
        )
        assert (
            cli._check_frozen_basic(
                instance, lake, duckdb, reference, (raw_id, silver_id)
            )
            == reference
        )
        with pytest.raises(
            cli.EtfBasicReadinessError, match="historical_checks_not_passed"
        ):
            cli._check_frozen_basic(
                instance, lake, duckdb, reference, (new_raw_id, silver_id)
            )
