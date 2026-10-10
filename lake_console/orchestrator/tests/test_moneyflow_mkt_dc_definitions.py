"""Market moneyflow jobs/checks use fake source/clock and isolated files/instance."""

import json
import os
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import dagster as dg
import pytest

import orchestrator.defs.assets.moneyflow_mkt_dc as assets
import orchestrator.defs.io.moneyflow_mkt_dc_update as update
import orchestrator.defs.io.moneyflow_update_publication as publication
from orchestrator.defs.catalog import get_lake_asset_catalog_entry
from orchestrator.defs.checks.moneyflow_mkt_dc import (
    raw_tushare_moneyflow_mkt_dc_file_contract_check,
    silver_moneyflow_mkt_dc_standardization_check,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
    moneyflow_writer_lock,
)
from orchestrator.defs.jobs.moneyflow_mkt_dc import (
    raw_tushare_moneyflow_mkt_dc_update_job,
    silver_moneyflow_mkt_dc_update_job,
)
from orchestrator.defs.partitions import cn_a_moneyflow_mkt_dc_trade_days
from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MKT_DC_FIELDS,
    MoneyflowContractError,
)

DAY = "2026-09-30"
RAW = assets.raw_tushare_moneyflow_mkt_dc
SILVER = assets.silver_moneyflow_mkt_dc
CHECKS = [
    raw_tushare_moneyflow_mkt_dc_file_contract_check,
    silver_moneyflow_mkt_dc_standardization_check,
]


def row(amount="-123.4567", day=DAY):
    return {
        f: day.replace("-", "")
        if f == "trade_date"
        else None
        if f == "close_sh"
        else amount
        for f in MONEYFLOW_MKT_DC_FIELDS
    }


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class Source:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def call(self, api, params, fields):
        self.calls.append((api, params, fields))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(columns=MONEYFLOW_MKT_DC_FIELDS, rows=response)


class IsolatedLake(LakeRootResource):
    def ensure_available_for_run(self):
        assert self.root().is_dir() and "/Volumes" not in str(self.root())


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("DAGSTER_HOME", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    lake, staging = tmp_path / "lake", tmp_path / "staging"
    lake.mkdir()
    staging.mkdir()
    monkeypatch.setattr(assets, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    # Real free-space guard is tested separately; tiny CI temp disks need not be 64GiB.
    monkeypatch.setattr(
        publication.shutil, "disk_usage", lambda _: SimpleNamespace(free=128 * 1024**3)
    )
    original = update.build_market_moneyflow_raw_candidate

    def build(**kwargs):
        clock = Clock()
        return original(**kwargs, clock=clock, sleep_fn=clock.sleep)

    monkeypatch.setattr(update, "build_market_moneyflow_raw_candidate", build)
    source = Source([[row()], [row()]])
    defs = dg.Definitions(
        assets=[RAW, SILVER],
        asset_checks=CHECKS,
        jobs=[
            raw_tushare_moneyflow_mkt_dc_update_job,
            silver_moneyflow_mkt_dc_update_job,
        ],
        resources={
            "lake_root": IsolatedLake(root_path=str(lake)),
            "tushare": dg.ResourceDefinition.hardcoded_resource(source),
            "duckdb": dg.ResourceDefinition.hardcoded_resource(SimpleNamespace()),
        },
    )
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    with dg.DagsterInstance.local_temp(
        str(instance_dir), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        assert instance.telemetry_enabled is False
        instance.add_dynamic_partitions(
            cn_a_moneyflow_mkt_dc_trade_days.name, [DAY, "2026-09-29"]
        )
        yield SimpleNamespace(
            defs=defs, instance=instance, source=source, lake=lake, staging=staging
        )


def run(env, name, *, day=DAY, raise_on_error=True):
    return env.defs.resolve_job_def(name).execute_in_process(
        instance=env.instance, partition_key=day, raise_on_error=raise_on_error
    )


def test_definitions_catalog_and_job_selection_are_independent(env):
    dg.Definitions.validate_loadable(env.defs)
    assert (
        RAW.partitions_def is SILVER.partitions_def is cn_a_moneyflow_mkt_dc_trade_days
    )
    assert SILVER.asset_deps[SILVER.key] == {RAW.key}
    for asset, check, name in (
        (RAW, CHECKS[0], "raw_tushare_moneyflow_mkt_dc_update_job"),
        (SILVER, CHECKS[1], "silver_moneyflow_mkt_dc_update_job"),
    ):
        entry = get_lake_asset_catalog_entry(asset.key.to_user_string())
        assert (
            entry.dataset_id == "moneyflow_mkt_dc" and entry.group_name == "moneyflow"
        )
        assert entry.column_schema is not None and len(entry.column_schema) == 15
        assert {s.name for s in check.check_specs} == set(entry.blocking_check_names)
        assert check.partitions_def is cn_a_moneyflow_mkt_dc_trade_days
        assert all(s.blocking for s in check.check_specs)
        job = env.defs.resolve_job_def(name)
        assert job.asset_layer.executable_asset_keys == {asset.key}
    assert (
        get_lake_asset_catalog_entry(RAW.key.to_user_string())
        .bootstrap_sources[0]
        .value
        == "prod_db_readonly"
    )


def test_real_partitioned_jobs_checks_and_storage_attribution(env):
    started = perf_counter()
    first = run(env, "raw_tushare_moneyflow_mkt_dc_update_job")
    assert first.success
    raw_path = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    assert (
        raw_path.is_file()
        and not silver_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY).exists()
    )
    second = run(env, "silver_moneyflow_mkt_dc_update_job")
    assert second.success and len(env.source.calls) == 2
    events = []
    for result, check in ((first, CHECKS[0]), (second, CHECKS[1])):
        evaluations = result.get_asset_check_evaluations()
        assert len(evaluations) == 1 and evaluations[0].passed
        assert evaluations[0].partition == DAY
        key = next(iter(check.check_keys))
        history = env.instance.event_log_storage.get_asset_check_execution_history(
            key, limit=2
        )
        assert history[0].partition == DAY and history[0].status.value == "SUCCEEDED"
        events.append(
            {
                "run_id": result.run_id,
                "asset_key": key.asset_key.to_user_string(),
                "check_name": key.name,
                "evaluation_partition": evaluations[0].partition,
                "storage_partition": history[0].partition,
                "storage_status": history[0].status.value,
                "passed": evaluations[0].passed,
            }
        )
    for api, params, fields in env.source.calls:
        assert api == "moneyflow_mkt_dc" and params == {
            "trade_date": "20260930",
            "limit": 2000,
            "offset": 0,
        }
        assert fields == MONEYFLOW_MKT_DC_FIELDS
    silver = silver_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    with moneyflow_candidate_connection(env.staging) as c:
        values = c.execute(
            "SELECT trade_date,close_sh,net_amount FROM read_parquet(?,hive_partitioning=false)",
            [str(silver)],
        ).fetchone()
    assert (
        values[0].isoformat() == DAY
        and values[1] is None
        and str(values[2]) == "-123.4567"
    )
    (env.staging / "partition-job-evidence.json").write_text(
        json.dumps(
            {
                "scope": "isolated_fake_source_and_clock",
                "partition": DAY,
                "events": events,
                "requests": env.source.calls,
                "row_counts": {"source_per_round": 1, "raw": 1, "silver": 1},
                "silver_sample": {
                    "trade_date": values[0].isoformat(),
                    "close_sh": values[1],
                    "net_amount": str(values[2]),
                },
                "files": [
                    {
                        "path": str(p),
                        "sha256": candidate_file_hash(p),
                        "bytes": p.stat().st_size,
                    }
                    for p in (raw_path, silver)
                ],
                "elapsed_seconds_including_jobs_but_virtual_stability_wait": perf_counter()
                - started,
            },
            indent=2,
        )
    )


@pytest.mark.parametrize(
    "responses",
    [
        [[], []],
        [[row()], [row("1.0000")]],
        [[row(), row()], [row()]],
        [[row(day="2026-09-29")], [row()]],
    ],
)
def test_source_failure_never_publishes_or_materializes(env, responses):
    env.source.responses = iter(responses)
    result = run(env, "raw_tushare_moneyflow_mkt_dc_update_job", raise_on_error=False)
    assert not result.success and result.get_asset_materialization_events() == []
    assert not raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY).exists()
    assert not any(e.passed for e in result.get_asset_check_evaluations())


def test_silver_missing_raw_readiness_fails_without_source_requests(env):
    result = run(env, "silver_moneyflow_mkt_dc_update_job", raise_on_error=False)
    assert not result.success and not env.source.calls
    assert not silver_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY).exists()


def test_silver_missing_other_day_readiness_is_not_inherited(env):
    assert run(env, "raw_tushare_moneyflow_mkt_dc_update_job").success
    result = run(
        env,
        "silver_moneyflow_mkt_dc_update_job",
        day="2026-09-29",
        raise_on_error=False,
    )
    assert not result.success and len(env.source.calls) == 2


def test_changed_raw_after_green_event_cannot_feed_silver(env):
    assert run(env, "raw_tushare_moneyflow_mkt_dc_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    raw.write_bytes(b"changed after green")
    result = run(env, "silver_moneyflow_mkt_dc_update_job", raise_on_error=False)
    assert not result.success and len(env.source.calls) == 2
    assert not silver_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY).exists()


def test_same_values_reuse_and_source_revision_updates_only_raw(env):
    assert run(env, "raw_tushare_moneyflow_mkt_dc_update_job").success
    assert run(env, "silver_moneyflow_mkt_dc_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    silver = silver_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    raw_before, silver_before = raw.stat().st_mtime_ns, candidate_file_hash(silver)
    env.source.responses = iter([[row()], [row()]])
    assert run(env, "raw_tushare_moneyflow_mkt_dc_update_job").success
    assert raw.stat().st_mtime_ns == raw_before
    env.source.responses = iter([[row("1.2345")], [row("1.2345")]])
    assert run(env, "raw_tushare_moneyflow_mkt_dc_update_job").success
    assert candidate_file_hash(silver) == silver_before
    assert run(env, "silver_moneyflow_mkt_dc_update_job").success
    assert candidate_file_hash(silver) != silver_before and len(env.source.calls) == 6


def test_existing_invalid_file_is_not_overwritten(env):
    raw = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"invalid original")
    result = run(env, "raw_tushare_moneyflow_mkt_dc_update_job", raise_on_error=False)
    assert not result.success and raw.read_bytes() == b"invalid original"


def test_writer_lock_stops_before_source_request(env):
    namespace = env.staging / "moneyflow"
    namespace.mkdir()
    with moneyflow_writer_lock(namespace):
        result = run(
            env, "raw_tushare_moneyflow_mkt_dc_update_job", raise_on_error=False
        )
    assert not result.success and not env.source.calls


def test_complete_checkpoint_failure_resumes_moved_file_without_source(
    env, monkeypatch
):
    original = publication._checkpoint

    def interrupted(path, state):
        if state["stage"] == "complete":
            raise RuntimeError("exit after replace")
        original(path, state)

    monkeypatch.setattr(publication, "_checkpoint", interrupted)
    with pytest.raises(RuntimeError, match="exit after replace"):
        update.update_market_moneyflow_raw(
            tushare=env.source,
            lake_root=env.lake,
            staging_root=env.staging,
            operation_id="resume",
            trade_date=DAY,
        )
    raw = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    before = candidate_file_hash(raw)
    assert not (
        env.staging / "moneyflow/resume/moneyflow_mkt_dc" / DAY / "raw.parquet"
    ).exists()
    monkeypatch.setattr(publication, "_checkpoint", original)
    result = update.update_market_moneyflow_raw(
        tushare=env.source,
        lake_root=env.lake,
        staging_root=env.staging,
        operation_id="resume",
        trade_date=DAY,
    )
    assert result["file_sha256"] == before and len(env.source.calls) == 2


def test_cancellation_preserves_old_target_and_can_resume_candidate(env):
    count = 0

    def cancel():
        nonlocal count
        count += 1
        # Direct _publish cancellation is before any replace.
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        update.update_market_moneyflow_raw(
            tushare=env.source,
            lake_root=env.lake,
            staging_root=env.staging,
            operation_id="cancel",
            trade_date=DAY,
            check_cancel=cancel,
        )
    assert count == 1 and not env.source.calls
    assert not raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY).exists()


@pytest.mark.parametrize("kind", ["overlap", "symlink", "space", "device"])
def test_root_rejections_precede_source_or_candidates(env, monkeypatch, kind):
    lake = env.lake
    if kind == "overlap":
        lake = env.staging
    elif kind == "symlink":
        lake = env.lake.parent / "link"
        lake.symlink_to(env.lake, target_is_directory=True)
    elif kind == "space":
        monkeypatch.setattr(
            publication.shutil, "disk_usage", lambda _: SimpleNamespace(free=1)
        )
    else:
        original = Path.stat

        def stat(p, **kw):
            value = original(p, **kw)
            return (
                os.stat_result((*value[:2], 123, *value[3:]))
                if p == env.lake
                else value
            )

        monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises(MoneyflowContractError):
        update.update_market_moneyflow_raw(
            tushare=env.source,
            lake_root=lake,
            staging_root=env.staging,
            operation_id="badroot",
            trade_date=DAY,
        )
    assert not env.source.calls


def test_no_sensor_prod_or_other_dataset_definitions_added():
    for directory in ("assets", "checks", "jobs"):
        text = Path(
            f"src/orchestrator/defs/{directory}/moneyflow_mkt_dc.py"
        ).read_text()
        assert (
            "ProdPostgres" not in text
            and "core_serving" not in text
            and "BIYING" not in text
            and "orchestrator.defs.catalog" not in text
        )
    assert (
        "@dg.sensor"
        not in Path("src/orchestrator/defs/assets/moneyflow_mkt_dc.py").read_text()
    )


def _check_existing_file(env, check):
    # Current SDK does not infer a partition definition for a checks-only job.
    # This isolated asset stub leaves the injected damaged file untouched;
    # the original check still executes in a genuinely partitioned asset job.
    asset = RAW if check is CHECKS[0] else SILVER
    path = (raw_moneyflow_path if asset is RAW else silver_moneyflow_path)(
        env.lake, "moneyflow_mkt_dc", DAY
    )

    @dg.asset(
        name=asset.key.to_user_string(),
        partitions_def=cn_a_moneyflow_mkt_dc_trade_days,
        deps=[] if asset is RAW else [RAW],
    )
    def existing_file():
        return dg.MaterializeResult(
            metadata={"goldenshare/file_sha256": candidate_file_hash(path)}
        )

    job = dg.define_asset_job(
        name="market_existing_file_check",
        selection=dg.AssetSelection.assets(existing_file)
        | dg.AssetSelection.checks(check),
        partitions_def=cn_a_moneyflow_mkt_dc_trade_days,
    )
    defs = dg.Definitions(
        assets=[
            existing_file if asset is RAW else RAW,
            existing_file if asset is SILVER else SILVER,
        ],
        asset_checks=CHECKS,
        jobs=[job],
        resources=env.defs.resources,
    )
    result = defs.resolve_job_def(job.name).execute_in_process(
        instance=env.instance, partition_key=DAY, raise_on_error=False
    )
    history = env.instance.event_log_storage.get_asset_check_execution_history(
        next(iter(check.check_keys)), limit=1
    )
    assert history[0].partition == DAY and history[0].status.value == "FAILED"
    return result


def _change_file(env, path, projection):
    changed = env.staging / "changed.parquet"
    with moneyflow_candidate_connection(env.staging) as c:
        c.execute(
            f"COPY (SELECT {projection} FROM read_parquet($source,hive_partitioning=false)) TO $target (FORMAT PARQUET)",
            {"source": str(path), "target": str(changed)},
        )
    os.replace(changed, path)


def test_wrong_raw_date_records_failed_partition_check_and_blocks_silver(env):
    assert run(env, "raw_tushare_moneyflow_mkt_dc_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    _change_file(env, raw, "* REPLACE('20260929'::VARCHAR AS trade_date)")
    result = _check_existing_file(env, CHECKS[0])
    assert not result.success
    evaluation = result.get_asset_check_evaluations()[0]
    assert not evaluation.passed and evaluation.partition == DAY
    assert evaluation.metadata["goldenshare/reason_code"].value == "file_count_or_date"
    assert not run(
        env, "silver_moneyflow_mkt_dc_update_job", raise_on_error=False
    ).success
    assert len(env.source.calls) == 2


def test_silver_amount_difference_records_failed_partition_check(env):
    assert run(env, "raw_tushare_moneyflow_mkt_dc_update_job").success
    assert run(env, "silver_moneyflow_mkt_dc_update_job").success
    silver = silver_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    _change_file(env, silver, "* REPLACE(999::DECIMAL(24,4) AS net_amount)")
    result = _check_existing_file(env, CHECKS[1])
    assert not result.success
    evaluation = result.get_asset_check_evaluations()[0]
    assert not evaluation.passed and evaluation.partition == DAY
    assert (
        evaluation.metadata["goldenshare/reason_code"].value
        == "standardization_difference"
    )


def test_target_change_after_intent_is_not_overwritten(env, monkeypatch):
    assert run(env, "raw_tushare_moneyflow_mkt_dc_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    env.source.responses = iter([[row("2.0000")], [row("2.0000")]])
    original = publication._checkpoint

    def alter(path, state):
        original(path, state)
        if state["stage"] == "intent":
            raw.write_bytes(b"external writer changed target")

    monkeypatch.setattr(publication, "_checkpoint", alter)
    with pytest.raises(MoneyflowContractError, match="update_target_changed"):
        update.update_market_moneyflow_raw(
            tushare=env.source,
            lake_root=env.lake,
            staging_root=env.staging,
            operation_id="target-change",
            trade_date=DAY,
        )
    assert raw.read_bytes() == b"external writer changed target"


def test_cancel_after_intent_preserves_candidate_and_resumes_without_source(
    env, monkeypatch
):
    original = publication._checkpoint
    cancel = {"requested": False}

    def checkpoint(path, state):
        original(path, state)
        if state["stage"] == "intent":
            cancel["requested"] = True

    def check_cancel():
        if cancel["requested"]:
            raise MoneyflowContractError("user_cancel")

    monkeypatch.setattr(publication, "_checkpoint", checkpoint)
    kwargs = {
        "tushare": env.source,
        "lake_root": env.lake,
        "staging_root": env.staging,
        "operation_id": "cancel-after-intent",
        "trade_date": DAY,
    }
    with pytest.raises(MoneyflowContractError, match="user_cancel"):
        update.update_market_moneyflow_raw(**kwargs, check_cancel=check_cancel)
    target = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    directory = (
        env.staging / "moneyflow" / kwargs["operation_id"] / "moneyflow_mkt_dc" / DAY
    )
    assert not target.exists() and (directory / "raw.parquet").is_file()
    assert (
        json.loads((directory / "promotion-raw.json").read_text())["stage"] == "intent"
    )
    monkeypatch.setattr(publication, "_checkpoint", original)
    result = update.update_market_moneyflow_raw(**kwargs)
    assert len(env.source.calls) == 2 and result["file_sha256"] == candidate_file_hash(
        target
    )


def test_formal_file_symlink_never_overwrites_external_file(env):
    external = env.staging / "external"
    external.write_bytes(b"preserve external file")
    target = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    target.parent.mkdir(parents=True)
    target.symlink_to(external)
    with pytest.raises(MoneyflowContractError, match="update_path"):
        update.update_market_moneyflow_raw(
            tushare=env.source,
            lake_root=env.lake,
            staging_root=env.staging,
            operation_id="target-symlink",
            trade_date=DAY,
        )
    assert target.is_symlink() and external.read_bytes() == b"preserve external file"


def test_silver_replace_exit_resumes_without_rebuilding_candidate(env, monkeypatch):
    assert run(env, "raw_tushare_moneyflow_mkt_dc_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    original = publication._checkpoint

    def interrupted(path, state):
        if state["stage"] == "complete":
            raise RuntimeError("silver exit after replace")
        original(path, state)

    monkeypatch.setattr(publication, "_checkpoint", interrupted)
    kwargs = {
        "lake_root": env.lake,
        "staging_root": env.staging,
        "operation_id": "silver-resume",
        "trade_date": DAY,
        "expected_raw_hash": candidate_file_hash(raw),
    }
    with pytest.raises(RuntimeError, match="silver exit after replace"):
        update.update_market_moneyflow_silver(**kwargs)
    silver = silver_moneyflow_path(env.lake, "moneyflow_mkt_dc", DAY)
    before = candidate_file_hash(silver)
    monkeypatch.setattr(publication, "_checkpoint", original)
    result = update.update_market_moneyflow_silver(**kwargs)
    assert result["file_sha256"] == before and len(env.source.calls) == 2
