"""Execution substeps against temporary files and a real isolated Dagster instance.

The reused fixture has independent literal old/new rows from LLD11.9 and the
current Raw/Silver producer contract. Its other 25 dates are shape-only. The
separate full fixture uses literal 26x1650 originals for full isolated stages;
neither fixture is evidence of formal execution or real source completeness.
"""

import json
import os
import re
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.asset_guards.etf_adj_factor_history_completion import (
    CompletionBasicCache,
    PreparedCompletionBasic,
)
from orchestrator.defs.bootstrap import etf_adj_factor_history_completion as execution
from orchestrator.defs.bootstrap.etf_adj_factor_history_completion_cli import (
    CompletionDuckDBResource,
    main,
    run_stage,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import audit_etf_daily_raw_relation
from orchestrator.defs.io.etf_daily_silver_writer import audit_etf_daily_silver_relation
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.etf_basic import (
    SILVER_ETF_BASIC_CHECKS,
    build_etf_basic_silver_snapshot_reference,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_FACTOR_COMPLETION_METADATA_KEY,
    SILVER_ETF_ADJ_FACTOR_JOB_NAME,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from tests import test_etf_adj_factor_history_completion as source_fixture
from tests.etf_daily_test_support import basic_row, make_roots, write_basic_reference
from tests.test_etf_adj_factor_history_completion import (
    ASSET,
    DAY,
    latest,
)

completion = source_fixture.completion


@pytest.fixture(autouse=True)
def controlled_duckdb(monkeypatch, tmp_path):
    temporary = tmp_path / "duckdb-temp"
    temporary.mkdir()
    resource = CompletionDuckDBResource(temp_directory=str(temporary))
    monkeypatch.setattr(DuckDBResource, "connect", lambda _self: resource.connect())
    return resource


@pytest.fixture
def prepared(completion, controlled_duckdb):
    with controlled_duckdb.connect() as connection:
        cache = CompletionBasicCache(connection, completion.lake)
        cache.get(completion.old)
        cache.get(completion.new)
        return PreparedCompletionBasic.from_cache(cache)


@pytest.fixture
def progress(completion):
    return {"plan_hash": completion.plan.plan_hash, "files": {}}


def ensure(f, progress):
    return execution.ensure_completion_materialization(
        instance=f.instance,
        plan=f.plan,
        item=f.plan.file(DAY),
        lake_root=f.lake,
        progress_path=f.staging / "events.json",
        progress=progress,
    )


def resolved_job(f, resource):
    from orchestrator.defs.assets.etf_daily import silver_etf_adj_factor
    from orchestrator.defs.checks.etf_daily_checks import silver_etf_adj_factor_checks
    from orchestrator.defs.jobs.etf_daily import silver_etf_adj_factor_update_job
    from orchestrator.defs.partitions import cn_a_etf_mins_trade_days

    f.instance.add_dynamic_partitions(cn_a_etf_mins_trade_days.name, [DAY])
    definitions = dg.Definitions(
        assets=[
            silver_etf_adj_factor,
            dg.AssetSpec("raw_tushare_fund_adj"),
            dg.AssetSpec("silver_etf_basic"),
        ],
        asset_checks=[silver_etf_adj_factor_checks],
        jobs=[silver_etf_adj_factor_update_job],
        resources={
            "duckdb": resource,
            "lake_root": LakeRootResource(root_path=str(f.lake)),
        },
    )
    return definitions.resolve_job_def(SILVER_ETF_ADJ_FACTOR_JOB_NAME)


def execute(f, progress, target, prepared, job, resource, **kwargs):
    return execution.execute_completion_checks(
        instance=f.instance,
        job=job,
        plan=f.plan,
        item=f.plan.file(DAY),
        target=target,
        progress_path=f.staging / "events.json",
        progress=progress,
        prepared_basic=prepared,
        resources={
            "duckdb": resource,
            "lake_root": LakeRootResource(root_path=str(f.lake)),
        },
        **kwargs,
    )


def test_materialization_saved_before_uuid_and_reused(
    completion, progress, monkeypatch
):
    calls = []
    original = completion.instance.fetch_materializations

    def fetch(*args, **kwargs):
        calls.append(kwargs["limit"])
        return original(*args, **kwargs)

    monkeypatch.setattr(completion.instance, "fetch_materializations", fetch)
    target = ensure(completion, progress)
    assert progress["files"][DAY]["target"] == target.storage_id
    assert "run_id" not in progress["files"][DAY]
    assert calls == [1, 1]
    again = ensure(completion, progress)
    assert again.storage_id == target.storage_id
    assert calls == [1, 1, 1]
    assert latest(completion.instance).storage_id == target.storage_id
    md = target.metadata
    assert md["dagster/row_count"] == 16  # independent 2 original + 14 additions
    assert md["goldenshare/written_row_count"] == 16
    assert md["goldenshare/basic_reference"] == completion.old.model_dump(mode="json")
    assert "goldenshare/selected_row_count" not in md
    assert (
        md[ETF_FACTOR_COMPLETION_METADATA_KEY]["files"][0]["original_storage_id"]
        == completion.parent.storage_id
    )


def test_materialization_saved_failure_does_not_create_uuid(
    completion, progress, monkeypatch
):
    def fail(*args, **kwargs):
        raise OSError("intentional progress save failure")

    monkeypatch.setattr(execution, "atomic_write_json", fail)
    with pytest.raises(OSError, match="intentional"):
        ensure(completion, progress)
    assert "run_id" not in progress["files"][DAY]
    first_target = latest(completion.instance).storage_id
    monkeypatch.undo()
    assert ensure(completion, progress).storage_id == first_target


def test_latest_other_record_stops_without_append(completion, progress):
    completion.instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=ASSET,
            partition=DAY,
            metadata={"unexpected": True},
        )
    )
    before = latest(completion.instance).storage_id
    with pytest.raises(ValueError, match="latest_target_conflict"):
        ensure(completion, progress)
    assert latest(completion.instance).storage_id == before


def test_saved_target_disagrees_with_latest_stops(completion, progress):
    target = ensure(completion, progress)
    progress["files"][DAY]["target"] = target.storage_id + 1
    with pytest.raises(ValueError, match="saved_target_conflict"):
        ensure(completion, progress)


def test_real_checks_append_six_results_replay_does_not_create_run(
    completion,
    progress,
    prepared,
    controlled_duckdb,
    monkeypatch,
):
    from orchestrator.defs.assets import etf_daily

    writer_calls = []
    monkeypatch.setattr(
        etf_daily,
        "write_etf_adj_factor_silver_partition",
        lambda **kwargs: writer_calls.append(kwargs),
    )
    os.replace(completion.candidate, completion.silver)
    target = ensure(completion, progress)
    job = resolved_job(completion, controlled_duckdb)
    execute(completion, progress, target, prepared, job, controlled_duckdb)
    run_id = progress["files"][DAY]["run_id"]
    run = execution._validate_check_run(
        completion.instance, run_id, DAY, target, completion.plan
    )
    assert run.status == dg.DagsterRunStatus.SUCCESS
    assert run.tags[ETF_FACTOR_COMPLETION_METADATA_KEY] == completion.plan.plan_hash
    assert run.asset_selection == frozenset()
    assert writer_calls == []
    before = len(completion.instance.get_runs())
    execute(completion, progress, target, prepared, job, controlled_duckdb)
    assert len(completion.instance.get_runs()) == before
    assert progress["files"][DAY]["run_id"] == run_id


def test_uuid_save_failure_prevents_create(
    completion, progress, prepared, controlled_duckdb, monkeypatch
):
    target = ensure(completion, progress)
    job = resolved_job(completion, controlled_duckdb)

    def fail(*args, **kwargs):
        raise OSError("uuid save failure")

    monkeypatch.setattr(execution, "atomic_write_json", fail)
    with pytest.raises(OSError, match="uuid save"):
        execute(completion, progress, target, prepared, job, controlled_duckdb)
    assert completion.instance.get_runs() == []


def test_saved_unknown_run_requires_previous_process_confirmation(
    completion, progress, prepared, controlled_duckdb
):
    target = ensure(completion, progress)
    progress["files"][DAY]["run_id"] = "ca7b8847-34e9-4cea-8f10-e9e3f43aa3d2"
    with pytest.raises(ValueError, match="confirm_previous_process_exit"):
        execute(
            completion,
            progress,
            target,
            prepared,
            resolved_job(completion, controlled_duckdb),
            controlled_duckdb,
        )
    assert completion.instance.get_runs() == []


def test_saved_uuid_can_create_once_after_confirmed_previous_process_exit(
    completion, progress, prepared, controlled_duckdb
):
    os.replace(completion.candidate, completion.silver)
    target = ensure(completion, progress)
    saved_id = "25c960a7-c8bc-4db8-af66-f96abed21812"
    progress["files"][DAY]["run_id"] = saved_id
    execution._save_progress(completion.staging / "events.json", progress)
    execute(
        completion,
        progress,
        target,
        prepared,
        resolved_job(completion, controlled_duckdb),
        controlled_duckdb,
        previous_process_exited=True,
    )
    assert [run.run_id for run in completion.instance.get_runs()] == [saved_id]
    assert progress["files"][DAY]["checks_passed"] is True
    execution._validate_check_run(
        completion.instance, saved_id, DAY, target, completion.plan
    )


def test_real_duplicate_run_exception_reuses_same_success_and_never_new_uuid(
    completion, progress, prepared, controlled_duckdb, monkeypatch
):
    from dagster._core.errors import DagsterRunAlreadyExists

    os.replace(completion.candidate, completion.silver)
    target = ensure(completion, progress)
    job = resolved_job(completion, controlled_duckdb)
    execute(completion, progress, target, prepared, job, controlled_duckdb)
    saved_id = progress["files"][DAY]["run_id"]
    original_get = completion.instance.get_run_by_id
    original_execute = dg.JobDefinition.execute_in_process
    missed, duplicate_ids = [], []

    def one_lookup_before_the_concurrent_commit(run_id):
        if run_id == saved_id and not missed:
            missed.append(run_id)
            return None
        return original_get(run_id)

    def actual_sdk_attempt(self, *args, **kwargs):
        try:
            return original_execute(self, *args, **kwargs)
        except DagsterRunAlreadyExists:
            duplicate_ids.append(kwargs["run_id"])
            raise

    monkeypatch.setattr(
        completion.instance, "get_run_by_id", one_lookup_before_the_concurrent_commit
    )
    monkeypatch.setattr(dg.JobDefinition, "execute_in_process", actual_sdk_attempt)
    execute(
        completion,
        progress,
        target,
        prepared,
        job,
        controlled_duckdb,
        previous_process_exited=True,
    )
    assert missed == duplicate_ids == [saved_id]
    assert [run.run_id for run in completion.instance.get_runs()] == [saved_id]
    assert progress["files"][DAY]["run_id"] == saved_id
    execution._validate_check_run(
        completion.instance, saved_id, DAY, target, completion.plan
    )


def test_missing_latest_materialization_stops_without_any_event_or_uuid(
    completion, progress, tmp_path
):
    with dg.DagsterInstance.ephemeral(
        tempdir=str(tmp_path / "empty-instance"),
        settings={"telemetry": {"enabled": False}},
    ) as instance:
        with pytest.raises(ValueError, match="latest_materialization_missing"):
            execution.ensure_completion_materialization(
                instance=instance,
                plan=completion.plan,
                item=completion.plan.file(DAY),
                lake_root=completion.lake,
                progress_path=tmp_path / "events.json",
                progress=progress,
            )
        assert progress["files"] == {} and instance.get_runs() == []
        assert not instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=dg.AssetKey(ASSET), asset_partitions=[DAY]),
            limit=1,
        ).records


@pytest.mark.parametrize(
    "status",
    [
        dg.DagsterRunStatus.FAILURE,
        dg.DagsterRunStatus.CANCELED,
        dg.DagsterRunStatus.NOT_STARTED,
        dg.DagsterRunStatus.STARTED,
    ],
)
def test_existing_non_success_run_is_never_restarted(
    completion,
    progress,
    prepared,
    controlled_duckdb,
    status,
):
    target = ensure(completion, progress)
    job = resolved_job(completion, controlled_duckdb)
    run = completion.instance.create_run_for_job(
        job,
        status=status,
        tags={
            "dagster/partition": DAY,
            ETF_FACTOR_COMPLETION_METADATA_KEY: completion.plan.plan_hash,
        },
    )
    progress["files"][DAY]["run_id"] = run.run_id
    with pytest.raises(ValueError, match="not_success"):
        execute(completion, progress, target, prepared, job, controlled_duckdb)
    assert len(completion.instance.get_runs()) == 1


def test_completed_run_wrong_plan_tag_is_rejected(
    completion, progress, prepared, controlled_duckdb
):
    target = ensure(completion, progress)
    job = resolved_job(completion, controlled_duckdb)
    run = completion.instance.create_run_for_job(
        job,
        status=dg.DagsterRunStatus.SUCCESS,
        tags={"dagster/partition": DAY, ETF_FACTOR_COMPLETION_METADATA_KEY: "0" * 64},
    )
    progress["files"][DAY]["run_id"] = run.run_id
    with pytest.raises(ValueError, match="identity_mismatch"):
        execute(completion, progress, target, prepared, job, controlled_duckdb)


@pytest.mark.parametrize(
    "stage",
    ["plan", "candidates", "candidate-audit", "promote", "events", "final-audit"],
)
def test_cli_missing_basic_stops_before_any_plan_open(stage, tmp_path):
    with pytest.raises(TypeError, match="prepared_basic_required"):
        run_stage(stage, plan_path=tmp_path / "does-not-exist.json")


def test_cli_has_no_all_stage_or_root_or_basic_file_options():
    with pytest.raises(SystemExit):
        main(["all"])
    with pytest.raises(SystemExit):
        main(["plan", "--plan", "/private/tmp/a.json", "--lake-root", "/other"])


def test_complete_stage_rejects_original_total_drift(
    completion, prepared, controlled_duckdb
):
    with (
        controlled_duckdb.connect() as connection,
        pytest.raises(ValueError, match="42900"),
    ):
        execution.audit_completion_candidates(
            connection=connection,
            lake_root=completion.lake,
            staging_root=completion.staging,
            storage=completion.instance.event_log_storage,
            plan=completion.plan,
            prepared_basic=prepared,
        )


def test_latest_records_selects_one_per_date_even_with_many_same_date_versions(
    completion,
):
    for day in ("2026-10-19", "2026-10-20", "2026-10-21"):
        for _ in range(3):
            completion.instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=ASSET,
                    partition=day,
                    metadata={"day": day},
                )
            )
    found = execution._latest_records(
        completion.instance.event_log_storage, ASSET, execution._COMPLETE_DAYS
    )
    assert set(found) == {"2026-10-19", "2026-10-20", "2026-10-21"}
    assert all(record.metadata["day"] == day for day, record in found.items())


def test_final_query_counter_blocks_fifteenth_without_query():
    calls = []
    counted = execution._CountedConnection(
        SimpleNamespace(execute=lambda *args: calls.append(args)),
        SimpleNamespace(query_count=14),
    )
    with pytest.raises(ValueError, match="query_limit"):
        counted.execute("SELECT 1")
    assert calls == []


def test_budget_cancellation_and_elapsed_both_stop(monkeypatch):
    with pytest.raises(InterruptedError):
        execution._budget(0, lambda: True)
    monkeypatch.setattr(execution, "perf_counter", lambda: 31)
    with pytest.raises(InterruptedError):
        execution._budget(0, lambda: False)


def test_unchanged_progress_has_no_foreign_dates(completion, tmp_path):
    path = tmp_path / "progress.json"
    path.write_text(
        json.dumps(
            {"plan_hash": completion.plan.plan_hash, "files": {"2026-10-19": {}}}
        )
    )
    with pytest.raises(ValueError, match="date_out_of_scope"):
        execution._progress(path, completion.plan)


def test_candidate_report_cannot_change_one_expected_row(completion, tmp_path):
    report = {
        "plan_hash": completion.plan.plan_hash,
        "added_rows": 701,
        "modified_rows": 0,
        "deleted_rows": 0,
        "files": {},
    }
    (tmp_path / "candidate-audit.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="report_mismatch"):
        execution._require_candidate_report(tmp_path, completion.plan)


def test_fixed_totals_do_not_accept_same_added_count_with_changed_original(completion):
    plan = replace(
        completion.plan,
        files=tuple(
            replace(
                item,
                original_metadata={**item.original_metadata, "dagster/row_count": 1651},
                expected_row_count=1651
                + len(completion.plan.scope["additions"][item.trade_date]),
            )
            for item in completion.plan.files
        ),
    )
    with pytest.raises(ValueError, match="42900"):
        execution._fixed_totals(plan)


def test_temp_resource_limits_are_fixed(controlled_duckdb):
    with controlled_duckdb.connect() as connection:
        assert (
            connection.execute("SELECT current_setting('threads')").fetchone()[0] == 1
        )
        assert (
            connection.execute(
                "SELECT current_setting('max_temp_directory_size')"
            ).fetchone()[0]
            == "0 bytes"
        )


def test_cli_rejects_ordinary_resource_before_reading_plan(completion, prepared):
    with pytest.raises(TypeError, match="controlled_duckdb"):
        run_stage(
            "candidate-audit",
            plan_path=completion.staging / "etf_daily/missing.json",
            prepared_basic=prepared,
            storage=completion.instance.event_log_storage,
            duckdb_resource=DuckDBResource(),
            lake_root=completion.lake,
            staging_root=completion.staging,
        )


def test_plan_cancellation_happens_before_storage_or_file_read(
    prepared, controlled_duckdb, completion
):
    with controlled_duckdb.connect() as connection:
        cache = prepared.seed_cache(
            connection, completion.lake, [completion.new, completion.old]
        )
        with pytest.raises(InterruptedError):
            execution.build_completion_plan(
                connection=connection,
                lake_root=completion.lake,
                storage=SimpleNamespace(),
                scope=source_fixture.SCOPE,
                basic_reference=completion.new,
                basic_cache=cache,
                check_cancel=lambda: True,
            )


def test_green_run_cannot_hide_later_real_failed_run(
    completion,
    progress,
    prepared,
    controlled_duckdb,
):
    os.replace(completion.candidate, completion.silver)
    target = ensure(completion, progress)
    job = resolved_job(completion, controlled_duckdb)
    execute(completion, progress, target, prepared, job, controlled_duckdb)
    good_bytes = completion.silver.read_bytes()
    bad = completion.staging / "intentionally-bad.parquet"
    with controlled_duckdb.connect() as connection:
        connection.execute(
            f"COPY (SELECT ts_code,trade_date,0.0::DOUBLE AS adj_factor,discount_rate FROM {read_parquet(completion.silver, hive_partitioning=False)}) TO {duckdb_string(bad)} (FORMAT PARQUET)"
        )
    os.replace(bad, completion.silver)
    keys = {
        dg.AssetCheckKey(dg.AssetKey(ASSET), name)
        for name in source_fixture.SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS
    }
    later = job.get_subset(
        asset_selection=set(), asset_check_selection=keys
    ).execute_in_process(
        instance=completion.instance,
        partition_key=DAY,
        resources={
            "prepared_basic": dg.ResourceDefinition.hardcoded_resource(prepared),
            "duckdb": controlled_duckdb,
            "lake_root": LakeRootResource(root_path=str(completion.lake)),
        },
        tags={ETF_FACTOR_COMPLETION_METADATA_KEY: completion.plan.plan_hash},
        raise_on_error=False,
    )
    assert not later.success
    completion.silver.write_bytes(good_bytes)
    before = len(completion.instance.get_runs())
    with pytest.raises(ValueError, match="latest_check_failed_or_unfinished"):
        execute(completion, progress, target, prepared, job, controlled_duckdb)
    assert len(completion.instance.get_runs()) == before == 2


def test_intermediate_staging_symlink_rejected_before_creation(completion, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (completion.staging / "etf_daily").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="path_symlink"):
        execution.completion_directory(completion.staging, completion.plan)
    assert list(outside.iterdir()) == []


def test_progress_leaf_symlink_rejected_before_read_or_write(completion, tmp_path):
    target = tmp_path / "unchanged.json"
    target.write_text("unchanged")
    path = completion.staging / "events.json"
    path.symlink_to(target)
    with pytest.raises(ValueError, match="path_symlink"):
        execution._progress(path, completion.plan)
    with pytest.raises(ValueError, match="path_symlink"):
        execution._save_progress(path, {})
    assert target.read_text() == "unchanged"


@pytest.fixture
def full_completion(tmp_path, controlled_duckdb):
    """26 x 1650 literal original rows = 42,900; real temporary producer formats.

    Original synthetic codes 700000.SH..701649.SH all have factor2/NULL.
    Approved 701 keys and the extra three dates have factor1/NULL. The 26 Raw
    files also contain 12,748 synthetic codes missing from both Basic snapshots:
    490 per first 25 dates and 498 on the last date. Thus Raw has the independently
    documented 56,349 rows; these additional rows must never enter Silver.
    Expected
    business values and counts below are literals independent of the new helper.
    """
    lake, staging = make_roots(tmp_path)
    old_rows = [basic_row(f"{700000 + i:06d}.SH") for i in range(1650)]
    old = write_basic_reference(lake_root=lake, staging_root=staging, rows=old_rows)
    new = write_basic_reference(
        lake_root=lake,
        staging_root=staging,
        rows=old_rows
        + [
            basic_row(code, list_date=day.replace("-", ""))
            for code, day in source_fixture.SCOPE["listing_dates"].items()
        ],
        eligibility_as_of=date(2026, 10, 21),
    )
    instance = dg.DagsterInstance.ephemeral(
        tempdir=str(tmp_path / "instance"), settings={"telemetry": {"enabled": False}}
    )
    references = {}
    with controlled_duckdb.connect() as connection:
        connection.execute(
            "CREATE TEMP TABLE original_rows AS SELECT (700000+i)::VARCHAR || '.SH' AS ts_code,2.0::DOUBLE AS adj_factor,NULL::DOUBLE AS discount_rate FROM range(1650) t(i)"
        )
        for day in (
            *sorted(source_fixture.SCOPE["additions"]),
            *execution._COMPLETE_DAYS,
        ):
            extra = source_fixture.SCOPE["additions"].get(
                day, sorted(source_fixture.SCOPE["listing_dates"])
            )
            padding = (
                0
                if day in execution._COMPLETE_DAYS
                else 498
                if day == max(source_fixture.SCOPE["additions"])
                else 490
            )
            code_values = ",".join(f"({duckdb_string(code)})" for code in extra)
            raw = execution.SPEC.raw_spec.target_path_builder(lake, day)
            silver = execution.SPEC.target_path_builder(lake, day)
            raw.parent.mkdir(parents=True, exist_ok=True)
            silver.parent.mkdir(parents=True, exist_ok=True)
            raw_sql = f"SELECT ts_code,{duckdb_string(day.replace('-', ''))} AS trade_date,adj_factor,discount_rate FROM original_rows UNION ALL SELECT ts_code,{duckdb_string(day.replace('-', ''))},1.0::DOUBLE,NULL::DOUBLE FROM (VALUES {code_values}) t(ts_code)"
            raw_sql += f" UNION ALL SELECT (800000+i)::VARCHAR || '.SH',{duckdb_string(day.replace('-', ''))},3.0::DOUBLE,NULL::DOUBLE FROM range({padding}) t(i)"
            silver_sql = (
                f"SELECT ts_code,DATE {duckdb_string(day)} AS trade_date,adj_factor,discount_rate FROM original_rows"
                if day not in execution._COMPLETE_DAYS
                else f"SELECT ts_code,strptime(trade_date,'%Y%m%d')::DATE AS trade_date,adj_factor,discount_rate FROM ({raw_sql}) r"
            )
            for sql, path in ((raw_sql, raw), (silver_sql, silver)):
                connection.execute(
                    f"COPY ({sql}) TO {duckdb_string(path)} (FORMAT PARQUET)"
                )
            raw_audit = audit_etf_daily_raw_relation(
                connection,
                relation_sql=read_parquet(raw, hive_partitioning=False),
                spec=execution.SPEC.raw_spec,
                partition_key=day,
            )
            silver_audit = audit_etf_daily_silver_relation(
                connection,
                relation_sql=read_parquet(silver, hive_partitioning=False),
                spec=execution.SPEC,
                partition_key=day,
            )
            reference_payload = old.model_dump(mode="python")
            reference_payload.pop("reference_fingerprint")
            reference_payload["eligibility_as_of"] = date.fromisoformat(day)
            reference = build_etf_basic_silver_snapshot_reference(**reference_payload)
            references[day] = reference
            raw_md = build_materialization_metadata(
                uri=raw,
                row_count=1650 + len(extra) + padding,
                extra_metadata={
                    "content_hash": raw_audit.content_hash,
                    "source_row_count": 1650 + len(extra) + padding,
                    "normalized_row_count": 1650 + len(extra) + padding,
                    "written_row_count": 1650 + len(extra) + padding,
                },
            )
            silver_count = 1706 if day in execution._COMPLETE_DAYS else 1650
            silver_md = build_materialization_metadata(
                uri=silver,
                row_count=silver_count,
                extra_metadata={
                    "content_hash": silver_audit.content_hash,
                    "written_row_count": silver_count,
                    "basic_reference": reference.model_dump(mode="json"),
                    "basic_raw_snapshot_hash": reference.raw_snapshot_hash,
                    "basic_silver_content_hash": reference.silver_content_hash,
                },
            )
            for asset, md in (
                (execution.SPEC.raw_spec.asset_key, raw_md),
                (ASSET, silver_md),
            ):
                instance.report_runless_asset_event(
                    dg.AssetMaterialization(asset_key=asset, partition=day, metadata=md)
                )
            if day not in execution._COMPLETE_DAYS:
                target = latest(instance, ASSET, day)
                for name in source_fixture.SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS:
                    source_fixture.emit_check(instance, target, name)
        basic_md = build_materialization_metadata(
            uri=new.silver_uri,
            row_count=1706,
            extra_metadata={
                "raw_snapshot_hash": new.raw_snapshot_hash,
                "silver_content_hash": new.silver_content_hash,
                "observed_at": new.silver_observed_at,
            },
        )
        instance.report_runless_asset_event(
            dg.AssetMaterialization(asset_key="silver_etf_basic", metadata=basic_md)
        )
        basic_target = latest(instance, "silver_etf_basic", None)
        for name in SILVER_ETF_BASIC_CHECKS:
            source_fixture.emit_check(instance, basic_target, name)
        cache = CompletionBasicCache(connection, lake)
        cache.get(new)
        for day in sorted(source_fixture.SCOPE["additions"]):
            cache.get(references[day])
        prepared = PreparedCompletionBasic.from_cache(cache)
    value = SimpleNamespace(
        lake=lake,
        staging=staging,
        instance=instance,
        new=new,
        prepared=prepared,
        root=tmp_path,
    )
    yield value
    instance.dispose()


def test_real_check_finishes_current_date_then_cancellation_stops_next_date(
    full_completion,
    controlled_duckdb,
    monkeypatch,
):
    from orchestrator.defs.checks import etf_daily_checks
    from orchestrator.defs.partitions import cn_a_etf_mins_trade_days

    f = full_completion
    f.instance.add_dynamic_partitions(
        cn_a_etf_mins_trade_days.name, sorted(source_fixture.SCOPE["additions"])
    )
    context = {
        "plan_path": f.staging / "etf_daily/frozen-plan.json",
        "prepared_basic": f.prepared,
        "scope": source_fixture.SCOPE,
        "basic_reference": f.new,
        "storage": f.instance.event_log_storage,
        "instance": f.instance,
        "job": resolved_job(f, controlled_duckdb),
        "duckdb_resource": controlled_duckdb,
        "lake_root": f.lake,
        "staging_root": f.staging,
    }
    plan = run_stage("plan", **context)
    context["expected_plan_hash"] = plan["plan_hash"]
    for stage in ("candidates", "candidate-audit", "promote"):
        if stage != "promote":
            run_stage(stage, approved=stage != "candidate-audit", **context)
            continue
        first_day = min(source_fixture.SCOPE["additions"])
        first_target = execution.SPEC.target_path_builder(f.lake, first_day)
        original_bytes = first_target.read_bytes()
        with pytest.raises(InterruptedError):
            run_stage("promote", approved=True, check_cancel=lambda: True, **context)
        assert first_target.read_bytes() == original_bytes
        actual_save = execution.atomic_write_json

        def fail_file_progress(path, value, actual_save=actual_save):
            if path.name == "files.json":
                raise OSError("intentional replace succeeded but progress save failed")
            return actual_save(path, value)

        with monkeypatch.context() as interruption:
            interruption.setattr(execution, "atomic_write_json", fail_file_progress)
            with pytest.raises(OSError, match="progress save failed"):
                run_stage("promote", approved=True, **context)
        first_day = min(source_fixture.SCOPE["additions"])
        first_target = execution.SPEC.target_path_builder(f.lake, first_day)
        first_writes = []
        actual_replace = os.replace

        def record_replace(
            source,
            target,
            first_target=first_target,
            first_writes=first_writes,
            actual_replace=actual_replace,
        ):
            if Path(target) == first_target:
                first_writes.append(str(target))
            return actual_replace(source, target)

        with monkeypatch.context() as resumption:
            resumption.setattr(os, "replace", record_replace)
            run_stage("promote", approved=True, **context)
        assert first_writes == []  # current complete file is reused, never rewritten.
    cancelled = False
    actual = etf_daily_checks.audit_completed_target

    def audit_then_cancel(*args, **kwargs):
        nonlocal cancelled
        result = actual(*args, **kwargs)
        cancelled = True
        return result

    monkeypatch.setattr(etf_daily_checks, "audit_completed_target", audit_then_cancel)
    with pytest.raises(InterruptedError):
        run_stage("events", approved=True, check_cancel=lambda: cancelled, **context)
    progress_path = (
        execution.completion_directory(
            f.staging, execution.EtfFactorCompletionPlan.from_dict(plan)
        )
        / "events.json"
    )
    progress = json.loads(progress_path.read_text())
    first = min(source_fixture.SCOPE["additions"])
    assert set(progress["files"]) == {first}
    assert progress["files"][first]["checks_passed"] is True
    runs = f.instance.get_runs()
    assert len(runs) == 1 and runs[0].status == dg.DagsterRunStatus.SUCCESS
    second = sorted(source_fixture.SCOPE["additions"])[1]
    assert (
        ETF_FACTOR_COMPLETION_METADATA_KEY
        not in execution.FactorMaterializationEvidence.from_record(
            latest(f.instance, ASSET, second)
        ).metadata
    )
    assert (
        len(json.loads((progress_path.parent / "files.json").read_text())["files"])
        == 26
    )
    with pytest.raises(InterruptedError):
        run_stage("events", approved=True, check_cancel=lambda: True, **context)
    assert len(f.instance.get_runs()) == 1


def test_complete_26_file_pipeline_and_29_day_final_audit(
    full_completion, controlled_duckdb, monkeypatch
):
    """Full isolated stages, actual checks/events, fixed normal budgets unchanged."""
    from dagster._serdes import serialize_value

    from orchestrator.defs.asset_guards import (
        etf_adj_factor_history_completion as guard,
    )
    from orchestrator.defs.partitions import cn_a_etf_mins_trade_days

    f = full_completion
    metrics = {"sql": [], "connections": 0, "audits": 0, "full_basic_reads": 0}
    query_times, seed_times, check_times, run_times, stored_events = [], [], [], {}, []

    class Connection:
        def __init__(self, connection, number):
            self.connection = connection
            self.number = number

        def execute(self, query, *args, **kwargs):
            metrics["sql"].append(str(query))
            started = perf_counter()
            try:
                return self.connection.execute(query, *args, **kwargs)
            finally:
                query_times.append((self.number, str(query), perf_counter() - started))

    class MeasuredResource(CompletionDuckDBResource):
        @contextmanager
        def connect(self):
            metrics["connections"] += 1
            with super().connect() as connection:
                yield Connection(connection, metrics["connections"])

    resource = MeasuredResource(temp_directory=controlled_duckdb.temp_directory)
    original_audit = guard.audit_completion_file

    def counted_audit(**kwargs):
        metrics["audits"] += 1
        return original_audit(**kwargs)

    def deny_full_read(**kwargs):
        metrics["full_basic_reads"] += 1
        raise AssertionError("full Basic reread after prepared input")

    original_seed = PreparedCompletionBasic.seed_cache

    def measured_seed(self, connection, *args, **kwargs):
        started = perf_counter()
        try:
            return original_seed(self, connection, *args, **kwargs)
        finally:
            seed_times.append((connection.number, perf_counter() - started))

    from orchestrator.defs.checks import etf_daily_checks

    original_check = etf_daily_checks.audit_completed_target

    def measured_check(**kwargs):
        started = perf_counter()
        try:
            return original_check(**kwargs)
        finally:
            check_times.append(
                (
                    kwargs["trade_date"],
                    kwargs["connection"].number,
                    perf_counter() - started,
                )
            )

    original_run = dg.JobDefinition.execute_in_process

    def measured_run(self, *args, **kwargs):
        started = perf_counter()
        try:
            return original_run(self, *args, **kwargs)
        finally:
            run_times[kwargs["run_id"]] = perf_counter() - started

    original_store = f.instance.event_log_storage.store_event

    def measured_store(entry, *args, **kwargs):
        started = perf_counter()
        try:
            return original_store(entry, *args, **kwargs)
        finally:
            stored_events.append((entry, perf_counter() - started))

    monkeypatch.setattr(guard, "audit_completion_file", counted_audit)
    monkeypatch.setattr(execution, "audit_completion_file", counted_audit)
    monkeypatch.setattr(guard, "audit_etf_basic_silver_snapshot", deny_full_read)
    monkeypatch.setattr(PreparedCompletionBasic, "seed_cache", measured_seed)
    monkeypatch.setattr(etf_daily_checks, "audit_completed_target", measured_check)
    monkeypatch.setattr(dg.JobDefinition, "execute_in_process", measured_run)
    monkeypatch.setattr(f.instance.event_log_storage, "store_event", measured_store)
    f.instance.add_dynamic_partitions(
        cn_a_etf_mins_trade_days.name, sorted(source_fixture.SCOPE["additions"])
    )
    job = resolved_job(f, resource)
    plan_path = f.staging / "etf_daily/frozen-plan.json"
    context = {
        "plan_path": plan_path,
        "prepared_basic": f.prepared,
        "scope": source_fixture.SCOPE,
        "basic_reference": f.new,
        "storage": f.instance.event_log_storage,
        "instance": f.instance,
        "job": job,
        "duckdb_resource": resource,
        "lake_root": f.lake,
        "staging_root": f.staging,
    }
    stages = {}
    for stage in (
        "plan",
        "candidates",
        "candidate-audit",
        "promote",
        "events",
        "events-resume",
        "final-audit",
    ):
        before = perf_counter()
        stored_count_before = len(stored_events)
        sql_start, connection_start, audit_start = (
            len(metrics["sql"]),
            metrics["connections"],
            metrics["audits"],
        )
        result = run_stage(
            "events" if stage == "events-resume" else stage,
            approved=stage in {"candidates", "promote", "events", "events-resume"},
            **context,
        )
        elapsed = perf_counter() - before
        sql = metrics["sql"][sql_start:]
        paths = [
            path
            for query in sql
            for path in re.findall(
                r"read_parquet\('([^']+)'", query, flags=re.IGNORECASE
            )
        ]
        stages[stage] = {
            "elapsed_seconds": elapsed,
            "sql_count": len(sql),
            "parquet_read_references": len(paths),
            "different_read_files": len(set(paths)),
            "raw_read_references": sum("/raw/" in path for path in paths),
            "silver_read_references": sum("/silver/" in path for path in paths),
            "temp_input_loads": sum(
                "create" in query.lower() and "read_parquet(" in query.lower()
                for query in sql
            ),
            "connections": metrics["connections"] - connection_start,
            "completion_audits": metrics["audits"] - audit_start,
        }
        assert elapsed < 30
        assert metrics["full_basic_reads"] == 0
        if stage == "plan":
            context["expected_plan_hash"] = result["plan_hash"]
        if stage == "events":
            assert len(result["files"]) == 26
            assert (
                stages[stage]["completion_audits"] == 52
            )  # 26 prechecks + 26 actual checks
            logs = [
                record.event_log_entry
                for value in result["files"].values()
                for record in f.instance.get_records_for_run(value["run_id"]).records
            ]
            stages[stage]["run_log_entries"] = len(logs)
            stages[stage]["run_log_serialized_bytes"] = sum(
                len(serialize_value(entry).encode()) for entry in logs
            )
            assert len(logs) == 702  # 27 SDK events per successful six-result run.
            assert stages[stage]["run_log_serialized_bytes"] <= 2 * 1024 * 1024
            first_day = min(source_fixture.SCOPE["additions"])
            first_id = result["files"][first_day]["run_id"]
            day, number, audit_seconds = next(
                item for item in check_times if item[0] == first_day
            )
            writes = [item for item in stored_events if item[0].run_id == first_id]
            evaluations = [
                item
                for item in writes
                if item[0].dagster_event
                and item[0].dagster_event.event_type_value == "ASSET_CHECK_EVALUATION"
            ]
            assert len(evaluations) == 6 and len(writes) == 27
            first_loads = [
                (query, seconds)
                for connection_number, query, seconds in query_times
                if connection_number == number and "read_parquet(" in query.lower()
            ]
            assert len(first_loads) == 2
            first_seed_seconds = sum(
                seconds for n, seconds in seed_times if n == number
            )
            phases = {
                entry.dagster_event.event_type_value: entry.timestamp
                for entry, _ in writes
                if entry.dagster_event
            }
            stages[stage]["first_day"] = {
                "trade_date": day,
                "sdk_run_seconds": run_times[first_id],
                "run_start_to_step_start_seconds": phases["STEP_START"]
                - phases["PIPELINE_START"],
                "basic_seed_seconds": first_seed_seconds,
                "complete_audit_seconds": audit_seconds,
                "raw_input_load_seconds": sum(
                    seconds for query, seconds in first_loads if "/raw/" in query
                ),
                "silver_input_load_seconds": sum(
                    seconds for query, seconds in first_loads if "/silver/" in query
                ),
                "six_result_storage_seconds": sum(
                    seconds for _, seconds in evaluations
                ),
                "all_27_events_storage_seconds": sum(seconds for _, seconds in writes),
                "raw_and_silver_loads": 2,
                "basic_parquet_reads": 0,
                "complete_check_audits": 1,
            }
            assert len(f.instance.get_runs()) == 26
            saved_events = result["files"]
        if stage == "events-resume":
            assert result["files"] == saved_events
            assert len(f.instance.get_runs()) == 26
            assert len(stored_events) == stored_count_before
            assert stages[stage]["completion_audits"] == 26
        if stage == "final-audit":
            assert result["written_rows"] == 43601
            assert result["different_files"] == 58 and result["evidence_queries"] <= 14
            assert (
                result["scope_rows"] == 869 and result["already_complete_rows"] == 168
            )
            assert stages[stage]["different_read_files"] == 58
            assert stages[stage]["parquet_read_references"] == 58
            assert stages[stage]["temp_input_loads"] == 58
    with resource.connect() as connection:
        paths = ",".join(
            duckdb_string(str(execution.SPEC.target_path_builder(f.lake, day)))
            for day in sorted(source_fixture.SCOPE["additions"])
        )
        totals = connection.execute(
            f"SELECT count(*),count(*) FILTER(WHERE adj_factor=2 AND discount_rate IS NULL),count(*) FILTER(WHERE adj_factor=1 AND discount_rate IS NULL) FROM read_parquet([{paths}],hive_partitioning=false)"
        ).fetchone()
        raw_paths = ",".join(
            duckdb_string(str(execution.SPEC.raw_spec.target_path_builder(f.lake, day)))
            for day in sorted(source_fixture.SCOPE["additions"])
        )
        raw_totals = connection.execute(
            f"SELECT count(*),count(*) FILTER(WHERE adj_factor=3),count(*) FILTER(WHERE adj_factor IN (1,2)) FROM read_parquet([{raw_paths}],hive_partitioning=false)"
        ).fetchone()
    assert totals == (43601, 42900, 701)
    assert raw_totals == (56349, 12748, 43601)
    import resource as process_resource
    import sys

    peak = process_resource.getrusage(process_resource.RUSAGE_SELF).ru_maxrss
    assert list(Path(resource.temp_directory).iterdir()) == []
    report = {
        "stages": stages,
        "full_basic_reads": metrics["full_basic_reads"],
        "scope": {
            "modified_files": 26,
            "raw_rows": 56349,
            "original_rows": 42900,
            "new_rows": 701,
            "complete_rows": 43601,
        },
        "measurement": "SQL references and TEMP loads; not OS-level file opens",
        "process_peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024,
        "peak_scope": "whole test process including fixtures and Dagster; not DuckDB-only",
        "spill_limit": "0B",
        "temporary_files_after_stages": 0,
    }
    (f.root / "full-stage-measurement.json").write_text(json.dumps(report, indent=2))
    print(
        "full-stage-measurement=" + str(f.root / "full-stage-measurement.json"),
        flush=True,
    )
