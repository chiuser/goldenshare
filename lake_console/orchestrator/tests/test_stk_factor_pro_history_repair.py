"""Actual repair operation with real temporary native events and frozen source scope."""

from contextlib import contextmanager
from unittest.mock import patch

import dagster as dg
import pytest

from orchestrator.defs.assets import stk_factor_pro as asset
from orchestrator.defs.io import stk_factor_pro_candidates as candidates
from orchestrator.defs.jobs.stk_factor_pro_history_repair import (
    raw_tushare_stk_factor_pro_repair_job,
)
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
)
from orchestrator.tushare_download import DownloadError, DownloadErrorCode, DownloadMode
from tests import test_stk_factor_pro_jobs as update_tests
from tests.stk_factor_pro_history_test_support import (
    HistoryDownloader,
    saved_real_rows,
    write_factor_file,
)
from tests.stk_factor_pro_test_support import DAY, connection
from tests.test_stk_factor_pro_jobs import FIRST, A, config, input_files

actual_job = update_tests.actual_job


def setup_failed_history(tmp_path, monkeypatch, actual_job, *, history_error=None):
    instance, job, set_source, lake, staging, _counts = actual_job
    input_files(tmp_path, lake, changed=(A,), codes=(A,))
    replay = saved_real_rows()
    remote = HistoryDownloader({A: (replay[-1],)})
    day_source = set_source((replay[-1],))
    history_calls = []

    class FailedHistoricalDownload:
        def download(self, task, **kwargs):
            if task.mode is DownloadMode.BY_POINT:
                return day_source.download(task, **kwargs)
            history_calls.append(task.mode)
            if history_error is not None:
                raise DownloadError(history_error)
            return remote.download(task, **kwargs)

    monkeypatch.setattr(
        asset.download.TushareDownloader, "load", FailedHistoricalDownload
    )
    path = raw_stk_factor_pro_path(lake, str(FIRST))
    path.parent.mkdir(parents=True)
    with connection(tmp_path) as conn:
        frame = candidates.build_stk_factor_pro_raw_batch(
            rows=(replay[1],),
            source="http",
            source_fields=asset.C.STK_FACTOR_PRO_SOURCE_COLUMNS,
            expected_dates=(FIRST,),
        )
        conn.register("fixture_day", frame)
        conn.execute("COPY fixture_day TO ? (FORMAT PARQUET)", [str(path)])
    instance.report_runless_asset_event(
        dg.AssetMaterialization(asset._RAW, partition=str(FIRST))
    )
    executed = job.execute_in_process(
        instance=instance,
        partition_key=str(DAY),
        run_config=config(),
        raise_on_error=False,
    )
    assert not executed.success
    failure = executed.failure_data_for_node("stk_factor_pro").user_failure_data
    assert failure.metadata["goldenshare/failure_phase"].value == "history"
    assert failure.metadata["goldenshare/retryable"].value is True
    if history_error is not None:
        assert failure.metadata["goldenshare/source_error_code"].value == int(
            history_error
        )
    assert len(day_source.calls) == 1
    assert history_calls == [DownloadMode.BY_OBJECT_RANGE]
    source_id = executed.run_id
    original = asset.history.read_stk_factor_pro_history_plan(
        asset.stk_factor_pro_run_staging_root(staging, source_id, str(DAY)),
        expected_target=DAY,
        expected_run_id=source_id,
        known_records={},
    )
    return job, source_id, original, replay


def repair_config(source_id, original, day=DAY):
    return {
        "ops": {
            "repair_stk_factor_pro_history": {
                "config": {
                    "target_trade_date": str(day),
                    "source_run_id": source_id,
                    "expected_history_plan_digest": original.history_plan_digest,
                    "expected_history_ranges_digest": original.history_ranges_digest,
                }
            }
        }
    }


@contextmanager
def repair_job_context(update_job):
    defs = dg.Definitions(
        jobs=[raw_tushare_stk_factor_pro_repair_job],
        resources={
            k: v for k, v in update_job.resource_defs.items() if k != "io_manager"
        },
    )
    yield defs.resolve_job_def(asset.C.STK_FACTOR_PRO_REPAIR_JOB_NAME)


@pytest.mark.parametrize("failure_layer", [None, "raw", "silver", "wrong_digest"])
def test_repair_uses_current_native_gate_and_only_fresh_original_history(
    tmp_path, monkeypatch, actual_job, failure_layer
):
    instance, _, _, lake, _staging, counts = actual_job
    job, source_id, original, replay = setup_failed_history(
        tmp_path, monkeypatch, actual_job
    )
    raw = raw_stk_factor_pro_path(lake, str(DAY))
    silver = silver_stock_factor_pro_path(lake, str(DAY))
    if failure_layer == "raw":
        raw.unlink()
    elif failure_layer == "silver":
        silver.unlink()
    target_state = tuple(
        path.read_bytes() if path.exists() else None for path in (raw, silver)
    )
    run_config = repair_config(source_id, original)
    if failure_layer == "wrong_digest":
        run_config["ops"]["repair_stk_factor_pro_history"]["config"][
            "expected_history_ranges_digest"
        ] = "0" * 64
    if failure_layer is None:
        with connection(tmp_path) as conn:
            revised = write_factor_file(conn, lake, DAY, ((A, 3),))
        assert revised.file_sha256 != original.factor_t_ref.file_sha256
    remote = HistoryDownloader({A: replay[1:]})
    monkeypatch.setattr(asset.download.TushareDownloader, "load", lambda: remote)
    for calls in counts.values():
        calls.clear()
    with repair_job_context(job) as repair:
        executed = repair.execute_in_process(
            instance=instance, run_config=run_config, raise_on_error=False
        )
        assert executed.success is (failure_layer is None), (
            executed.failure_data_for_node(
                "repair_stk_factor_pro_history"
            ).error.to_string()
        )
        if failure_layer is None:
            assert len(remote.calls) == 1
            task = remote.calls[0][0]
            assert task.mode is DownloadMode.BY_OBJECT_RANGE
            assert (
                task.object_ranges[0].time_range.start,
                task.object_ranges[0].time_range.end,
            ) == (str(FIRST), str(DAY))
            assert [x.rows for x in remote.sessions] == [4]
            assert len(executed.get_asset_materialization_events()) == 6
            assert all(
                e.partition != str(DAY)
                for e in executed.get_asset_materialization_events()
            )
            known_pg = {}
            facts = asset.readiness.read_stk_factor_pro_recorded_results(
                instance, target_trade_date=DAY, known_pg=known_pg
            )
            assert facts.unresolved_history_failure_run_id is None
            assert (
                not facts.pending_plan_refs
                and len(facts.successful_publication_refs) == 1
            )
            assert facts.day_result_ref.run_id == source_id
            assert facts.history_plan_ref.creator_run_id == executed.run_id
            with patch.object(
                instance, "fetch_observations", wraps=instance.fetch_observations
            ) as fetch:
                baseline = asset.readiness.read_stk_factor_pro_day_factor_shas(
                    instance,
                    prior=facts,
                    previous_trade_date=original.identity.previous_trade_date,
                    lake_root=lake,
                    staging_root=_staging,
                    contract=original.contract,
                    known_pg=known_pg,
                    known_records={},
                )
                fetch.assert_not_called()
            assert baseline == (
                original.factor_t_ref.file_sha256,
                original.factor_p_ref.file_sha256,
            )
            remote.calls.clear()
            next_run = repair.execute_in_process(
                instance=instance, run_config=run_config, raise_on_error=False
            )
            assert next_run.success and not remote.calls
        else:
            assert not remote.calls
            assert not executed.get_asset_materialization_events()
            failure = executed.failure_data_for_node("repair_stk_factor_pro_history")
            expected = {
                "raw": "原日期数据缺失",
                "silver": "原日期Silver不可用",
                "wrong_digest": "原完整计划或范围摘要不符",
            }
            assert expected[failure_layer] in failure.error.message
            assert (
                failure.user_failure_data.metadata["goldenshare/retryable"].value
                is False
            )
    assert (
        tuple(path.read_bytes() if path.exists() else None for path in (raw, silver))
        == target_state
    )
    assert all(not calls for calls in counts.values())


def test_newer_repair_failure_takes_precedence_over_retryable_update(
    tmp_path, monkeypatch, actual_job
):
    instance, _, _, lake, _, _ = actual_job
    job, source_id, original, _ = setup_failed_history(
        tmp_path,
        monkeypatch,
        actual_job,
        history_error=DownloadErrorCode.TRANSIENT_SOURCE,
    )
    silver_stock_factor_pro_path(lake, str(DAY)).unlink()
    with repair_job_context(job) as repair:
        failed = repair.execute_in_process(
            instance=instance,
            run_config=repair_config(source_id, original),
            raise_on_error=False,
        )
    assert not failed.success
    failure = failed.failure_data_for_node("repair_stk_factor_pro_history")
    assert "原日期Silver不可用" in failure.error.message
    known_pg = {}
    with (
        patch.object(
            instance, "get_run_records", wraps=instance.get_run_records
        ) as runs,
        patch.object(
            instance, "fetch_observations", wraps=instance.fetch_observations
        ) as observations,
    ):
        facts = asset.readiness.read_stk_factor_pro_recorded_results(
            instance, target_trade_date=DAY, known_pg=known_pg
        )
        assert runs.call_count == 1 and runs.call_args.kwargs["limit"] == 2
        assert observations.call_count == 2
        assert all(call.kwargs["limit"] == 1 for call in observations.call_args_list)
    assert facts.day_result_ref.run_id == source_id
    assert facts.unresolved_day_failure_run_id is None
    assert facts.unresolved_history_failure_run_id == failed.run_id
    assert asset.readiness.read_stk_factor_pro_failure(
        instance, facts.unresolved_history_failure_run_id, known_pg=known_pg
    ) == {"retryable": False, "failure_phase": "history"}


def test_explicit_initialization_repair_updates_only_touched_import_record(
    tmp_path, monkeypatch, actual_job
):
    from datetime import date

    from tests.stk_factor_pro_bootstrap_test_support import approval_fixture, native_row
    from tests.stk_factor_pro_history_test_support import write_factor_file
    from tests.stk_factor_pro_test_support import row
    from tests.test_stk_factor_pro_bootstrap_coverage import upstream
    from tests.test_stk_factor_pro_bootstrap_process import IsolatedInstance
    from tests.test_stk_factor_pro_bootstrap_source import FakeProd
    from tests.test_stk_factor_pro_jobs import B

    instance, job, set_source, lake, staging, counts = actual_job
    previous, day = date(2019, 10, 15), date(2019, 10, 16)
    instance.add_dynamic_partitions(
        asset.C.STK_FACTOR_PRO_PARTITIONS, [str(previous), str(day)]
    )
    original_counts = ((previous, 1), (day, 1))
    known = {}
    with connection(tmp_path) as conn:
        _, _, approval, source_identity = approval_fixture(
            conn,
            tmp_path,
            counts=original_counts,
            known_records=known,
        )
        upstream(conn, lake, (previous, day), codes=(A, B))
        remote = FakeProd(
            approval,
            source_identity,
            original_counts,
            [
                native_row(A, day=previous),
                native_row(A, day=day),
            ],
        )
        asset.initialization._run_stk_factor_pro_bootstrap(
            conn,
            lake_root=lake,
            staging_root=staging,
            operation_id=approval.operation_id,
            instance=IsolatedInstance(),
            prod_postgres=remote,
        )
        write_factor_file(conn, lake, previous, ((A, 1), (B, 1)))
        write_factor_file(conn, lake, day, ((A, 2), (B, 1)))
    result_path = asset.records.operation_path(
        staging, approval, f"coverage/{day}/result.json"
    )
    past_path = asset.records.operation_path(
        staging, approval, f"coverage/{previous}/result.json"
    )
    day_cfg = config(
        day,
        execution_day=asset.initialization._now().date(),
        purpose="bootstrap_supplement",
        slot=None,
    )
    day_cfg["ops"]["stk_factor_pro"]["config"].update(
        bootstrap_operation_id=approval.operation_id,
        expected_bootstrap_approval_digest=known[
            asset.records.operation_path(staging, approval, "approval.json")
        ][1],
        expected_bootstrap_date_result_digest=asset.factor_known_file_sha(
            result_path, known_records={}
        ),
    )
    today = set_source((row(B, day.strftime("%Y%m%d")),), day)
    history = HistoryDownloader({A: (row(A, day.strftime("%Y%m%d")),)})

    class IncompleteHistory:
        def download(self, task, **kwargs):
            return (today if task.mode is DownloadMode.BY_POINT else history).download(
                task, **kwargs
            )

    monkeypatch.setattr(asset.download.TushareDownloader, "load", IncompleteHistory)
    first = job.execute_in_process(
        instance=instance,
        partition_key=str(day),
        run_config=day_cfg,
        raise_on_error=False,
    )
    assert not first.success
    assert (
        first.failure_data_for_node("stk_factor_pro")
        .user_failure_data.metadata["goldenshare/retryable"]
        .value
        is True
    )
    assert len(today.calls) == len(history.calls) == 1
    current_t = result_path.read_bytes()
    old_p = past_path.read_bytes()
    assert tuple(len(counts[k]) for k in ("dates", "types", "aggregate")) == (0, 1, 1)
    for calls in counts.values():
        calls.clear()
    original = asset.history.read_stk_factor_pro_history_plan(
        asset.stk_factor_pro_run_staging_root(staging, first.run_id, str(day)),
        expected_target=day,
        expected_run_id=first.run_id,
        known_records={},
    )
    fixed = HistoryDownloader(
        {
            A: (
                row(A, previous.strftime("%Y%m%d"), close=42),
                row(A, day.strftime("%Y%m%d")),
            )
        }
    )
    monkeypatch.setattr(asset.download.TushareDownloader, "load", lambda: fixed)
    with repair_job_context(job) as repair:
        repaired = repair.execute_in_process(
            instance=instance,
            run_config=repair_config(first.run_id, original, day),
            raise_on_error=False,
        )
    assert repaired.success, repaired.failure_data_for_node(
        "repair_stk_factor_pro_history"
    ).error.to_string()
    assert (
        len(fixed.calls) == 1 and fixed.calls[0][0].mode is DownloadMode.BY_OBJECT_RANGE
    )
    assert result_path.read_bytes() == current_t and past_path.read_bytes() != old_p
    recorded = asset.records.read_json(
        past_path, asset.C.StkFactorProBootstrapDateCoverage, known_records={}
    )
    assert recorded.current_publication.run_id == repaired.run_id
    assert (
        recorded.source_rows,
        recorded.raw_rows,
        recorded.silver_rows,
        recorded.missing_count,
    ) == (1, 1, 1, 1)
    assert all(not calls for calls in counts.values())
