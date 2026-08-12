import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import (
    idx_factor_pro_bootstrap_cli,
    idx_factor_pro_bootstrap_events_cli,
)
from orchestrator.defs.bootstrap.idx_factor_pro_bootstrap_events import (
    IdxFactorProBootstrapEventsError,
    plan_idx_factor_pro_bootstrap_events,
    post_audit_idx_factor_pro_events,
    register_idx_factor_pro_partitions,
    report_idx_factor_pro_events,
)
from orchestrator.defs.bootstrap.idx_factor_pro_bootstrap_plan import (
    IdxFactorProBootstrapPlanError,
    build_idx_factor_pro_bootstrap_plan,
)
from orchestrator.defs.bootstrap.idx_factor_pro_bootstrap_promote import (
    IdxFactorProBootstrapPromoteError,
    promote_idx_factor_pro_candidates,
)
from orchestrator.defs.bootstrap.idx_factor_pro_bootstrap_stage import (
    IdxFactorProBootstrapStageError,
    build_idx_factor_pro_candidates,
    stage_idx_factor_pro_source,
)
from orchestrator.defs.paths import (
    raw_idx_factor_pro_path,
    silver_index_factor_pro_path,
)
from orchestrator.defs.resources import DuckDBResource, TushareResult
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_FIRST_AVAILABLE_TRADE_DATES,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    active_idx_factor_pro_daily_codes,
)
from tests._idx_factor_pro_helpers import idx_factor_pro_row


class BootstrapTushare:
    def __init__(self, rows_by_code: dict[str, list[dict[str, object]]]) -> None:
        self.rows_by_code = rows_by_code
        self.calls: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def call(self, api_name, params, fields) -> TushareResult:
        request_params = dict(params)
        request_fields = tuple(fields)
        self.calls.append((api_name, request_params, request_fields))
        rows = self.rows_by_code.get(str(request_params["ts_code"]), [])
        offset = int(request_params["offset"])
        limit = int(request_params["limit"])
        return TushareResult(
            rows=rows[offset : offset + limit],
            columns=IDX_FACTOR_PRO_SOURCE_COLUMNS,
            metadata={},
        )


class BootstrapEventInstance:
    def __init__(self, *, active_run: bool = False) -> None:
        self.active_run = active_run
        self.dynamic_partitions: list[str] = []
        self.events: list[object] = []
        self.materializations: dict[tuple[str, str], SimpleNamespace] = {}
        self.check_records: dict[tuple[str, str], list[SimpleNamespace]] = {}
        self.event_log_storage = self

    def get_runs(self, *, filters, limit: int):
        del filters, limit
        return [object()] if self.active_run else []

    def get_dynamic_partitions(self, name: str) -> list[str]:
        del name
        return list(self.dynamic_partitions)

    def add_dynamic_partitions(self, name: str, keys: list[str]) -> None:
        del name
        self.dynamic_partitions.extend(
            value for value in keys if value not in self.dynamic_partitions
        )

    def get_materialized_partitions(self, asset_key: dg.AssetKey) -> set[str]:
        label = asset_key.to_user_string()
        return {
            partition
            for (asset, partition), _record in self.materializations.items()
            if asset == label
        }

    def fetch_materializations(self, record_filter, limit: int = 1):
        asset = record_filter.asset_key.to_user_string()
        partitions = set(record_filter.asset_partitions or ())
        records = [
            record
            for (candidate_asset, partition), record in self.materializations.items()
            if candidate_asset == asset and (not partitions or partition in partitions)
        ]
        records.sort(key=lambda value: value.storage_id, reverse=True)
        return SimpleNamespace(records=records[:limit])

    def get_asset_check_execution_history(self, check_key, limit: int):
        key = (check_key.asset_key.to_user_string(), check_key.name)
        return list(reversed(self.check_records.get(key, ())))[:limit]

    def report_runless_asset_event(self, event: object) -> None:
        self.events.append(event)
        if isinstance(event, dg.AssetMaterialization):
            asset = event.asset_key.to_user_string()
            storage_id = len(self.events)
            self.materializations[(asset, str(event.partition))] = SimpleNamespace(
                storage_id=storage_id,
                run_id="runless",
                timestamp=float(storage_id),
                partition_key=str(event.partition),
            )
            return
        if isinstance(event, dg.AssetCheckEvaluation):
            key = (event.asset_key.to_user_string(), event.check_name)
            self.check_records.setdefault(key, []).append(
                SimpleNamespace(
                    partition=event.partition,
                    event=SimpleNamespace(
                        dagster_event=SimpleNamespace(event_specific_data=event)
                    ),
                )
            )


def _plan(
    tmp_path: Path,
    *,
    trade_dates: tuple[str, ...] = ("2025-01-17",),
    write_report: bool = True,
):
    return build_idx_factor_pro_bootstrap_plan(
        end_date=trade_dates[-1],
        lake_root=tmp_path / "data_lake",
        staging_root=tmp_path / "data_lake_staging",
        report_root=tmp_path / "reports",
        trade_dates=trade_dates,
        disk_free_bytes=10**12,
        write_report=write_report,
    )


def _promoted_fixture(tmp_path: Path):
    plan = _plan(tmp_path)
    codes = active_idx_factor_pro_daily_codes("2025-01-17")
    source = BootstrapTushare(
        {code: [idx_factor_pro_row(code, "20250117")] for code in codes}
    )
    source_report = stage_idx_factor_pro_source(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        tushare=source,  # type: ignore[arg-type]
        apply=True,
    )
    candidate_report = build_idx_factor_pro_candidates(
        plan_report_path=plan.report_path,
        source_report_path=source_report,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        apply=True,
    )
    promote_report = promote_idx_factor_pro_candidates(
        plan_report_path=plan.report_path,
        candidate_report_path=candidate_report,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        apply=True,
    )
    return plan, promote_report


def test_plan_hash_is_stable_and_000680_enters_on_source_first_date(
    tmp_path: Path,
) -> None:
    first = _plan(tmp_path, write_report=False)
    second = _plan(tmp_path, write_report=False)

    assert first.plan_hash == second.plan_hash
    assert "000680.SH" not in active_idx_factor_pro_daily_codes("2025-01-16")
    assert "000680.SH" in active_idx_factor_pro_daily_codes("2025-01-17")
    code_plan = next(value for value in first.code_plans if value.ts_code == "000680.SH")
    assert code_plan.source_start_date == "2025-01-17"
    assert code_plan.effective_start_date == "2025-01-17"
    assert code_plan.max_request_count == 1


def test_plan_rejects_space_budget_failure(tmp_path: Path) -> None:
    plan = build_idx_factor_pro_bootstrap_plan(
        end_date="2025-01-17",
        lake_root=tmp_path / "data_lake",
        staging_root=tmp_path / "data_lake_staging",
        report_root=tmp_path / "reports",
        trade_dates=("2025-01-17",),
        disk_free_bytes=0,
        write_report=False,
    )

    assert plan.disk_budget.passed is False


def test_source_stage_pages_by_code_and_stops_on_short_page(tmp_path: Path) -> None:
    start = date.fromisoformat(IDX_FACTOR_PRO_FIRST_AVAILABLE_TRADE_DATES["000001.SH"])
    source_dates = tuple(
        (start + timedelta(days=index)).isoformat() for index in range(8_001)
    )
    trade_dates = (*source_dates, "2025-01-17")
    plan = _plan(tmp_path, trade_dates=trade_dates)
    rows = [
        idx_factor_pro_row("000001.SH", value.replace("-", ""))
        for value in source_dates
    ]
    source = BootstrapTushare({"000001.SH": rows})

    report_path = stage_idx_factor_pro_source(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        tushare=source,  # type: ignore[arg-type]
        apply=True,
        selected_codes=("000001.SH",),
    )

    assert report_path.is_file()
    assert len(source.calls) == 2
    assert [value[1]["offset"] for value in source.calls] == [0, 8_000]
    assert all(value[1]["ts_code"] == "000001.SH" for value in source.calls)


def test_source_stage_rejects_another_code(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    source = BootstrapTushare(
        {"000001.SH": [idx_factor_pro_row("399001.SZ", "20250117")]}
    )

    with pytest.raises(IdxFactorProBootstrapStageError, match="another code"):
        stage_idx_factor_pro_source(
            plan_report_path=plan.report_path,
            expected_plan_hash=plan.plan_hash,
            tushare=source,  # type: ignore[arg-type]
            apply=True,
            selected_codes=("000001.SH",),
        )


def test_full_source_candidate_and_formal_promotion(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    codes = active_idx_factor_pro_daily_codes("2025-01-17")
    source = BootstrapTushare(
        {
            code: [idx_factor_pro_row(code, "20250117")]
            for code in codes
        }
    )
    source_report = stage_idx_factor_pro_source(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        tushare=source,  # type: ignore[arg-type]
        apply=True,
    )
    candidate_report = build_idx_factor_pro_candidates(
        plan_report_path=plan.report_path,
        source_report_path=source_report,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        apply=True,
    )

    promote_report = promote_idx_factor_pro_candidates(
        plan_report_path=plan.report_path,
        candidate_report_path=candidate_report,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        apply=True,
    )

    assert promote_report.is_file()
    assert raw_idx_factor_pro_path(plan.lake_root, "2025-01-17").is_file()
    assert silver_index_factor_pro_path(plan.lake_root, "2025-01-17").is_file()


def test_source_estimate_may_differ_before_seed_but_candidate_stays_strict(
    tmp_path: Path,
) -> None:
    pre_seed_date = "1991-09-30"
    candidate_date = "2025-01-17"
    plan = _plan(tmp_path, trade_dates=(pre_seed_date, candidate_date))
    codes = active_idx_factor_pro_daily_codes(candidate_date)
    rows_by_code = {
        code: [idx_factor_pro_row(code, candidate_date.replace("-", ""))]
        for code in codes
    }
    rows_by_code["000001.SH"].insert(
        0, idx_factor_pro_row("000001.SH", pre_seed_date.replace("-", ""))
    )
    source = BootstrapTushare(rows_by_code)

    source_report = stage_idx_factor_pro_source(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        tushare=source,  # type: ignore[arg-type]
        apply=True,
    )
    source_payload = json.loads(source_report.read_text(encoding="utf-8"))

    assert source_payload["row_count"] == plan.estimated_source_row_count - 1
    assert source_payload["row_count_delta"] == -1
    candidate_report = build_idx_factor_pro_candidates(
        plan_report_path=plan.report_path,
        source_report_path=source_report,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        apply=True,
    )
    candidate_payload = json.loads(candidate_report.read_text(encoding="utf-8"))
    assert candidate_payload["raw_row_count"] == len(codes)


def test_formal_promotion_rejects_conflicting_target(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    codes = active_idx_factor_pro_daily_codes("2025-01-17")
    source = BootstrapTushare(
        {code: [idx_factor_pro_row(code, "20250117")] for code in codes}
    )
    source_report = stage_idx_factor_pro_source(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        tushare=source,  # type: ignore[arg-type]
        apply=True,
    )
    candidate_report = build_idx_factor_pro_candidates(
        plan_report_path=plan.report_path,
        source_report_path=source_report,
        expected_plan_hash=plan.plan_hash,
        apply=True,
    )
    formal = raw_idx_factor_pro_path(plan.lake_root, "2025-01-17")
    formal.parent.mkdir(parents=True, exist_ok=True)
    formal.write_bytes(b"conflict")

    with pytest.raises(
        IdxFactorProBootstrapPromoteError,
        match="conflicts with candidate manifest",
    ):
        promote_idx_factor_pro_candidates(
            plan_report_path=plan.report_path,
            candidate_report_path=candidate_report,
            expected_plan_hash=plan.plan_hash,
            apply=True,
        )


def test_plan_loader_rejects_wrong_expected_hash(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    with pytest.raises(IdxFactorProBootstrapPlanError, match="expected plan hash"):
        build_idx_factor_pro_candidates(
            plan_report_path=plan.report_path,
            source_report_path=tmp_path / "missing.json",
            expected_plan_hash="wrong",
            apply=True,
        )


def test_events_require_separate_partition_and_event_confirmations(
    tmp_path: Path,
) -> None:
    plan, promote_report = _promoted_fixture(tmp_path)
    instance = BootstrapEventInstance()

    dry_run = plan_idx_factor_pro_bootstrap_events(
        instance=instance,
        plan_report_path=plan.report_path,
        promote_report_path=promote_report,
        expected_plan_hash=plan.plan_hash,
        require_registered=True,
    )
    assert dry_run.should_stop is True
    assert dry_run.missing_registered_dates == ("2025-01-17",)
    assert instance.events == []

    with pytest.raises(
        IdxFactorProBootstrapEventsError,
        match="confirm_partition_write",
    ):
        register_idx_factor_pro_partitions(
            instance=instance,
            plan_report_path=plan.report_path,
            promote_report_path=promote_report,
            expected_plan_hash=plan.plan_hash,
            apply=True,
        )
    registered = register_idx_factor_pro_partitions(
        instance=instance,
        plan_report_path=plan.report_path,
        promote_report_path=promote_report,
        expected_plan_hash=plan.plan_hash,
        apply=True,
        confirm_partition_write=True,
    )
    assert registered.registered_partition_count == 1

    with pytest.raises(IdxFactorProBootstrapEventsError, match="confirm_event_write"):
        report_idx_factor_pro_events(
            instance=instance,
            plan_report_path=plan.report_path,
            promote_report_path=promote_report,
            expected_plan_hash=plan.plan_hash,
            dry_run=False,
            sample_date="2025-01-17",
            sample_only=True,
        )


def test_events_sample_then_full_apply_are_idempotent(tmp_path: Path) -> None:
    plan, promote_report = _promoted_fixture(tmp_path)
    instance = BootstrapEventInstance()
    register_idx_factor_pro_partitions(
        instance=instance,
        plan_report_path=plan.report_path,
        promote_report_path=promote_report,
        expected_plan_hash=plan.plan_hash,
        apply=True,
        confirm_partition_write=True,
    )

    sample = report_idx_factor_pro_events(
        instance=instance,
        plan_report_path=plan.report_path,
        promote_report_path=promote_report,
        expected_plan_hash=plan.plan_hash,
        dry_run=False,
        confirm_event_write=True,
        sample_only=True,
        sample_date="2025-01-17",
    )
    assert sample.reported_materialization_count == 2
    assert sample.reported_check_count == 8

    checkpoint_path = tmp_path / "events-checkpoint.json"
    full = report_idx_factor_pro_events(
        instance=instance,
        plan_report_path=plan.report_path,
        promote_report_path=promote_report,
        expected_plan_hash=plan.plan_hash,
        dry_run=False,
        confirm_event_write=True,
        checkpoint_path=checkpoint_path,
    )
    assert full.reported_materialization_count == 0
    assert full.reported_check_count == 0
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["mode"] == "apply"
    assert checkpoint["plan"]["plan_hash"] == plan.plan_hash
    audited = post_audit_idx_factor_pro_events(
        instance=instance,
        plan_report_path=plan.report_path,
        promote_report_path=promote_report,
        expected_plan_hash=plan.plan_hash,
    )
    assert audited.planned_materialization_count == 0
    assert audited.planned_check_count == 0


def test_events_reject_active_runs_and_changed_formal_files(tmp_path: Path) -> None:
    plan, promote_report = _promoted_fixture(tmp_path)
    active_instance = BootstrapEventInstance(active_run=True)
    active_instance.dynamic_partitions.append("2025-01-17")

    with pytest.raises(IdxFactorProBootstrapEventsError, match="active runs"):
        report_idx_factor_pro_events(
            instance=active_instance,
            plan_report_path=plan.report_path,
            promote_report_path=promote_report,
            expected_plan_hash=plan.plan_hash,
            dry_run=False,
            confirm_event_write=True,
        )

    raw_idx_factor_pro_path(plan.lake_root, "2025-01-17").write_bytes(b"changed")
    with pytest.raises(IdxFactorProBootstrapEventsError, match="changed"):
        plan_idx_factor_pro_bootstrap_events(
            instance=BootstrapEventInstance(),
            plan_report_path=plan.report_path,
            promote_report_path=promote_report,
            expected_plan_hash=plan.plan_hash,
        )


@pytest.mark.parametrize(
    ("argv", "expected_code"),
    (
        (
            [
                "stage-source",
                "--plan-report",
                "plan.json",
                "--expected-plan-hash",
                "hash",
            ],
            2,
        ),
        (
            [
                "build-candidates",
                "--plan-report",
                "plan.json",
                "--expected-plan-hash",
                "hash",
                "--source-report",
                "source.json",
            ],
            2,
        ),
        (
            [
                "promote",
                "--plan-report",
                "plan.json",
                "--expected-plan-hash",
                "hash",
                "--candidate-report",
                "candidate.json",
            ],
            2,
        ),
    ),
)
def test_bootstrap_cli_requires_phase_specific_write_confirmation(
    argv: list[str], expected_code: int
) -> None:
    assert idx_factor_pro_bootstrap_cli.main(argv) == expected_code


@pytest.mark.parametrize(
    "argv",
    (
        [
            "register-partitions",
            "--plan-report",
            "plan.json",
            "--promote-report",
            "promote.json",
            "--expected-plan-hash",
            "hash",
            "--output",
            "out.json",
        ],
        [
            "sample",
            "--plan-report",
            "plan.json",
            "--promote-report",
            "promote.json",
            "--expected-plan-hash",
            "hash",
            "--sample-date",
            "2025-01-17",
            "--output",
            "out.json",
        ],
    ),
)
def test_event_cli_requires_separate_partition_or_event_confirmation(
    argv: list[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        idx_factor_pro_bootstrap_events_cli.main(argv)
    assert error.value.code == 2


def test_event_cli_requires_checkpoint_only_for_full_apply() -> None:
    common = [
        "--plan-report",
        "plan.json",
        "--promote-report",
        "promote.json",
        "--expected-plan-hash",
        "hash",
        "--output",
        "out.json",
        "--confirm-event-write",
    ]
    with pytest.raises(SystemExit) as missing_checkpoint:
        idx_factor_pro_bootstrap_events_cli.main(["apply", *common])
    assert missing_checkpoint.value.code == 2

    with pytest.raises(SystemExit) as sample_checkpoint:
        idx_factor_pro_bootstrap_events_cli.main(
            [
                "sample",
                *common,
                "--sample-date",
                "2025-01-17",
                "--checkpoint",
                "checkpoint.json",
            ]
        )
    assert sample_checkpoint.value.code == 2
