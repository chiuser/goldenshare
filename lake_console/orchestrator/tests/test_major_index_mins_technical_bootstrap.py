import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.bootstrap import (
    major_index_mins_technical_bootstrap_cli,
    major_index_mins_technical_bootstrap_events_cli,
    major_index_mins_technical_history,
)
from orchestrator.defs.bootstrap.major_index_mins_technical_bootstrap_events import (
    MajorIndexMinsTechnicalBootstrapEventsError,
    plan_major_index_mins_technical_bootstrap_events,
    post_audit_major_index_mins_technical_events,
    report_major_index_mins_technical_events,
)
from orchestrator.defs.bootstrap.major_index_mins_technical_history import (
    MajorIndexMinsTechnicalBootstrapError,
    MinuteTechnicalBootstrapPlan,
    MinuteTechnicalInputFile,
    build_major_index_mins_technical_bootstrap_plan,
    build_major_index_mins_technical_candidates,
    build_major_index_mins_technical_performance_sample,
    load_major_index_mins_technical_bootstrap_plan,
    promote_major_index_mins_technical_candidates,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io.major_index_mins_technical_writer import (
    MajorIndexMinsTechnicalValidationError,
)
from orchestrator.defs.paths import (
    gold_major_index_mins_path,
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_state_path,
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


def _write_gold_bar_partition(root: Path, *, trade_date: str, freq: int) -> Path:
    path = gold_major_index_mins_path(root, freq, trade_date)
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
                    freq,
                    trade_date,
                    f"{trade_date} {trade_time}",
                    close,
                    close + 1.0,
                    close - 1.0,
                    close,
                    1.0,
                    close,
                    "SSE",
                    close,
                )
            )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE gold_rows (
              ts_code VARCHAR,
              freq INTEGER,
              trade_date DATE,
              trade_time TIMESTAMP,
              open DOUBLE,
              high DOUBLE,
              low DOUBLE,
              close DOUBLE,
              vol DOUBLE,
              amount DOUBLE,
              exchange VARCHAR,
              vwap DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO gold_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM gold_rows ORDER BY ts_code, trade_time",
                path,
            )
        )
    return path


def _write_complete_date(root: Path, trade_date: str) -> None:
    for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
        _write_gold_bar_partition(root, trade_date=trade_date, freq=freq)


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


def _performance_sample_plan(tmp_path: Path) -> MinuteTechnicalBootstrapPlan:
    trade_dates = tuple(
        (date.fromisoformat(FIRST_DATE) + timedelta(days=offset)).isoformat()
        for offset in range(60)
    )
    inputs = tuple(
        MinuteTechnicalInputFile(
            trade_date=trade_date,
            freq=freq,
            path=str(tmp_path / "data_lake" / f"{trade_date}-{freq}.parquet"),
            row_count=2,
            size_bytes=1,
            sha256="unused-by-mocked-loader",
        )
        for trade_date in trade_dates
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
    )
    return MinuteTechnicalBootstrapPlan(
        generated_at="2026-08-12T00:00:00+00:00",
        end_date=trade_dates[-1],
        source_lake_root=tmp_path / "data_lake",
        staging_root=tmp_path / "data_lake_staging",
        report_root=tmp_path / "reports",
        trade_dates=trade_dates,
        ignored_incomplete_tail_dates=(),
        input_files=inputs,
        source_manifest_hash="source",
        object_pool_hash="pool",
        schema_contract_hash="schema",
        estimated_output_bytes=1,
        disk_free_bytes=10**12,
        plan_hash="sample-plan-hash",
        report_path=tmp_path / "reports" / "plan.json",
    )


def _install_performance_sample_fakes(
    monkeypatch: pytest.MonkeyPatch,
    plan: MinuteTechnicalBootstrapPlan,
) -> list[tuple[str, int]]:
    calls: list[tuple[str, int]] = []

    def fake_load(*_args, **_kwargs) -> MinuteTechnicalBootstrapPlan:
        return plan

    def fake_write(**kwargs):
        trade_date = str(kwargs["partition_key"])
        freq = int(kwargs["freq"])
        target_root = Path(kwargs["target_lake_root_path"])
        technical_path = gold_major_index_mins_technical_path(
            target_root, freq, trade_date
        )
        state_path = gold_major_index_mins_technical_state_path(
            target_root, freq, trade_date
        )
        technical_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        technical_path.write_bytes(f"technical:{trade_date}:{freq}".encode())
        state_path.write_bytes(f"state:{trade_date}:{freq}".encode())
        calls.append((trade_date, freq))
        return SimpleNamespace(
            technical_path=technical_path,
            state_path=state_path,
            technical_row_count=2,
            state_row_count=len(expected_major_index_mins_technical_codes(trade_date)),
            input_row_count=2,
            elapsed_ms=10.0,
        )

    monkeypatch.setattr(
        major_index_mins_technical_history,
        "load_major_index_mins_technical_bootstrap_plan",
        fake_load,
    )
    monkeypatch.setattr(
        major_index_mins_technical_history,
        "write_major_index_mins_technical_partition",
        fake_write,
    )
    return calls


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
    assert {value.row_count for value in first.input_files} == {
        len(expected_major_index_mins_technical_codes(FIRST_DATE)) * 2
    }
    assert first.hash_payload()["schema_version"] == 2


def test_plan_rejects_intermediate_incomplete_gold_bar_date(tmp_path: Path) -> None:
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


def test_plan_rejects_legacy_manifest_without_input_row_counts(tmp_path: Path) -> None:
    _write_complete_date(tmp_path / "data_lake", FIRST_DATE)
    plan = _plan(tmp_path)
    payload = json.loads(plan.report_path.read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    for value in payload["input_files"]:
        value.pop("row_count")
    plan.report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapError,
        match="must be regenerated with schema_version=2",
    ):
        load_major_index_mins_technical_bootstrap_plan(
            plan.report_path,
            expected_plan_hash=plan.plan_hash,
        )


def test_plan_loader_rejects_expected_hash_and_same_size_input_drift(
    tmp_path: Path,
) -> None:
    _write_complete_date(tmp_path / "data_lake", FIRST_DATE)
    plan = _plan(tmp_path)

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapError,
        match="expected plan hash mismatch",
    ):
        load_major_index_mins_technical_bootstrap_plan(
            plan.report_path,
            expected_plan_hash="another-plan",
        )

    source_path = Path(plan.input_files[0].path)
    content = bytearray(source_path.read_bytes())
    content[len(content) // 2] ^= 1
    source_path.write_bytes(content)
    assert source_path.stat().st_size == plan.input_files[0].size_bytes

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapError,
        match="input hash changed",
    ):
        load_major_index_mins_technical_bootstrap_plan(
            plan.report_path,
            expected_plan_hash=plan.plan_hash,
        )


@pytest.mark.parametrize("sample_date_count", (21, 30, 100))
def test_performance_sample_rejects_arbitrary_date_counts(
    tmp_path: Path,
    sample_date_count: int,
) -> None:
    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapError,
        match="exactly 20 or 60",
    ):
        build_major_index_mins_technical_performance_sample(
            plan_report_path=tmp_path / "plan.json",
            expected_plan_hash="hash",
            sample_date_count=sample_date_count,
            apply=True,
        )


def test_performance_sample_resumes_from_20_to_60_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _performance_sample_plan(tmp_path)
    calls = _install_performance_sample_fakes(monkeypatch, plan)

    report_20 = build_major_index_mins_technical_performance_sample(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        sample_date_count=20,
        apply=True,
    )
    payload_20 = json.loads(report_20.read_text(encoding="utf-8"))
    first_hashes = {value["path"]: value["sha256"] for value in payload_20["files"]}
    assert len(calls) == 20 * len(MAJOR_INDEX_MINS_TECHNICAL_FREQS)

    report_60 = build_major_index_mins_technical_performance_sample(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        sample_date_count=60,
        apply=True,
    )
    payload_60 = json.loads(report_60.read_text(encoding="utf-8"))

    assert len(calls) == 60 * len(MAJOR_INDEX_MINS_TECHNICAL_FREQS)
    assert calls[: len(MAJOR_INDEX_MINS_TECHNICAL_FREQS)] == [
        (plan.trade_dates[0], freq) for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
    ]
    assert payload_20["report_type"] == "performance_sample"
    assert payload_20["promotion_eligible"] is False
    assert payload_20["writes"] == {
        "sample_files": 280,
        "candidate_files": 0,
        "formal_lake": 0,
        "dagster_events": 0,
    }
    assert payload_60["writes"]["sample_files"] == 840
    assert len(payload_60["completed_dates"]) == 60
    assert len(payload_60["measurements"]) == 60 * 7
    assert payload_60["summary"]["total_input_rows"] == 60 * 7 * 2
    assert payload_60["summary"]["peak_rss_bytes"] > 0
    assert all(
        value["sha256"] == first_hashes[value["path"]]
        for value in payload_60["files"][:280]
    )
    assert not (plan.candidate_root / "candidate_lake").exists()
    assert not plan.source_lake_root.exists()


def test_performance_sample_checkpoints_only_complete_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _performance_sample_plan(tmp_path)
    _install_performance_sample_fakes(monkeypatch, plan)
    working_writer = (
        major_index_mins_technical_history.write_major_index_mins_technical_partition
    )

    def fail_during_first_date(**kwargs):
        if int(kwargs["freq"]) == 30:
            raise MajorIndexMinsTechnicalValidationError("controlled failure")
        return working_writer(**kwargs)

    monkeypatch.setattr(
        major_index_mins_technical_history,
        "write_major_index_mins_technical_partition",
        fail_during_first_date,
    )

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapError,
        match="performance sample writer failed",
    ):
        build_major_index_mins_technical_performance_sample(
            plan_report_path=plan.report_path,
            expected_plan_hash=plan.plan_hash,
            sample_date_count=20,
            apply=True,
        )

    checkpoint = plan.performance_sample_root / "performance-sample-checkpoint.json"
    assert not checkpoint.exists()


def test_performance_sample_rejects_partial_uncheckpointed_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _performance_sample_plan(tmp_path)
    _install_performance_sample_fakes(monkeypatch, plan)
    sample_lake = plan.performance_sample_root / "sample_lake"
    partial = gold_major_index_mins_technical_path(sample_lake, 1, plan.trade_dates[0])
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"partial")

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapError,
        match="partial performance-sample pair",
    ):
        build_major_index_mins_technical_performance_sample(
            plan_report_path=plan.report_path,
            expected_plan_hash=plan.plan_hash,
            sample_date_count=20,
            apply=True,
        )


def test_performance_sample_rejects_frozen_row_count_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _performance_sample_plan(tmp_path)
    _install_performance_sample_fakes(monkeypatch, plan)
    first = plan.input_files[0]
    plan = replace(
        plan,
        input_files=(
            replace(first, row_count=first.row_count + 1),
            *plan.input_files[1:],
        ),
    )
    monkeypatch.setattr(
        major_index_mins_technical_history,
        "load_major_index_mins_technical_bootstrap_plan",
        lambda *_args, **_kwargs: plan,
    )

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapError,
        match="frozen manifest",
    ):
        build_major_index_mins_technical_performance_sample(
            plan_report_path=plan.report_path,
            expected_plan_hash=plan.plan_hash,
            sample_date_count=20,
            apply=True,
        )


def test_formal_promotion_rejects_performance_sample_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _performance_sample_plan(tmp_path)
    _install_performance_sample_fakes(monkeypatch, plan)
    sample_report = build_major_index_mins_technical_performance_sample(
        plan_report_path=plan.report_path,
        expected_plan_hash=plan.plan_hash,
        sample_date_count=20,
        apply=True,
    )

    with pytest.raises(
        MajorIndexMinsTechnicalBootstrapError,
        match="only accepts a full candidate report",
    ):
        promote_major_index_mins_technical_candidates(
            plan_report_path=plan.report_path,
            candidate_report_path=sample_report,
            expected_plan_hash=plan.plan_hash,
            apply=True,
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
            "sample-candidates",
            "--plan-report",
            "plan.json",
            "--expected-plan-hash",
            "hash",
            "--sample-date-count",
            "20",
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
    ]
    with pytest.raises(SystemExit) as missing_checkpoint:
        major_index_mins_technical_bootstrap_events_cli.main(
            ["apply", *common, "--confirm-event-write"]
        )
    assert missing_checkpoint.value.code == 2

    with pytest.raises(SystemExit) as dry_run_checkpoint:
        major_index_mins_technical_bootstrap_events_cli.main(
            ["dry-run", *common, "--checkpoint", "checkpoint.json"]
        )
    assert dry_run_checkpoint.value.code == 2


def test_event_cli_passes_checkpoint_to_full_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        major_index_mins_technical_bootstrap_events_cli.dg.DagsterInstance,
        "get",
        lambda: object(),
    )

    def fake_report(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(
        major_index_mins_technical_bootstrap_events_cli,
        "report_major_index_mins_technical_events",
        fake_report,
    )
    monkeypatch.setattr(
        major_index_mins_technical_bootstrap_events_cli,
        "write_major_index_mins_technical_event_report",
        lambda _report, output: output.write_text("{}", encoding="utf-8"),
    )
    output = tmp_path / "out.json"
    checkpoint = tmp_path / "checkpoint.json"

    assert (
        major_index_mins_technical_bootstrap_events_cli.main(
            [
                "apply",
                "--plan-report",
                "plan.json",
                "--promote-report",
                "promote.json",
                "--expected-plan-hash",
                "hash",
                "--output",
                str(output),
                "--checkpoint",
                str(checkpoint),
                "--confirm-event-write",
            ]
        )
        == 0
    )
    assert captured["dry_run"] is False
    assert captured["sample_only"] is False
    assert captured["checkpoint_path"] == checkpoint
