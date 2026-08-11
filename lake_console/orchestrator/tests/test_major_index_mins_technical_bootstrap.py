from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.bootstrap import (
    major_index_mins_technical_bootstrap_cli,
    major_index_mins_technical_bootstrap_events_cli,
)
from orchestrator.defs.bootstrap.major_index_mins_technical_bootstrap_events import (
    MajorIndexMinsTechnicalBootstrapEventsError,
    plan_major_index_mins_technical_bootstrap_events,
    post_audit_major_index_mins_technical_events,
    report_major_index_mins_technical_events,
)
from orchestrator.defs.bootstrap.major_index_mins_technical_history import (
    MajorIndexMinsTechnicalBootstrapError,
    build_major_index_mins_technical_bootstrap_plan,
    build_major_index_mins_technical_candidates,
    promote_major_index_mins_technical_candidates,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import (
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_state_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    expected_major_index_mins_technical_codes,
)

FIRST_DATE = "2009-01-05"
SECOND_DATE = "2009-01-06"
THIRD_DATE = "2009-01-07"


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


def _write_silver_partition(root: Path, *, trade_date: str, freq: int) -> Path:
    path = silver_major_index_mins_path(root, f"{freq}min", trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[object, ...]] = []
    for code_index, code in enumerate(
        expected_major_index_mins_technical_codes(trade_date)
    ):
        for bar_index, trade_time in enumerate(("11:30:00", "15:00:00")):
            close = 10.0 + code_index + bar_index
            rows.append(
                (
                    code,
                    f"{freq}min",
                    f"{trade_date} {trade_time}",
                    close + 1.0,
                    close - 1.0,
                    close,
                )
            )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE silver_rows (
              ts_code VARCHAR,
              freq VARCHAR,
              trade_time TIMESTAMP,
              high DOUBLE,
              low DOUBLE,
              close DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO silver_rows VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM silver_rows ORDER BY ts_code, trade_time",
                path,
            )
        )
    return path


def _write_complete_date(root: Path, trade_date: str) -> None:
    for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
        _write_silver_partition(root, trade_date=trade_date, freq=freq)


def _plan(tmp_path: Path, *, registered_dates: tuple[str, ...] = (FIRST_DATE,)):
    return build_major_index_mins_technical_bootstrap_plan(
        end_date=registered_dates[-1],
        registered_dates=registered_dates,
        source_lake_root=tmp_path / "data_lake",
        staging_root=tmp_path / "data_lake_staging",
        report_root=tmp_path / "reports",
        disk_free_bytes=10**12,
    )


def _promoted_fixture(tmp_path: Path):
    _write_complete_date(tmp_path / "data_lake", FIRST_DATE)
    plan = _plan(tmp_path)
    candidate_report = build_major_index_mins_technical_candidates(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        apply=True,
    )
    promote_report = promote_major_index_mins_technical_candidates(
        plan_report_path=plan.report_path,
        candidate_report_path=candidate_report,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        apply=True,
    )
    return plan, promote_report


def test_plan_hash_is_stable_and_ignores_only_incomplete_tail(tmp_path: Path) -> None:
    _write_complete_date(tmp_path / "data_lake", FIRST_DATE)
    first = _plan(tmp_path, registered_dates=(FIRST_DATE, SECOND_DATE))
    second = build_major_index_mins_technical_bootstrap_plan(
        end_date=SECOND_DATE,
        registered_dates=(FIRST_DATE, SECOND_DATE),
        source_lake_root=tmp_path / "data_lake",
        staging_root=tmp_path / "data_lake_staging",
        report_root=tmp_path / "other-reports",
        disk_free_bytes=10**12,
        write_report=False,
    )

    assert first.plan_hash == second.plan_hash
    assert first.trade_dates == (FIRST_DATE,)
    assert first.ignored_incomplete_tail_dates == (SECOND_DATE,)
    assert len(first.input_files) == len(MAJOR_INDEX_MINS_TECHNICAL_FREQS)


def test_plan_rejects_intermediate_incomplete_silver_date(tmp_path: Path) -> None:
    root = tmp_path / "data_lake"
    _write_complete_date(root, FIRST_DATE)
    _write_complete_date(root, THIRD_DATE)

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapError,
        match="intermediate incomplete date",
    ):
        _plan(
            tmp_path,
            registered_dates=(FIRST_DATE, SECOND_DATE, THIRD_DATE),
        )


def test_candidate_build_is_resumable_from_complete_checkpoint(tmp_path: Path) -> None:
    _write_complete_date(tmp_path / "data_lake", FIRST_DATE)
    plan = _plan(tmp_path)

    first_report = build_major_index_mins_technical_candidates(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        apply=True,
    )
    second_report = build_major_index_mins_technical_candidates(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        apply=True,
    )

    assert first_report == second_report
    for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
        assert gold_major_index_mins_technical_path(
            plan.candidate_root / "candidate_lake", freq, FIRST_DATE
        ).is_file()
        assert gold_major_index_mins_technical_state_path(
            plan.candidate_root / "candidate_lake", freq, FIRST_DATE
        ).is_file()


def test_candidate_build_rejects_partial_uncheckpointed_target(tmp_path: Path) -> None:
    _write_complete_date(tmp_path / "data_lake", FIRST_DATE)
    plan = _plan(tmp_path)
    unexpected = gold_major_index_mins_technical_path(
        plan.candidate_root / "candidate_lake", 1, FIRST_DATE
    )
    unexpected.parent.mkdir(parents=True, exist_ok=True)
    unexpected.write_bytes(b"uncheckpointed")

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapError,
        match="partial candidate pair requires an explicit repair plan",
    ):
        build_major_index_mins_technical_candidates(
            plan_report_path=plan.report_path,
            expected_plan_hash=plan.plan_hash,
            apply=True,
        )


def test_candidate_promotion_moves_all_pairs_and_physically_audits(
    tmp_path: Path,
) -> None:
    _write_complete_date(tmp_path / "data_lake", FIRST_DATE)
    plan = _plan(tmp_path)
    candidate_report = build_major_index_mins_technical_candidates(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        apply=True,
    )

    promote_report = promote_major_index_mins_technical_candidates(
        plan_report_path=plan.report_path,
        candidate_report_path=candidate_report,
        expected_plan_hash=plan.plan_hash,
        duckdb_resource=DuckDBResource(),
        apply=True,
    )

    assert promote_report.is_file()
    for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
        assert gold_major_index_mins_technical_path(
            plan.source_lake_root, freq, FIRST_DATE
        ).is_file()
        assert gold_major_index_mins_technical_state_path(
            plan.source_lake_root, freq, FIRST_DATE
        ).is_file()


def test_candidate_promotion_rejects_partial_formal_pair(tmp_path: Path) -> None:
    _write_complete_date(tmp_path / "data_lake", FIRST_DATE)
    plan = _plan(tmp_path)
    candidate_report = build_major_index_mins_technical_candidates(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        apply=True,
    )
    formal = gold_major_index_mins_technical_path(
        plan.source_lake_root,
        1,
        FIRST_DATE,
    )
    formal.parent.mkdir(parents=True, exist_ok=True)
    formal.write_bytes(b"partial")

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapError,
        match="partial pair",
    ):
        promote_major_index_mins_technical_candidates(
            plan_report_path=plan.report_path,
            candidate_report_path=candidate_report,
            expected_plan_hash=plan.plan_hash,
            apply=True,
        )


def test_events_require_existing_minute_partitions_and_confirmation(
    tmp_path: Path,
) -> None:
    plan, promote_report = _promoted_fixture(tmp_path)
    instance = BootstrapEventInstance()

    dry_run = plan_major_index_mins_technical_bootstrap_events(
        instance=instance,
        plan_report_path=plan.report_path,
        promote_report_path=promote_report,
        expected_plan_hash=plan.plan_hash,
    )
    assert dry_run.should_stop is True
    assert dry_run.missing_registered_dates == (FIRST_DATE,)
    assert dry_run.planned_materialization_count == 14
    assert dry_run.planned_check_count == 70
    assert instance.events == []

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapEventsError,
        match="confirm_event_write",
    ):
        report_major_index_mins_technical_events(
            instance=instance,
            plan_report_path=plan.report_path,
            promote_report_path=promote_report,
            expected_plan_hash=plan.plan_hash,
            dry_run=False,
            sample_only=True,
            sample_date=FIRST_DATE,
        )


def test_events_sample_then_full_apply_are_idempotent(tmp_path: Path) -> None:
    plan, promote_report = _promoted_fixture(tmp_path)
    instance = BootstrapEventInstance()
    instance.dynamic_partitions.append(FIRST_DATE)

    sample = report_major_index_mins_technical_events(
        instance=instance,
        plan_report_path=plan.report_path,
        promote_report_path=promote_report,
        expected_plan_hash=plan.plan_hash,
        dry_run=False,
        confirm_event_write=True,
        sample_only=True,
        sample_date=FIRST_DATE,
    )
    assert sample.reported_materialization_count == 14
    assert sample.reported_check_count == 70

    full = report_major_index_mins_technical_events(
        instance=instance,
        plan_report_path=plan.report_path,
        promote_report_path=promote_report,
        expected_plan_hash=plan.plan_hash,
        dry_run=False,
        confirm_event_write=True,
    )
    assert full.reported_materialization_count == 0
    assert full.reported_check_count == 0
    audited = post_audit_major_index_mins_technical_events(
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
    active_instance.dynamic_partitions.append(FIRST_DATE)

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapEventsError,
        match="active runs",
    ):
        report_major_index_mins_technical_events(
            instance=active_instance,
            plan_report_path=plan.report_path,
            promote_report_path=promote_report,
            expected_plan_hash=plan.plan_hash,
            dry_run=False,
            confirm_event_write=True,
        )

    gold_major_index_mins_technical_path(
        plan.source_lake_root,
        1,
        FIRST_DATE,
    ).write_bytes(b"changed")
    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapEventsError,
        match="changed",
    ):
        plan_major_index_mins_technical_bootstrap_events(
            instance=BootstrapEventInstance(),
            plan_report_path=plan.report_path,
            promote_report_path=promote_report,
            expected_plan_hash=plan.plan_hash,
        )


@pytest.mark.parametrize(
    "argv",
    (
        [
            "build-candidates",
            "--plan-report",
            "plan.json",
            "--expected-plan-hash",
            "hash",
        ],
        [
            "promote",
            "--plan-report",
            "plan.json",
            "--expected-plan-hash",
            "hash",
            "--candidate-report",
            "candidate.json",
        ],
    ),
)
def test_bootstrap_cli_requires_phase_specific_write_confirmation(
    argv: list[str],
) -> None:
    assert major_index_mins_technical_bootstrap_cli.main(argv) == 2


def test_event_cli_requires_event_confirmation() -> None:
    with pytest.raises(SystemExit) as error:
        major_index_mins_technical_bootstrap_events_cli.main(
            [
                "sample",
                "--plan-report",
                "plan.json",
                "--promote-report",
                "promote.json",
                "--expected-plan-hash",
                "hash",
                "--sample-date",
                FIRST_DATE,
                "--output",
                "out.json",
            ]
        )
    assert error.value.code == 2
