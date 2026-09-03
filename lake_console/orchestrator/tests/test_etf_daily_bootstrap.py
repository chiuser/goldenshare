from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap.etf_daily_bootstrap_apply import (
    EtfDailyBootstrapApplyError,
    _chunks,
    load_checkpoint,
    run_bounded_sample,
    run_raw_apply,
    run_silver_apply,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_audit import (
    EtfDailyBootstrapAuditError,
    run_physical_post_audit,
    run_raw_audit,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_cli import (
    _confirmation_error,
    _parser,
    _require_formal_roots,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_plan import (
    EtfDailyBootstrapPlanError,
    build_etf_daily_raw_bootstrap_plan,
    build_etf_daily_silver_bootstrap_plan,
    load_etf_daily_raw_bootstrap_plan,
    load_json,
    write_raw_bootstrap_plan,
    write_silver_bootstrap_plan,
)
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_DAILY_RAW_SPEC,
    EtfDailyRawValidationError,
)
from orchestrator.defs.resources import DuckDBResource, TushareResult
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_COVERAGE_POLICY_REVISION,
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_SOURCE_COLUMNS,
)
from tests.etf_daily_test_support import (
    basic_row,
    make_roots,
    write_basic_reference,
    write_raw_fixture,
)

DATES = ("2025-01-02", "2025-01-03")


class _PartitionInstance:
    def __init__(self, dates: Sequence[str]) -> None:
        self.dates = list(dates)

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self.dates)


class _FakeTushare:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object], tuple[str, ...]]] = []
        self.fail_on_call = fail_on_call

    def call(
        self,
        api_name: str,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> TushareResult:
        copied = dict(params)
        self.calls.append((api_name, copied, tuple(fields)))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("bounded fake failure")
        if int(copied["offset"]):
            rows: list[dict[str, object]] = []
        elif api_name == "fund_daily":
            rows = [_daily_row("510330.SH", str(copied["trade_date"]))]
        else:
            rows = [_adj_row("510330.SH", str(copied["trade_date"]))]
        return TushareResult(rows=rows, columns=tuple(fields), metadata={})


def _daily_row(ts_code: str, trade_date: str) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "pre_close": 4.0,
        "open": 4.0,
        "high": 4.02,
        "low": 3.99,
        "close": 4.01,
        "change": 0.01,
        "pct_chg": 0.25,
        "vol": 100.0,
        "amount": 400.0,
    }


def _adj_row(ts_code: str, trade_date: str) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "adj_factor": 1.0,
        "discount_rate": None,
    }


def _raw_plan(tmp_path: Path, dates: Sequence[str] = DATES):
    lake_root, staging_root = make_roots(tmp_path)
    plan = build_etf_daily_raw_bootstrap_plan(
        instance=_PartitionInstance(dates),
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        code_revision="test-revision",
        operation_id="etf-daily-test",
        created_at=datetime(2026, 9, 3, tzinfo=UTC),
        observed_free_bytes=10**9,
    )
    return lake_root, staging_root, plan


def test_raw_plan_is_request_free_and_freezes_only_registered_2025_dates(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    instance = _PartitionInstance(("2024-12-31", "2025-01-03", "2025-01-02"))
    plan = build_etf_daily_raw_bootstrap_plan(
        instance=instance,
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        code_revision="revision",
        operation_id="request-free-plan",
        observed_free_bytes=10**9,
    )

    assert plan.trade_dates == DATES
    assert plan.watermark == "2025-01-03"
    assert len(plan.raw_targets) == 4
    assert "basic_reference" not in plan.to_dict()
    assert plan.to_dict()["writes"] == {
        "tushare_requests": 0,
        "formal_lake_files": 0,
        "dagster_events": 0,
    }


def test_raw_plan_round_trip_rejects_hash_and_contract_drift(tmp_path: Path) -> None:
    _, _, plan = _raw_plan(tmp_path)
    path = tmp_path / "raw-plan.json"
    write_raw_bootstrap_plan(plan, path)
    assert (
        load_etf_daily_raw_bootstrap_plan(path, expected_plan_hash=plan.raw_plan_hash)
        == plan
    )

    payload = path.read_text(encoding="utf-8").replace(
        '"watermark": "2025-01-03"', '"watermark": "2025-01-02"'
    )
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(EtfDailyBootstrapPlanError, match="drifted"):
        load_etf_daily_raw_bootstrap_plan(path, expected_plan_hash=plan.raw_plan_hash)


def test_raw_apply_stops_then_resumes_from_per_file_checkpoint(tmp_path: Path) -> None:
    lake_root, staging_root, plan = _raw_plan(tmp_path)
    checkpoint = tmp_path / "checkpoint.json"
    with pytest.raises(EtfDailyRawValidationError, match="bounded fake failure"):
        run_raw_apply(
            raw_plan=plan,
            instance=_PartitionInstance(DATES),
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb_resource=DuckDBResource(),
            tushare=_FakeTushare(fail_on_call=3),  # type: ignore[arg-type]
            checkpoint_path=checkpoint,
            output_path=tmp_path / "raw-apply.json",
            confirm_raw_apply=True,
        )

    assert (
        len([item for item in load_checkpoint(checkpoint) if item.phase == "raw"]) == 2
    )

    resumed_source = _FakeTushare()
    report = run_raw_apply(
        raw_plan=plan,
        instance=_PartitionInstance(DATES),
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        tushare=resumed_source,  # type: ignore[arg-type]
        checkpoint_path=checkpoint,
        output_path=tmp_path / "raw-apply.json",
        confirm_raw_apply=True,
    )
    assert report["completed_file_count"] == 4
    assert len(resumed_source.calls) == 2
    replay_source = _FakeTushare()
    replay = run_raw_apply(
        raw_plan=plan,
        instance=_PartitionInstance(DATES),
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        tushare=replay_source,  # type: ignore[arg-type]
        checkpoint_path=checkpoint,
        output_path=tmp_path / "raw-apply-replay.json",
        confirm_raw_apply=True,
    )
    assert replay["completed_file_count"] == 4
    assert replay_source.calls == []


def test_raw_apply_rejects_watermark_and_uncompleted_target_drift(
    tmp_path: Path,
) -> None:
    lake_root, staging_root, plan = _raw_plan(tmp_path)
    with pytest.raises(EtfDailyBootstrapApplyError, match="watermark"):
        run_raw_apply(
            raw_plan=plan,
            instance=_PartitionInstance((*DATES, "2025-01-06")),
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb_resource=DuckDBResource(),
            tushare=_FakeTushare(),  # type: ignore[arg-type]
            checkpoint_path=tmp_path / "checkpoint.json",
            output_path=tmp_path / "apply.json",
            confirm_raw_apply=True,
        )

    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_DAILY_RAW_SPEC,
        partition_key=DATES[0],
        rows=(_daily_row("159919.SZ", "20250102"),),
    )
    with pytest.raises(EtfDailyRawValidationError, match="conflicts"):
        run_raw_apply(
            raw_plan=plan,
            instance=_PartitionInstance(DATES),
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb_resource=DuckDBResource(),
            tushare=_FakeTushare(),  # type: ignore[arg-type]
            checkpoint_path=tmp_path / "checkpoint.json",
            output_path=tmp_path / "apply.json",
            confirm_raw_apply=True,
        )


def test_raw_apply_recovers_file_written_before_checkpoint(tmp_path: Path) -> None:
    lake_root, staging_root, plan = _raw_plan(tmp_path)
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_DAILY_RAW_SPEC,
        partition_key=DATES[0],
        rows=(_daily_row("510330.SH", "20250102"),),
    )
    checkpoint = tmp_path / "checkpoint.json"
    report = run_raw_apply(
        raw_plan=plan,
        instance=_PartitionInstance(DATES),
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        tushare=_FakeTushare(),  # type: ignore[arg-type]
        checkpoint_path=checkpoint,
        output_path=tmp_path / "raw-apply.json",
        confirm_raw_apply=True,
    )
    entries = [item for item in load_checkpoint(checkpoint) if item.phase == "raw"]
    recovered = next(
        item
        for item in entries
        if item.asset_key == "raw_tushare_fund_daily" and item.trade_date == DATES[0]
    )
    assert report["completed_file_count"] == 4
    assert recovered.write_mode == "reuse_existing"


def test_raw_plan_and_apply_reject_space_below_the_frozen_factor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake_root, staging_root = make_roots(tmp_path)
    with pytest.raises(EtfDailyBootstrapPlanError, match="space gate"):
        build_etf_daily_raw_bootstrap_plan(
            instance=_PartitionInstance(DATES),
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb_resource=DuckDBResource(),
            code_revision="revision",
            operation_id="space-plan",
            observed_free_bytes=0,
        )

    _, _, plan = _raw_plan(_make_parent(tmp_path / "apply-space"))
    usage = __import__("shutil").disk_usage(staging_root)
    monkeypatch.setattr(
        "orchestrator.defs.bootstrap.etf_daily_bootstrap_apply.shutil.disk_usage",
        lambda _path: usage._replace(free=0),
    )
    with pytest.raises(EtfDailyBootstrapApplyError, match="space gate"):
        run_raw_apply(
            raw_plan=plan,
            instance=_PartitionInstance(DATES),
            lake_root=tmp_path / "apply-space" / "data_lake",
            staging_root=tmp_path / "apply-space" / "data_lake_staging",
            duckdb_resource=DuckDBResource(),
            tushare=_FakeTushare(),  # type: ignore[arg-type]
            checkpoint_path=tmp_path / "space-checkpoint.json",
            output_path=tmp_path / "space-apply.json",
            confirm_raw_apply=True,
        )


def test_bounded_sample_uses_at_most_three_dates_and_never_writes_source_lake(
    tmp_path: Path,
) -> None:
    source_lake, source_staging, plan = _raw_plan(
        _make_parent(tmp_path / "source"),
        ("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"),
    )
    reference = write_basic_reference(
        lake_root=source_lake,
        staging_root=source_staging,
        rows=(basic_row("510330.SH"),),
    )
    isolated_lake, isolated_staging = make_roots(_make_parent(tmp_path / "isolated"))
    report = run_bounded_sample(
        raw_plan=plan,
        isolated_lake_root=isolated_lake,
        isolated_staging_root=isolated_staging,
        duckdb_resource=DuckDBResource(),
        tushare=_FakeTushare(),  # type: ignore[arg-type]
        basic_reference=reference,
        output_path=tmp_path / "bounded-sample.json",
    )
    assert report["trade_dates"] == ["2025-01-02", "2025-01-06", "2025-01-07"]
    assert report["formal_lake_files_written"] == 0
    assert report["peak_rss_bytes"] > 0
    assert report["temp_spill_bytes"] == 0
    assert report["field_gates"] == {"change": True, "discount_rate": True}
    assert not (source_lake / "raw" / "tushare" / "fund_daily").exists()
    assert len(list(isolated_lake.rglob("part-000.parquet"))) == 14


@pytest.mark.parametrize("missing_factor", (False, True))
def test_raw_audit_silver_plan_apply_and_physical_audit_close_four_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_factor: bool,
) -> None:
    lake_root, staging_root, raw_plan = _raw_plan(tmp_path)
    reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=(basic_row("510330.SH"), basic_row("159919.SZ"))
        if missing_factor
        else (basic_row("510330.SH"),),
    )
    checkpoint = tmp_path / "checkpoint.json"
    run_raw_apply(
        raw_plan=raw_plan,
        instance=_PartitionInstance(DATES),
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        tushare=_FakeTushare(),  # type: ignore[arg-type]
        checkpoint_path=checkpoint,
        output_path=tmp_path / "raw-apply.json",
        confirm_raw_apply=True,
    )
    from orchestrator.defs.bootstrap import etf_daily_bootstrap_plan as plan_module

    with monkeypatch.context() as patch:

        def no_second_manifest_scan(**_kwargs):
            raise AssertionError(
                "Raw audit must derive its manifest from the batch results"
            )

        patch.setattr(plan_module, "build_raw_manifest", no_second_manifest_scan)
        raw_audit = run_raw_audit(
            raw_plan=raw_plan,
            lake_root=lake_root,
            duckdb_resource=DuckDBResource(),
            checkpoint_path=checkpoint,
            latest_basic_reference=reference,
            output_path=tmp_path / "raw-audit.json",
        )
    assert raw_audit["passed"] is True
    assert raw_audit["raw_asset_code_sets_required_equal"] is False
    assert raw_audit["performance"]["batch_count"] == 2
    assert raw_audit["performance"]["raw_data_load_count"] == 2
    assert raw_audit["performance"]["raw_batch_sql_query_count"] == 22
    assert [item["asset_key"] for item in raw_audit["raw_manifest"]] == [
        "raw_tushare_fund_daily",
        "raw_tushare_fund_adj",
        "raw_tushare_fund_daily",
        "raw_tushare_fund_adj",
    ]
    silver_plan = build_etf_daily_silver_bootstrap_plan(
        raw_plan=raw_plan,
        raw_audit_report=raw_audit,
        basic_reference=reference,
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        code_revision="silver-revision",
        coverage_policy_revision=ETF_DAILY_COVERAGE_POLICY_REVISION,
        coverage_review_confirmed=True,
        observed_free_bytes=10**9,
    )
    silver_path = tmp_path / "silver-plan.json"
    write_silver_bootstrap_plan(silver_plan, silver_path)
    run_silver_apply(
        silver_plan=silver_plan,
        raw_plan=raw_plan,
        latest_basic_reference=reference,
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        checkpoint_path=checkpoint,
        output_path=tmp_path / "silver-apply.json",
        confirm_silver_apply=True,
    )
    silver_replay = run_silver_apply(
        silver_plan=silver_plan,
        raw_plan=raw_plan,
        latest_basic_reference=reference,
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=DuckDBResource(),
        checkpoint_path=checkpoint,
        output_path=tmp_path / "silver-apply-replay.json",
        confirm_silver_apply=True,
    )
    assert silver_replay["completed_file_count"] == 4
    expectation = (
        pytest.raises(EtfDailyBootstrapAuditError, match="did not pass")
        if missing_factor
        else nullcontext()
    )
    with expectation:
        run_physical_post_audit(
            raw_plan=raw_plan,
            silver_plan=silver_plan,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb_resource=DuckDBResource(),
            checkpoint_path=checkpoint,
            output_path=tmp_path / "physical.json",
        )
    physical = load_json(tmp_path / "physical.json", label="physical audit")
    assert physical["passed"] is (not missing_factor)
    assert physical["expected_file_count"] == physical["actual_file_count"] == 8
    assert {item["asset_key"] for item in physical["file_evidence"]} == {
        "raw_tushare_fund_daily",
        "raw_tushare_fund_adj",
        "silver_etf_daily",
        "silver_etf_adj_factor",
    }

    if missing_factor:
        from orchestrator.defs.bootstrap.etf_daily_bootstrap_events import (
            EtfDailyBootstrapEventsError,
            build_event_plan,
        )

        for item in physical["file_evidence"]:
            assert Path(item["target_path"]).is_file()
            if item["asset_key"] == "silver_etf_adj_factor":
                assert item["passed"] is False
                assert item["coverage_error_codes"] == ["missing_expected_codes"]
            elif item["asset_key"] == "silver_etf_daily":
                assert item["passed"] is True
                assert item["coverage_warning"] is True
        with pytest.raises(EtfDailyBootstrapEventsError, match="not green"):
            build_event_plan(
                instance=None,
                silver_plan=silver_plan,
                physical_report_path=tmp_path / "physical.json",
            )
        return

    drifted_reference = write_basic_reference(
        lake_root=lake_root,
        staging_root=staging_root,
        rows=(basic_row("510330.SH"), basic_row("159919.SZ")),
    )
    with pytest.raises(EtfDailyBootstrapApplyError, match="Basic changed"):
        run_silver_apply(
            silver_plan=silver_plan,
            raw_plan=raw_plan,
            latest_basic_reference=drifted_reference,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb_resource=DuckDBResource(),
            checkpoint_path=checkpoint,
            output_path=tmp_path / "silver-apply-again.json",
            confirm_silver_apply=True,
        )
    changed_raw = FUND_DAILY_RAW_SPEC.target_path_builder(lake_root, DATES[0])
    changed_raw.unlink()
    write_raw_fixture(
        lake_root=lake_root,
        spec=FUND_DAILY_RAW_SPEC,
        partition_key=DATES[0],
        rows=(_daily_row("159919.SZ", "20250102"),),
    )
    with pytest.raises(EtfDailyBootstrapApplyError, match="Raw manifest drifted"):
        run_silver_apply(
            silver_plan=silver_plan,
            raw_plan=raw_plan,
            latest_basic_reference=reference,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb_resource=DuckDBResource(),
            checkpoint_path=checkpoint,
            output_path=tmp_path / "silver-apply-raw-drift.json",
            confirm_silver_apply=True,
        )


def test_silver_plan_requires_coverage_review_and_exact_policy(tmp_path: Path) -> None:
    _, _, raw_plan = _raw_plan(tmp_path)
    fake_report = {
        "raw_plan_hash": raw_plan.raw_plan_hash,
        "passed": True,
        "dagster_events_written": 0,
    }
    fake_report["report_hash"] = "0" * 64
    with pytest.raises(EtfDailyBootstrapPlanError, match="coverage review"):
        build_etf_daily_silver_bootstrap_plan(
            raw_plan=raw_plan,
            raw_audit_report=fake_report,
            basic_reference=None,  # type: ignore[arg-type]
            lake_root=tmp_path,
            staging_root=tmp_path,
            duckdb_resource=DuckDBResource(),
            code_revision="revision",
            coverage_policy_revision=ETF_DAILY_COVERAGE_POLICY_REVISION,
            coverage_review_confirmed=False,
        )
    with pytest.raises(EtfDailyBootstrapPlanError, match="policy revision"):
        build_etf_daily_silver_bootstrap_plan(
            raw_plan=raw_plan,
            raw_audit_report=fake_report,
            basic_reference=None,  # type: ignore[arg-type]
            lake_root=tmp_path,
            staging_root=tmp_path,
            duckdb_resource=DuckDBResource(),
            code_revision="revision",
            coverage_policy_revision="fund_daily_warn__fund_adj_warn_v1",
            coverage_review_confirmed=True,
        )


def test_cli_rejects_relative_paths_and_requires_phase_confirmation() -> None:
    parser = _parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "raw-plan",
                "--lake-root",
                "relative",
                "--staging-root",
                "/tmp/staging",
                "--output",
                "/tmp/plan.json",
                "--code-revision",
                "revision",
                "--operation-id",
                "op",
            ]
        )
    args = parser.parse_args(
        [
            "raw-plan",
            "--lake-root",
            "/tmp/lake",
            "--staging-root",
            "/tmp/staging",
            "--output",
            "/tmp/plan.json",
            "--code-revision",
            "revision",
            "--operation-id",
            "op",
        ]
    )
    assert args.confirm_raw_plan is False
    assert _confirmation_error(args) == "raw-plan requires --confirm-raw-plan"
    with pytest.raises(EtfDailyBootstrapPlanError, match="approved Lake"):
        _require_formal_roots(
            Path("/Volumes/datasource/goldenshare-tushare-lake"),
            Path("/tmp/staging"),
        )


def test_raw_fields_remain_subset_of_silver_and_never_rename_change() -> None:
    assert FUND_DAILY_SOURCE_COLUMNS[7] == "change"
    assert "change_amount" not in FUND_DAILY_SOURCE_COLUMNS
    assert "discount_rate" in FUND_ADJ_SOURCE_COLUMNS


def test_bootstrap_scheduler_never_builds_a_batch_larger_than_twenty_days() -> None:
    dates = tuple(f"2025-01-{index:02d}" for index in range(1, 22))
    batches = _chunks(dates, 20)
    assert tuple(len(batch) for batch in batches) == (20, 1)
    assert tuple(date for batch in batches for date in batch) == dates


def test_bootstrap_production_modules_keep_lake_and_source_boundaries() -> None:
    bootstrap_dir = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "orchestrator"
        / "defs"
        / "bootstrap"
    )
    sources = "\n".join(
        (bootstrap_dir / name).read_text(encoding="utf-8")
        for name in (
            "etf_daily_bootstrap_plan.py",
            "etf_daily_bootstrap_apply.py",
            "etf_daily_bootstrap_audit.py",
            "etf_daily_bootstrap_events.py",
            "etf_daily_bootstrap_cli.py",
        )
    )
    for forbidden in (
        "goldenshare-tushare-lake",
        "kopia",
        "ProdPostgresResource",
        "_fetch_all_pages",
        "duckdb.connect(",
        "change_amount",
    ):
        assert forbidden not in sources


def _make_parent(path: Path) -> Path:
    path.mkdir()
    return path
