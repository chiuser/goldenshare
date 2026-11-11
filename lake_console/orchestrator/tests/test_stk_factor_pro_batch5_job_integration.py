"""Real update job, real Dagster storage and offline replay across process exit."""

import json
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from subprocess import run
from time import perf_counter

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.definitions.job_base import InMemoryJob
from dagster._core.execution.api import execute_run
from pytest import MonkeyPatch

from orchestrator.defs.assets import stk_factor_pro as asset
from orchestrator.defs.checks import stk_factor_pro as checks
from orchestrator.defs.io import stk_factor_pro_candidates as candidates
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    stk_factor_pro_run_staging_root,
)
from orchestrator.defs.sensors.readiness import (
    RAW_ADJ_FACTOR_READINESS_SPEC,
    RAW_STOCK_BASIC_READINESS_SPEC,
    SILVER_STOCK_LIFECYCLE_READINESS_SPEC,
    SUSPEND_D_READINESS_SPECS,
)
from orchestrator.tushare_download.configuration import ConfigurationSnapshot
from orchestrator.tushare_download.contract_registry import ContractRegistry
from orchestrator.tushare_download.contracts import CONTRACTS
from orchestrator.tushare_download.dataset_transport_mapping import (
    BINDINGS,
    DatasetTransportMapping,
)
from orchestrator.tushare_download.download_api import _build_downloader
from tests.stk_factor_pro_history_test_support import saved_real_rows, write_factor_file
from tests.stk_factor_pro_test_support import DAY, NAMES, connection, row
from tests.test_stk_factor_pro_bootstrap_coverage import upstream
from tests.test_stk_factor_pro_history_integration import ObservedDownloader
from tests.test_stk_factor_pro_jobs import (
    PREVIOUS,
    A,
    B,
    config,
    isolated_update_environment,
)
from tests.tushare_download.fixtures import FakeClock, ScriptTransport

DAYS = tuple(date(2026, 10, n) for n in range(12, 17))


def seed_upstream_events(instance):
    """Seed real bound upstream events for independent producer-shaped fixture files."""

    @dg.op(out={})
    def published_upstream(context):
        checks = [
            (spec, day)
            for specs, days in (
                ((RAW_ADJ_FACTOR_READINESS_SPEC,), (PREVIOUS, DAY)),
                (SUSPEND_D_READINESS_SPECS, (DAY,)),
                (
                    (
                        RAW_STOCK_BASIC_READINESS_SPEC,
                        SILVER_STOCK_LIFECYCLE_READINESS_SPEC,
                    ),
                    (None,),
                ),
            )
            for spec in specs
            for day in days
        ]
        for spec, day in checks:
            yield dg.AssetMaterialization(
                spec.asset_key, partition=None if day is None else str(day)
            )
        records = context.instance.get_records_for_run(
            context.run.run_id,
            of_type=dg.DagsterEventType.ASSET_MATERIALIZATION,
        ).records
        materializations = {(r.asset_key, r.partition_key): r for r in records}
        for spec, day in checks:
            asset_key = spec.asset_key
            materialization = materializations[
                (asset_key, None if day is None else str(day))
            ]
            for name in spec.blocking_check_names:
                yield AssetCheckEvaluation(
                    asset_key=asset_key,
                    check_name=name,
                    passed=True,
                    partition=None if day is None else str(day),
                    blocking=True,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=materialization.storage_id,
                        run_id=context.run.run_id,
                        timestamp=materialization.timestamp,
                    ),
                )

    @dg.job
    def upstream_job():
        published_upstream()

    assert upstream_job.execute_in_process(instance=instance).success


def offline_source(rows, requests):
    clock = FakeClock()

    def respond(request, attempt):
        assert request.api_name == "stk_factor_pro" and request.fields == NAMES
        params = dict(request.params)
        if "trade_date" in params:
            assert params == {"trade_date": "20261016", "limit": 10000, "offset": 0}
            return (rows[-1], row(B, "20261016"))
        assert params == {
            "ts_code": A,
            "start_date": "20261012",
            "end_date": "20261016",
            "limit": 10000,
            "offset": 0,
        }
        return rows

    native = _build_downloader(
        ConfigurationSnapshot("offline-placeholder", "http://offline.invalid"),
        ContractRegistry(CONTRACTS),
        DatasetTransportMapping(BINDINGS),
        lambda *_: ScriptTransport(respond, requests),
        clock,
        clock.sleep,
    )
    return ObservedDownloader(native)


def worker(base, phase):
    previous = (
        json.loads((base / "before-exit.json").read_text())
        if phase == "recover"
        else None
    )
    old_root = (
        stk_factor_pro_run_staging_root(base / "staging", previous["run_id"], str(DAY))
        if previous
        else None
    )
    rows = saved_real_rows()
    requests = []
    downloader = offline_source(rows, requests)
    started = perf_counter()
    costs = Counter()
    peak = 0

    def observe_sql(sql):
        costs["parquet_queries"] += "read_parquet" in sql.lower()
        costs["history_batch_reads"] += sql.lstrip().startswith(
            "CREATE TEMP TABLE stk_factor_pro_history_batch_source "
        )
        costs["candidate_copies"] += (
            sql.lstrip().startswith("COPY") and "/candidates/" in sql
        )

    def sample():
        nonlocal peak
        peak = max(
            peak,
            sum(p.stat().st_size for p in (base / "staging").rglob("*") if p.is_file()),
        )

    with (
        MonkeyPatch.context() as patch,
        isolated_update_environment(
            base,
            patch,
            substitute_upstream=False,
            old_run_root=old_root,
            observe_sql=observe_sql,
        ) as (instance, job, _, lake, staging, counts),
    ):
        patch.setattr(asset.download.TushareDownloader, "load", lambda: downloader)
        instance.add_dynamic_partitions(
            asset.C.STK_FACTOR_PRO_PARTITIONS, [str(DAYS[0])]
        )
        if previous is None:
            with connection(base) as conn:
                upstream(conn, lake, DAYS, codes=(A, B))
                write_factor_file(conn, lake, PREVIOUS, ((A, 1), (B, 1)))
                write_factor_file(conn, lake, DAY, ((A, 2), (B, 1)))
                prior = raw_stk_factor_pro_path(lake, str(DAYS[0]))
                prior.parent.mkdir(parents=True)
                frame = candidates.build_stk_factor_pro_raw_batch(
                    rows=(rows[0], row(B, "20261012", close=123)),
                    source="http",
                    source_fields=NAMES,
                    expected_dates=(DAYS[0],),
                )
                conn.register("existing", frame)
                conn.execute("COPY existing TO ? (FORMAT PARQUET)", [str(prior)])
            seed_upstream_events(instance)
            instance.report_runless_asset_event(
                dg.AssetMaterialization(asset._RAW, partition=str(DAYS[0]))
            )
        replace_file = os.replace
        hash_file = checks.factor_file_sha

        def observed_replace(source, target):
            target = Path(target)
            if target.is_relative_to(lake) or target.is_relative_to(staging):
                costs["atomic_replaces"] += 1
                costs["formal_replaces"] += target.is_relative_to(lake)
                costs["json_record_writes"] += target.suffix == ".json"
                sample()
            return replace_file(source, target)

        def observed_hash(path):
            costs["sha_reads"] += 1
            costs["sha_bytes"] += path.stat().st_size
            return hash_file(path)

        patch.setattr(os, "replace", observed_replace)
        for module in (
            checks,
            asset.history,
            asset.download,
            asset.publication,
            asset.records,
        ):
            if hasattr(module, "factor_file_sha"):
                patch.setattr(module, "factor_file_sha", observed_hash)
        if phase == "exit":
            publish = asset.publication.publish_stk_factor_pro_history

            def exit_after_raw(*args, **kwargs):
                for target, audit in publish(*args, **kwargs):
                    if target.layer == "raw" and audit is not None:
                        run_id = kwargs["plan"].identity.creator_run_id
                        root = stk_factor_pro_run_staging_root(
                            staging, run_id, str(DAY)
                        )
                        assert (root / "source/history/source-complete.json").is_file()
                        assert not silver_stock_factor_pro_path(
                            lake, str(DAYS[0])
                        ).exists()
                        (base / "before-exit.json").write_text(
                            json.dumps(
                                {
                                    "run_id": run_id,
                                    "requests": len(requests),
                                    "start_queries": [
                                        len(counts[k])
                                        for k in ("dates", "types", "aggregate")
                                    ],
                                    "elapsed_s": perf_counter() - started,
                                    "cost": dict(costs),
                                    "observed_peak_staging_bytes": peak,
                                }
                            )
                        )
                        os._exit(17)
                    yield target, audit

            patch.setattr(
                asset.publication, "publish_stk_factor_pro_history", exit_after_raw
            )
            job.execute_in_process(
                instance=instance, partition_key=str(DAY), run_config=config()
            )
            raise AssertionError("worker did not exit at the committed history Raw")
        if previous is None:
            result = job.execute_in_process(
                instance=instance, partition_key=str(DAY), run_config=config()
            )
        else:
            parent = instance.get_run_by_id(previous["run_id"])
            assert parent.status == dg.DagsterRunStatus.STARTED
            # After seeing the real exit, the test instance records the terminal
            # status that the production run monitor would provide.
            instance.report_run_failed(
                parent, "isolated worker exited after history Raw"
            )
            parent = instance.get_run_by_id(parent.run_id)
            assert parent.status == dg.DagsterRunStatus.FAILURE
            old_files = Path.open

            def reject_previous(path, *args, **kwargs):
                assert not any(
                    path.is_relative_to(old_root / part)
                    for part in ("source", "candidates")
                )
                return old_files(path, *args, **kwargs)

            patch.setattr(Path, "open", reject_previous)
            fresh = instance.create_run_for_job(
                job,
                parent_run_id=parent.run_id,
                root_run_id=parent.run_id,
                tags=parent.tags,
                run_config=parent.run_config,
            )
            result = execute_run(InMemoryJob(job), fresh, instance, raise_on_error=True)
        assert result.success
        facts = asset.readiness.read_stk_factor_pro_recorded_results(
            instance, target_trade_date=DAY, known_pg={}
        )
        assert (
            facts.raw_coverage.complete is True
            and len(facts.successful_publication_refs) == 1
        )
        assert not facts.pending_plan_refs
        verify_started = perf_counter()
        with connection(base) as conn:
            for day in DAYS:
                raw, silver = (
                    raw_stk_factor_pro_path(lake, str(day)),
                    silver_stock_factor_pro_path(lake, str(day)),
                )
                assert conn.execute(
                    "SELECT typeof(trade_date) FROM read_parquet(?,hive_partitioning=false) LIMIT 1",
                    [str(raw)],
                ).fetchone() == ("VARCHAR",)
                assert conn.execute(
                    "SELECT typeof(trade_date) FROM read_parquet(?,hive_partitioning=false) LIMIT 1",
                    [str(silver)],
                ).fetchone() == ("DATE",)
            actual = conn.execute(
                "SELECT close,pe,macd_bfq FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=?",
                [str(raw_stk_factor_pro_path(lake, str(DAYS[0]))), B],
            ).fetchone()
            assert actual == (123.0, None, -1.25)
        root = stk_factor_pro_run_staging_root(staging, result.run_id, str(DAY))
        (base / f"{phase}-result.json").write_text(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "requests": len(requests),
                    "start_queries": [
                        len(counts[k]) for k in ("dates", "types", "aggregate")
                    ],
                    "staged_source_units": len(
                        list((root / "source/history/units").glob("*.parquet"))
                    ),
                    "elapsed_s": verify_started - started,
                    "readback_s": perf_counter() - verify_started,
                    "published_files": len(result.get_asset_materialization_events()),
                    "check_events": len(result.get_asset_check_evaluations()),
                    "cost": dict(costs),
                    "observed_peak_staging_bytes": peak,
                    "staging_bytes": sum(
                        path.stat().st_size
                        for path in root.rglob("*")
                        if path.is_file()
                    ),
                }
            )
        )


def test_actual_job_hard_exit_then_native_reexecution_downloads_fresh(tmp_path):
    project = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-B",
        "-m",
        "tests.test_stk_factor_pro_batch5_job_integration",
    ]
    env = os.environ.copy()
    for key in ("DAGSTER_HOME", "TUSHARE_TOKEN", "TUSHARE_BASE_URL"):
        env.pop(key, None)
    for phase, expected_status in (("exit", 17), ("recover", 0)):
        finished = run(
            [*command, str(tmp_path), phase],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        assert finished.returncode == expected_status, finished.stderr[-16000:]
    before = json.loads((tmp_path / "before-exit.json").read_text())
    after = json.loads((tmp_path / "recover-result.json").read_text())
    assert before["run_id"] != after["run_id"]
    assert before["requests"] == after["requests"] == 2
    assert before["start_queries"] == [1, 1, 1] and after["start_queries"] == [0, 0, 0]
    assert after["staged_source_units"] == 1
    assert after["published_files"] == after["check_events"] == 10
    assert after["cost"]["history_batch_reads"] == 1


def test_actual_normal_job_offline_replay_and_cost(tmp_path):
    worker(tmp_path, "normal")
    completed = json.loads((tmp_path / "normal-result.json").read_text())
    assert completed["requests"] == 2 and completed["staged_source_units"] == 1
    assert completed["start_queries"] == [1, 1, 1]
    assert completed["published_files"] == completed["check_events"] == 10
    assert completed["cost"]["history_batch_reads"] == 1


if __name__ == "__main__":
    worker(Path(sys.argv[1]), sys.argv[2])
