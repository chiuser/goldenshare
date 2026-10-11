"""Concept moneyflow jobs/checks use fake source/clock and isolated files/instance."""

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import dagster as dg
import pytest

import orchestrator.defs.assets.moneyflow_cnt_ths as assets
import orchestrator.defs.io.moneyflow_daily_update as update
import orchestrator.defs.io.moneyflow_update_publication as publication
from orchestrator.defs.catalog import get_lake_asset_catalog_entry
from orchestrator.defs.checks.moneyflow_cnt_ths import (
    raw_tushare_moneyflow_cnt_ths_file_contract_check,
    silver_moneyflow_cnt_ths_standardization_check,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
)
from orchestrator.defs.jobs.moneyflow_cnt_ths import (
    raw_tushare_moneyflow_cnt_ths_update_job,
    silver_moneyflow_cnt_ths_update_job,
)
from orchestrator.defs.partitions import cn_a_moneyflow_cnt_ths_trade_days
from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.moneyflow import (
    MoneyflowContractError,
)
from orchestrator.defs.run_contracts.moneyflow_daily import daily_fields

DAY = "2026-09-30"
MONEYFLOW_CNT_THS_FIELDS = daily_fields("moneyflow_cnt_ths")
RAW = assets.raw_tushare_moneyflow_cnt_ths
SILVER = assets.silver_moneyflow_cnt_ths
CHECKS = [
    raw_tushare_moneyflow_cnt_ths_file_contract_check,
    silver_moneyflow_cnt_ths_standardization_check,
]


def row(amount="-123.4567", day=DAY):
    return {
        "trade_date": day.replace("-", ""),
        "ts_code": "885955.TI",
        "name": "重组蛋白",
        "lead_stock": None,
        "close_price": "30.67",
        "pct_change": "3.78",
        "industry_index": "1234567890123456.1234",
        "company_num": 128,
        "pct_change_stock": None,
        "net_buy_amount": "80.0",
        "net_sell_amount": None,
        "net_amount": amount,
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
        return SimpleNamespace(columns=MONEYFLOW_CNT_THS_FIELDS, rows=response)


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
    original = update.build_daily_moneyflow_raw_candidate

    def build(**kwargs):
        clock = Clock()
        return original(**kwargs, clock=clock, sleep_fn=clock.sleep)

    monkeypatch.setattr(update, "build_daily_moneyflow_raw_candidate", build)
    source = Source([[row()], [row()]])
    defs = dg.Definitions(
        assets=[RAW, SILVER],
        asset_checks=CHECKS,
        jobs=[
            raw_tushare_moneyflow_cnt_ths_update_job,
            silver_moneyflow_cnt_ths_update_job,
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
            cn_a_moneyflow_cnt_ths_trade_days.name, [DAY, "2026-09-29"]
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
        RAW.partitions_def is SILVER.partitions_def is cn_a_moneyflow_cnt_ths_trade_days
    )
    assert SILVER.asset_deps[SILVER.key] == {RAW.key}
    for asset, check, name in (
        (RAW, CHECKS[0], "raw_tushare_moneyflow_cnt_ths_update_job"),
        (SILVER, CHECKS[1], "silver_moneyflow_cnt_ths_update_job"),
    ):
        entry = get_lake_asset_catalog_entry(asset.key.to_user_string())
        assert (
            entry.dataset_id == "moneyflow_cnt_ths" and entry.group_name == "moneyflow"
        )
        assert entry.column_schema is not None and len(entry.column_schema) == 12
        assert {s.name for s in check.check_specs} == set(entry.blocking_check_names)
        assert check.partitions_def is cn_a_moneyflow_cnt_ths_trade_days
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
    first = run(env, "raw_tushare_moneyflow_cnt_ths_update_job")
    assert first.success
    raw_path = raw_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    assert (
        raw_path.is_file()
        and not silver_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY).exists()
    )
    second = run(env, "silver_moneyflow_cnt_ths_update_job")
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
        assert api == "moneyflow_cnt_ths" and params == {
            "trade_date": "20260930",
            "limit": 2000,
            "offset": 0,
        }
        assert fields == MONEYFLOW_CNT_THS_FIELDS
    silver = silver_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    with moneyflow_candidate_connection(env.staging) as c:
        values = c.execute(
            "SELECT trade_date,lead_stock,net_amount,industry_index FROM read_parquet(?,hive_partitioning=false)",
            [str(silver)],
        ).fetchone()
    assert (
        values[0].isoformat() == DAY
        and values[1] is None
        and str(values[2]) == "-123.4567"
        and values[3] == Decimal("1234567890123456.1234")
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
                    "lead_stock": values[1],
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
    result = run(env, "raw_tushare_moneyflow_cnt_ths_update_job", raise_on_error=False)
    assert not result.success and result.get_asset_materialization_events() == []
    assert not raw_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY).exists()
    assert not any(e.passed for e in result.get_asset_check_evaluations())


def test_silver_missing_raw_readiness_fails_without_source_requests(env):
    result = run(env, "silver_moneyflow_cnt_ths_update_job", raise_on_error=False)
    assert not result.success and not env.source.calls
    assert not silver_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY).exists()


def test_silver_missing_other_day_readiness_is_not_inherited(env):
    assert run(env, "raw_tushare_moneyflow_cnt_ths_update_job").success
    result = run(
        env,
        "silver_moneyflow_cnt_ths_update_job",
        day="2026-09-29",
        raise_on_error=False,
    )
    assert not result.success and len(env.source.calls) == 2


def test_changed_raw_after_green_event_cannot_feed_silver(env):
    assert run(env, "raw_tushare_moneyflow_cnt_ths_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    raw.write_bytes(b"changed after green")
    result = run(env, "silver_moneyflow_cnt_ths_update_job", raise_on_error=False)
    assert not result.success and len(env.source.calls) == 2
    assert not silver_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY).exists()


def test_same_values_reuse_and_source_revision_updates_only_raw(env):
    assert run(env, "raw_tushare_moneyflow_cnt_ths_update_job").success
    assert run(env, "silver_moneyflow_cnt_ths_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    silver = silver_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    raw_before, silver_before = raw.stat().st_mtime_ns, candidate_file_hash(silver)
    env.source.responses = iter([[row()], [row()]])
    assert run(env, "raw_tushare_moneyflow_cnt_ths_update_job").success
    assert raw.stat().st_mtime_ns == raw_before
    env.source.responses = iter([[row("1.2345")], [row("1.2345")]])
    assert run(env, "raw_tushare_moneyflow_cnt_ths_update_job").success
    assert candidate_file_hash(silver) == silver_before
    assert run(env, "silver_moneyflow_cnt_ths_update_job").success
    assert candidate_file_hash(silver) != silver_before and len(env.source.calls) == 6


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
        update.update_daily_moneyflow_raw(
            dataset="moneyflow_cnt_ths",
            tushare=env.source,
            lake_root=env.lake,
            staging_root=env.staging,
            operation_id="resume",
            trade_date=DAY,
        )
    raw = raw_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    before = candidate_file_hash(raw)
    assert not (
        env.staging / "moneyflow/resume/moneyflow_cnt_ths" / DAY / "raw.parquet"
    ).exists()
    monkeypatch.setattr(publication, "_checkpoint", original)
    result = update.update_daily_moneyflow_raw(
        dataset="moneyflow_cnt_ths",
        tushare=env.source,
        lake_root=env.lake,
        staging_root=env.staging,
        operation_id="resume",
        trade_date=DAY,
    )
    assert result["file_sha256"] == before and len(env.source.calls) == 2


def test_no_sensor_prod_or_other_dataset_definitions_added():
    for directory in ("assets", "checks", "jobs"):
        text = Path(
            f"src/orchestrator/defs/{directory}/moneyflow_cnt_ths.py"
        ).read_text()
        assert (
            "ProdPostgres" not in text
            and "core_serving" not in text
            and "BIYING" not in text
            and "orchestrator.defs.catalog" not in text
        )
    assert (
        "@dg.sensor"
        not in Path("src/orchestrator/defs/assets/moneyflow_cnt_ths.py").read_text()
    )


def _check_existing_file(env, check):
    # Current SDK does not infer a partition definition for a checks-only job.
    # This isolated asset stub leaves the injected damaged file untouched;
    # the original check still executes in a genuinely partitioned asset job.
    asset = RAW if check is CHECKS[0] else SILVER
    path = (raw_moneyflow_path if asset is RAW else silver_moneyflow_path)(
        env.lake, "moneyflow_cnt_ths", DAY
    )

    @dg.asset(
        name=asset.key.to_user_string(),
        partitions_def=cn_a_moneyflow_cnt_ths_trade_days,
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
        partitions_def=cn_a_moneyflow_cnt_ths_trade_days,
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
    assert run(env, "raw_tushare_moneyflow_cnt_ths_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    _change_file(env, raw, "* REPLACE('20260929'::VARCHAR AS trade_date)")
    result = _check_existing_file(env, CHECKS[0])
    assert not result.success
    evaluation = result.get_asset_check_evaluations()[0]
    assert not evaluation.passed and evaluation.partition == DAY
    assert (
        evaluation.metadata["goldenshare/reason_code"].value == "file_count_date_or_key"
    )
    assert not run(
        env, "silver_moneyflow_cnt_ths_update_job", raise_on_error=False
    ).success
    assert len(env.source.calls) == 2


def test_silver_amount_difference_records_failed_partition_check(env):
    assert run(env, "raw_tushare_moneyflow_cnt_ths_update_job").success
    assert run(env, "silver_moneyflow_cnt_ths_update_job").success
    silver = silver_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    _change_file(env, silver, "* REPLACE(999::DECIMAL(24,4) AS net_amount)")
    result = _check_existing_file(env, CHECKS[1])
    assert not result.success
    evaluation = result.get_asset_check_evaluations()[0]
    assert not evaluation.passed and evaluation.partition == DAY
    assert (
        evaluation.metadata["goldenshare/reason_code"].value
        == "standardization_difference"
    )


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
        update.update_daily_moneyflow_raw(
            dataset="moneyflow_cnt_ths", **kwargs, check_cancel=check_cancel
        )
    target = raw_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    directory = (
        env.staging / "moneyflow" / kwargs["operation_id"] / "moneyflow_cnt_ths" / DAY
    )
    assert not target.exists() and (directory / "raw.parquet").is_file()
    assert (
        json.loads((directory / "promotion-raw.json").read_text())["stage"] == "intent"
    )
    monkeypatch.setattr(publication, "_checkpoint", original)
    result = update.update_daily_moneyflow_raw(dataset="moneyflow_cnt_ths", **kwargs)
    assert len(env.source.calls) == 2 and result["file_sha256"] == candidate_file_hash(
        target
    )


def test_silver_replace_exit_resumes_without_rebuilding_candidate(env, monkeypatch):
    assert run(env, "raw_tushare_moneyflow_cnt_ths_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
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
        update.update_daily_moneyflow_silver(dataset="moneyflow_cnt_ths", **kwargs)
    silver = silver_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    before = candidate_file_hash(silver)
    monkeypatch.setattr(publication, "_checkpoint", original)
    result = update.update_daily_moneyflow_silver(dataset="moneyflow_cnt_ths", **kwargs)
    assert result["file_sha256"] == before and len(env.source.calls) == 2


def test_archived_real_387_concepts_job_source_raw_silver_reconcile(env):
    fixture = json.loads(
        Path("tests/fixtures/moneyflow_cnt_ths_20260930.json").read_text()
    )
    assert len(fixture) == 387 and len({r["ts_code"] for r in fixture}) == 387
    env.source.responses = iter([fixture, list(reversed(fixture))])
    started = perf_counter()
    first = run(env, "raw_tushare_moneyflow_cnt_ths_update_job")
    second = run(env, "silver_moneyflow_cnt_ths_update_job")
    jobs_elapsed_ms = round((perf_counter() - started) * 1000, 3)
    assert first.success and second.success and len(env.source.calls) == 2
    raw = raw_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    silver = silver_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY)
    with moneyflow_candidate_connection(env.staging) as connection:
        raw_count = connection.execute(
            "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)", [str(raw)]
        ).fetchone()[0]
        silver_count = connection.execute(
            "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)",
            [str(silver)],
        ).fetchone()[0]
        sample = connection.execute(
            "SELECT trade_date,name,company_num,net_amount FROM read_parquet(?,hive_partitioning=false) WHERE ts_code='885955.TI'",
            [str(silver)],
        ).fetchone()
    assert raw_count == silver_count == 387
    with moneyflow_candidate_connection(env.staging) as connection:
        types = {
            r[0]: r[1]
            for r in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                [str(silver)],
            ).fetchall()
        }
        assert (
            types["trade_date"] == "DATE" and types["industry_index"] == "DECIMAL(24,4)"
        )
        actual = connection.execute(
            "SELECT * FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(silver)],
        ).fetchall()
    numeric = {
        "close_price",
        "pct_change",
        "industry_index",
        "pct_change_stock",
        "net_buy_amount",
        "net_sell_amount",
        "net_amount",
    }
    expected = [
        tuple(
            date(2026, 9, 30)
            if f == "trade_date"
            else Decimal(str(r[f]))
            if f in numeric and r[f] is not None
            else r[f]
            for f in MONEYFLOW_CNT_THS_FIELDS
        )
        for r in sorted(fixture, key=lambda r: r["ts_code"])
    ]
    assert actual == expected
    assert sample[0].isoformat() == DAY and sample[1:] == ("重组蛋白", 128, 19)
    native = []
    for result, check in ((first, CHECKS[0]), (second, CHECKS[1])):
        evaluation = result.get_asset_check_evaluations()[0]
        record = env.instance.event_log_storage.get_asset_check_execution_history(
            next(iter(check.check_keys)), limit=1
        )[0]
        target = (
            record.event.dagster_event.event_specific_data.target_materialization_data
        )
        mat = env.instance.fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=next(iter(check.check_keys)).asset_key, asset_partitions=[DAY]
            ),
            limit=1,
        ).records[0]
        assert (
            evaluation.partition == record.partition == DAY
            and record.status.value == "SUCCEEDED"
        )
        assert evaluation.metadata["goldenshare/checked_row_count"].value == 387
        assert (
            target.storage_id == mat.storage_id
            and target.run_id == mat.event_log_entry.run_id
            and target.timestamp == mat.timestamp
        )
        native.append(
            {
                "asset": mat.asset_key.to_user_string(),
                "partition": record.partition,
                "status": record.status.value,
                "target_storage_id": target.storage_id,
                "materialization_storage_id": mat.storage_id,
            }
        )
    (env.staging / "387-concepts-job-evidence.json").write_text(
        json.dumps(
            {
                "scope": "isolated_job_with_archived_real_fixture_and_virtual_clock",
                "jobs_elapsed_ms": jobs_elapsed_ms,
                "source_rows_per_round": 387,
                "raw_rows": raw_count,
                "silver_rows": silver_count,
                "rejects": 0,
                "requests": env.source.calls,
                "native": native,
                "files": [
                    {
                        "path": str(p),
                        "bytes": p.stat().st_size,
                        "sha256": candidate_file_hash(p),
                    }
                    for p in (raw, silver)
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@pytest.mark.parametrize("corruption", ["dataset", "count", "scope", "verification"])
def test_corrupt_source_proof_never_publishes(env, monkeypatch, corruption):
    original = update.build_daily_moneyflow_raw_candidate

    def altered(**kwargs):
        raw = original(**kwargs)
        receipt = raw.parent / "receipt.json"
        value = json.loads(receipt.read_text())
        if corruption == "dataset":
            value["dataset"] = "moneyflow_ind_ths"
        elif corruption == "count":
            value["row_count"] = 90
        elif corruption == "scope":
            value["scope_row_counts"] = {"all": 90}
        else:
            (raw.parent / "verification.parquet").write_bytes(b"changed source proof")
        receipt.write_text(json.dumps(value))
        return raw

    monkeypatch.setattr(update, "build_daily_moneyflow_raw_candidate", altered)
    result = run(env, "raw_tushare_moneyflow_cnt_ths_update_job", raise_on_error=False)
    assert (
        not result.success
        and not raw_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY).exists()
    )
    assert result.get_asset_materialization_events() == []


@pytest.mark.parametrize(
    "dataset",
    [
        "moneyflow",
        "moneyflow_dc",
        "moneyflow_ths",
        "moneyflow_ind_dc",
        "moneyflow_mkt_dc",
        "../moneyflow_cnt_ths",
    ],
)
@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_unapproved_daily_dataset_rejected_before_source_and_files(env, dataset, layer):
    kwargs = {
        "dataset": dataset,
        "lake_root": env.lake,
        "staging_root": env.staging,
        "operation_id": "invalid-dataset",
        "trade_date": DAY,
    }
    if layer == "raw":
        kwargs["tushare"] = env.source
    else:
        kwargs["expected_raw_hash"] = "0" * 64
    with pytest.raises(MoneyflowContractError, match="daily_update_dataset"):
        getattr(update, "update_daily_moneyflow_" + layer)(**kwargs)
    assert not env.source.calls and not (env.staging / "moneyflow").exists()


def test_same_operation_never_reuses_industry_receipt_or_file(env):
    industry_dir = env.staging / "moneyflow/same-operation/moneyflow_ind_ths" / DAY
    industry_dir.mkdir(parents=True)
    sentinel = industry_dir / "receipt.json"
    sentinel.write_bytes(b"preserve industry proof")
    result = update.update_daily_moneyflow_raw(
        dataset="moneyflow_cnt_ths",
        tushare=env.source,
        lake_root=env.lake,
        staging_root=env.staging,
        operation_id="same-operation",
        trade_date=DAY,
    )
    assert result["row_count"] == 1 and len(env.source.calls) == 2
    assert sentinel.read_bytes() == b"preserve industry proof"
    assert not raw_moneyflow_path(env.lake, "moneyflow_ind_ths", DAY).exists()
