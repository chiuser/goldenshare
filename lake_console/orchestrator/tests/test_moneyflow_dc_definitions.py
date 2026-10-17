"""DC stock moneyflow jobs/checks use fake source/clock and isolated files/instance."""

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import dagster as dg
import pytest

import orchestrator.defs.assets.moneyflow_dc as assets
import orchestrator.defs.io.moneyflow_daily_update as update
import orchestrator.defs.io.moneyflow_update_publication as publication
from orchestrator.defs.catalog import get_lake_asset_catalog_entry
from orchestrator.defs.checks.moneyflow_dc import (
    raw_tushare_moneyflow_dc_file_contract_check,
    silver_moneyflow_dc_standardization_check,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
)
from orchestrator.defs.jobs.moneyflow_dc import (
    raw_tushare_moneyflow_dc_update_job,
    silver_moneyflow_dc_update_job,
)
from orchestrator.defs.partitions import cn_a_moneyflow_dc_trade_days
from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.moneyflow import (
    MoneyflowContractError,
)

pytestmark = pytest.mark.usefixtures("isolated_moneyflow_transport")

DAY = "2026-10-08"
MONEYFLOW_DC_FIELDS = (
    "trade_date",
    "ts_code",
    "name",
    "pct_change",
    "close",
    "net_amount",
    "net_amount_rate",
    "buy_elg_amount",
    "buy_elg_amount_rate",
    "buy_lg_amount",
    "buy_lg_amount_rate",
    "buy_md_amount",
    "buy_md_amount_rate",
    "buy_sm_amount",
    "buy_sm_amount_rate",
)
RAW = assets.raw_tushare_moneyflow_dc
SILVER = assets.silver_moneyflow_dc
CHECKS = [
    raw_tushare_moneyflow_dc_file_contract_check,
    silver_moneyflow_dc_standardization_check,
]


def row(code="000001.SZ", name=None, amount="-5.1234", day=DAY):
    return dict(
        zip(
            MONEYFLOW_DC_FIELDS,
            (
                day.replace("-", ""),
                code,
                name,
                "-2.38",
                "30.6700",
                amount,
                None,
                "3",
                "2.5",
                "2",
                "1.94",
                None,
                None,
                "-4",
                "-2.38",
            ),
        )
    )


def sample(amount="-5.1234", day=DAY):
    return [
        row(code, name, amount, day)
        for code, name in (
            ("000001.SZ", None),
            ("600000.SH", "同名股票"),
            ("920305.BJ", "同名股票"),
        )
    ]


def pages(rows):
    result = [rows[i : i + 2000] for i in range(0, len(rows), 2000)]
    if len(rows) % 2000 == 0:
        result.append([])
    return result


def set_rows(env, first, second=None):
    env.source.responses = iter(
        pages(first) + pages(first[::-1] if second is None else second)
    )


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
        return SimpleNamespace(columns=MONEYFLOW_DC_FIELDS, rows=response)


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
    source = Source(pages(sample()) * 2)
    defs = dg.Definitions(
        assets=[RAW, SILVER],
        asset_checks=CHECKS,
        jobs=[
            raw_tushare_moneyflow_dc_update_job,
            silver_moneyflow_dc_update_job,
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
            cn_a_moneyflow_dc_trade_days.name, [DAY, "2026-09-29"]
        )
        from .moneyflow_baseline_support import seed_moneyflow_baseline

        seed_moneyflow_baseline(
            instance=instance,
            lake=lake,
            staging=staging,
            dataset="moneyflow_dc",
            rows=sample()[:1],
        )
        yield SimpleNamespace(
            defs=defs, instance=instance, source=source, lake=lake, staging=staging
        )


def run(env, name, *, day=DAY, raise_on_error=True):
    return env.defs.resolve_job_def(name).execute_in_process(
        instance=env.instance, partition_key=day, raise_on_error=raise_on_error
    )


def _check_existing_file(env, check):
    # Current SDK does not infer a partition definition for a checks-only job.
    # This isolated asset stub leaves the injected damaged file untouched;
    # the original check still executes in a genuinely partitioned asset job.
    asset = RAW if check is CHECKS[0] else SILVER
    path = (raw_moneyflow_path if asset is RAW else silver_moneyflow_path)(
        env.lake, "moneyflow_dc", DAY
    )

    @dg.asset(
        name=asset.key.to_user_string(),
        partitions_def=cn_a_moneyflow_dc_trade_days,
        deps=[] if asset is RAW else [RAW],
    )
    def existing_file():
        return dg.MaterializeResult(
            metadata={"goldenshare/file_sha256": candidate_file_hash(path)}
        )

    job = dg.define_asset_job(
        name="board_existing_file_check",
        selection=dg.AssetSelection.assets(existing_file)
        | dg.AssetSelection.checks(check),
        partitions_def=cn_a_moneyflow_dc_trade_days,
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


def test_independent_definitions_catalog_schema_and_selections(env):
    dg.Definitions.validate_loadable(env.defs)
    assert RAW.partitions_def is SILVER.partitions_def is cn_a_moneyflow_dc_trade_days
    assert SILVER.asset_deps[SILVER.key] == {RAW.key}
    for asset, check in zip((RAW, SILVER), CHECKS):
        entry = get_lake_asset_catalog_entry(asset.key.to_user_string())
        assert entry.dataset_id == "moneyflow_dc" and entry.group_name == "moneyflow"
        assert len(entry.column_schema) == 15
        assert {s.name for s in check.check_specs} == set(entry.blocking_check_names)
        assert check.partitions_def is cn_a_moneyflow_dc_trade_days
        assert all(s.blocking for s in check.check_specs)
        job = env.defs.resolve_job_def(asset.key.to_user_string() + "_update_job")
        assert job.asset_layer.executable_asset_keys == {asset.key}
    assert (
        get_lake_asset_catalog_entry(RAW.key.to_user_string())
        .bootstrap_sources[0]
        .value
        == "prod_db_readonly"
    )
    assert not any(
        "moneyflow_cnt_ths" in str(k)
        for k in env.defs.resolve_asset_graph().get_all_asset_keys()
    )


def test_partitioned_jobs_preserve_stock_keys_nullable_name_and_wan(env):
    first = run(env, "raw_tushare_moneyflow_dc_update_job")
    second = run(env, "silver_moneyflow_dc_update_job")
    assert first.success and second.success and len(env.source.calls) == 2
    for api, params, fields in env.source.calls:
        assert api == "moneyflow_dc" and fields == MONEYFLOW_DC_FIELDS
        assert params == {
            "trade_date": DAY.replace("-", ""),
            "limit": 2000,
            "offset": 0,
        }
    with moneyflow_candidate_connection(env.staging) as c:
        values = c.execute(
            "SELECT trade_date,ts_code,name,net_amount,buy_md_amount FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(silver_moneyflow_path(env.lake, "moneyflow_dc", DAY))],
        ).fetchall()
    assert len(values) == 3 and values[0][2] is None
    assert {v[1].split(".")[1] for v in values} == {"SH", "SZ", "BJ"}
    assert all(
        v[0] == date.fromisoformat(DAY) and v[3] == Decimal("-5.1234") and v[4] is None
        for v in values
    )
    # Preserve the source net amount; 3+2 does not equal -5.1234.
    for result, check in zip((first, second), CHECKS):
        evaluations = result.get_asset_check_evaluations()
        assert (
            len(evaluations) == 1
            and evaluations[0].passed
            and evaluations[0].partition == DAY
        )
        history = env.instance.event_log_storage.get_asset_check_execution_history(
            next(iter(check.check_keys)), limit=1
        )
        assert history[0].status.value == "SUCCEEDED" and history[0].partition == DAY
        target = history[
            0
        ].event.dagster_event.event_specific_data.target_materialization_data
        mat = env.instance.fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=next(iter(check.check_keys)).asset_key, asset_partitions=[DAY]
            ),
            limit=1,
        ).records[0]
        assert (target.storage_id, target.run_id, target.timestamp) == (
            mat.storage_id,
            mat.event_log_entry.run_id,
            mat.timestamp,
        )


def test_archived_real_6024_rows_reconcile_all_fields_and_markets(env):
    fixture = json.loads(Path("tests/fixtures/moneyflow_dc_20260930.json").read_text())
    assert len(fixture) == 6024
    # Preserve archived field values; project date to the isolated continuation run.
    fixture = [dict(r, trade_date=DAY.replace("-", "")) for r in fixture]
    set_rows(env, fixture, list(reversed(fixture)))
    started = perf_counter()
    first = run(env, "raw_tushare_moneyflow_dc_update_job")
    second = run(env, "silver_moneyflow_dc_update_job")
    assert first.success and second.success and len(env.source.calls) == 8
    assert [p["offset"] for _, p, _ in env.source.calls] == [0, 2000, 4000, 6000] * 2
    assert all(
        api == "moneyflow_dc"
        and fields == MONEYFLOW_DC_FIELDS
        and p
        == {"trade_date": DAY.replace("-", ""), "limit": 2000, "offset": p["offset"]}
        for api, p, fields in env.source.calls
    )
    raw = raw_moneyflow_path(env.lake, "moneyflow_dc", DAY)
    silver = silver_moneyflow_path(env.lake, "moneyflow_dc", DAY)
    expected = [
        tuple(
            date.fromisoformat(DAY)
            if f == "trade_date"
            else Decimal(str(r[f]))
            if f in MONEYFLOW_DC_FIELDS[3:] and r[f] is not None
            else r[f]
            for f in MONEYFLOW_DC_FIELDS
        )
        for r in sorted(fixture, key=lambda r: r["ts_code"])
    ]
    with moneyflow_candidate_connection(env.staging) as c:
        assert (
            c.execute(
                "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)",
                [str(raw)],
            ).fetchone()[0]
            == 6024
        )
        actual = c.execute(
            "SELECT * FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(silver)],
        ).fetchall()
        assert actual == expected
        market_counts = dict(
            c.execute(
                "SELECT split_part(ts_code,'.',2),count(*) FROM read_parquet(?,hive_partitioning=false) GROUP BY 1",
                [str(silver)],
            ).fetchall()
        )
        assert market_counts == {"SH": 2522, "SZ": 3154, "BJ": 348}
    mats = []
    for result in (first, second):
        mat = result.get_asset_materialization_events()[
            0
        ].event_specific_data.materialization
        assert mat.metadata["dagster/row_count"].value == 6024
        evaluation = result.get_asset_check_evaluations()[0]
        assert evaluation.passed and evaluation.partition == DAY
        assert evaluation.metadata["goldenshare/checked_row_count"].value == 6024
        mats.append(
            {"run_id": result.run_id, "partition": mat.partition, "row_count": 6024}
        )
    (env.staging / "6024-stocks-job-evidence.json").write_text(
        json.dumps(
            {
                "scope": "isolated_archived_fixture_fake_source_and_clock",
                "source_rows_per_round": 6024,
                "raw_rows": 6024,
                "silver_rows": 6024,
                "rejected_rows": 0,
                "market_counts": market_counts,
                "all_15_fields_equal": True,
                "jobs": mats,
                "requests": env.source.calls,
                "file_proofs": [
                    {
                        "path": str(p),
                        "sha256": candidate_file_hash(p),
                        "bytes": p.stat().st_size,
                    }
                    for p in (raw, silver)
                ],
                "jobs_elapsed_seconds": perf_counter() - started,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def test_same_name_different_stock_codes_remain_distinct(env):
    set_rows(env, sample())
    assert run(env, "raw_tushare_moneyflow_dc_update_job").success
    assert run(env, "silver_moneyflow_dc_update_job").success
    with moneyflow_candidate_connection(env.staging) as c:
        assert (
            c.execute(
                "SELECT count(*) FROM read_parquet(?,hive_partitioning=false) WHERE name='同名股票'",
                [str(silver_moneyflow_path(env.lake, "moneyflow_dc", DAY))],
            ).fetchone()[0]
            == 2
        )


@pytest.mark.parametrize("round_number", (1, 2))
def test_empty_stock_date_in_either_round_never_publishes(env, round_number):
    set_rows(env, [] if round_number == 1 else sample(), [])
    result = run(env, "raw_tushare_moneyflow_dc_update_job", raise_on_error=False)
    assert not result.success and not result.get_asset_materialization_events()
    assert not raw_moneyflow_path(env.lake, "moneyflow_dc", DAY).exists()


@pytest.mark.parametrize(
    "reason", ("date", "duplicate", "unstable", "empty_code", "schema", "board_schema")
)
def test_invalid_or_unstable_source_cannot_publish_green_events(env, reason):
    rows = sample()
    if reason == "date":
        set_rows(env, sample(day="2026-09-29"))
    elif reason == "duplicate":
        set_rows(env, rows + [row(code="000001.SZ", name="不同名称")])
    elif reason == "unstable":
        set_rows(env, rows, sample(amount="99.0000"))
    elif reason == "empty_code":
        set_rows(env, [row(code=None)])
    elif reason == "board_schema":
        set_rows(env, [dict(row(), content_type="行业")])
    else:
        env.source.responses = iter(
            [[{k: v for k, v in row().items() if k != "buy_sm_amount_rate"}]]
        )
    result = run(env, "raw_tushare_moneyflow_dc_update_job", raise_on_error=False)
    assert not result.success and not result.get_asset_materialization_events()
    assert not raw_moneyflow_path(env.lake, "moneyflow_dc", DAY).exists()


def test_full_page_uses_stock_offsets_and_empty_termination(env):
    set_rows(env, [row(code=f"{i:06d}.SZ") for i in range(2000)])
    assert run(env, "raw_tushare_moneyflow_dc_update_job").success
    assert [p["offset"] for _, p, _ in env.source.calls] == [0, 2000] * 2
    assert all(
        set(p) == {"trade_date", "limit", "offset"} for _, p, _ in env.source.calls
    )


def test_silver_requires_green_same_day_raw(env):
    result = run(env, "silver_moneyflow_dc_update_job", raise_on_error=False)
    assert not result.success and not env.source.calls
    assert not silver_moneyflow_path(env.lake, "moneyflow_dc", DAY).exists()


@pytest.mark.parametrize("condition", ["other_day", "stale_check", "failed_check"])
def test_silver_rejects_other_day_stale_or_failed_raw_check(env, condition):
    assert run(env, "raw_tushare_moneyflow_dc_update_job").success
    day = "2026-09-29" if condition == "other_day" else DAY
    if condition == "stale_check":
        env.instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=RAW.key,
                partition=DAY,
                metadata={
                    "goldenshare/file_sha256": candidate_file_hash(
                        raw_moneyflow_path(env.lake, "moneyflow_dc", DAY)
                    )
                },
            )
        )
    elif condition == "failed_check":
        _change_file(
            env,
            raw_moneyflow_path(env.lake, "moneyflow_dc", DAY),
            "* REPLACE('20260929'::VARCHAR AS trade_date)",
        )
        assert not _check_existing_file(env, CHECKS[0]).success
    result = run(env, "silver_moneyflow_dc_update_job", day=day, raise_on_error=False)
    assert not result.success and len(env.source.calls) == 2
    assert not silver_moneyflow_path(env.lake, "moneyflow_dc", day).exists()


def test_raw_physical_hash_change_blocks_silver_before_source(env):
    assert run(env, "raw_tushare_moneyflow_dc_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_dc", DAY)
    _change_file(env, raw, "* REPLACE(99::DECIMAL(24,4) AS net_amount)")
    result = run(env, "silver_moneyflow_dc_update_job", raise_on_error=False)
    assert not result.success and len(env.source.calls) == 2


@pytest.mark.parametrize(
    "projection,reason",
    [
        ("* REPLACE('20260929'::VARCHAR AS trade_date)", "file_count_date_or_key"),
        ("* REPLACE('000001.SZ'::VARCHAR AS ts_code)", "file_count_date_or_key"),
    ],
)
def test_wrong_date_or_duplicate_stock_records_failed_blocking_check(
    env, projection, reason
):
    assert run(env, "raw_tushare_moneyflow_dc_update_job").success
    _change_file(env, raw_moneyflow_path(env.lake, "moneyflow_dc", DAY), projection)
    result = _check_existing_file(env, CHECKS[0])
    assert not result.success
    evaluation = result.get_asset_check_evaluations()[0]
    assert not evaluation.passed and evaluation.partition == DAY
    assert evaluation.metadata["goldenshare/reason_code"].value == reason
    assert not run(env, "silver_moneyflow_dc_update_job", raise_on_error=False).success


def test_silver_field_change_records_failed_reconciliation(env):
    assert run(env, "raw_tushare_moneyflow_dc_update_job").success
    assert run(env, "silver_moneyflow_dc_update_job").success
    _change_file(
        env,
        silver_moneyflow_path(env.lake, "moneyflow_dc", DAY),
        "* REPLACE(999::DECIMAL(24,4) AS net_amount)",
    )
    result = _check_existing_file(env, CHECKS[1])
    assert not result.success
    assert (
        result.get_asset_check_evaluations()[0]
        .metadata["goldenshare/reason_code"]
        .value
        == "standardization_difference"
    )


def test_same_files_replay_is_idempotent_and_revision_updates_silver(env):
    assert run(env, "raw_tushare_moneyflow_dc_update_job").success
    assert run(env, "silver_moneyflow_dc_update_job").success
    raw = raw_moneyflow_path(env.lake, "moneyflow_dc", DAY)
    silver = silver_moneyflow_path(env.lake, "moneyflow_dc", DAY)
    before = raw.stat().st_mtime_ns
    set_rows(env, sample())
    assert run(env, "raw_tushare_moneyflow_dc_update_job").success
    assert raw.stat().st_mtime_ns == before
    old_silver = candidate_file_hash(silver)
    set_rows(env, sample(amount="17.1234"))
    assert run(env, "raw_tushare_moneyflow_dc_update_job").success
    assert candidate_file_hash(silver) == old_silver
    assert run(env, "silver_moneyflow_dc_update_job").success
    assert candidate_file_hash(silver) != old_silver and len(env.source.calls) == 6


@pytest.mark.parametrize("corruption", ("dataset", "scope_counts", "verification"))
def test_candidate_receipt_and_all_scope_proofs_required(env, corruption):
    original = update.build_daily_moneyflow_raw_candidate

    def corrupt(**kwargs):
        raw = original(**kwargs)
        path = raw.parent / "receipt.json"
        receipt = json.loads(path.read_text())
        if corruption == "dataset":
            receipt["dataset"] = "moneyflow_cnt_ths"
        elif corruption == "scope_counts":
            receipt["scope_row_counts"] = {"all": 90}
        else:
            (raw.parent / "verification.parquet").write_bytes(b"bad proof")
        path.write_text(json.dumps(receipt))
        return raw

    update.build_daily_moneyflow_raw_candidate = corrupt
    try:
        result = run(env, "raw_tushare_moneyflow_dc_update_job", raise_on_error=False)
    finally:
        update.build_daily_moneyflow_raw_candidate = original
    assert not result.success and not result.get_asset_materialization_events()
    assert not raw_moneyflow_path(env.lake, "moneyflow_dc", DAY).exists()


@pytest.mark.parametrize("layer", ("raw", "silver"))
def test_exit_after_replace_resumes_without_source_or_rebuild(env, monkeypatch, layer):
    if layer == "silver":
        assert run(env, "raw_tushare_moneyflow_dc_update_job").success
    original = publication._checkpoint

    def interrupted(path, state):
        if state["stage"] == "complete":
            raise RuntimeError("exit after replace")
        original(path, state)

    monkeypatch.setattr(publication, "_checkpoint", interrupted)
    kwargs = {
        "dataset": "moneyflow_dc",
        "lake_root": env.lake,
        "staging_root": env.staging,
        "operation_id": "resume",
        "trade_date": DAY,
    }
    if layer == "raw":
        kwargs["tushare"] = env.source
        kwargs["instance"] = env.instance
    else:
        kwargs["expected_raw_hash"] = candidate_file_hash(
            raw_moneyflow_path(env.lake, "moneyflow_dc", DAY)
        )
    with pytest.raises(RuntimeError, match="exit after replace"):
        getattr(update, "update_daily_moneyflow_" + layer)(**kwargs)
    target = (raw_moneyflow_path if layer == "raw" else silver_moneyflow_path)(
        env.lake, "moneyflow_dc", DAY
    )
    digest = candidate_file_hash(target)
    monkeypatch.setattr(publication, "_checkpoint", original)
    result = getattr(update, "update_daily_moneyflow_" + layer)(**kwargs)
    assert result["file_sha256"] == digest and len(env.source.calls) == 2


def test_cancel_after_intent_resumes_verified_raw_candidate(env, monkeypatch):
    original = publication._checkpoint
    cancelled = {"value": False}

    def checkpoint(path, state):
        original(path, state)
        if state["stage"] == "intent":
            cancelled["value"] = True

    def check_cancel():
        if cancelled["value"]:
            raise MoneyflowContractError("user_cancel")

    monkeypatch.setattr(publication, "_checkpoint", checkpoint)
    kwargs = {
        "dataset": "moneyflow_dc",
        "tushare": env.source,
        "lake_root": env.lake,
        "staging_root": env.staging,
        "operation_id": "cancel",
        "trade_date": DAY,
    }
    with pytest.raises(MoneyflowContractError, match="user_cancel"):
        update.update_daily_moneyflow_raw(
            instance=env.instance, **kwargs, check_cancel=check_cancel
        )
    assert not raw_moneyflow_path(env.lake, "moneyflow_dc", DAY).exists()
    assert (
        env.staging / "moneyflow/cancel/moneyflow_dc" / DAY / "raw.parquet"
    ).is_file()
    monkeypatch.setattr(publication, "_checkpoint", original)
    update.update_daily_moneyflow_raw(instance=env.instance, **kwargs)
    assert len(env.source.calls) == 2


def test_same_operation_never_reuses_other_dataset_receipt(env):
    other = env.staging / "moneyflow/shared/moneyflow_cnt_ths" / DAY
    other.mkdir(parents=True)
    sentinel = other / "receipt.json"
    sentinel.write_bytes(b"preserve concept")
    result = update.update_daily_moneyflow_raw(
        instance=env.instance,
        dataset="moneyflow_dc",
        tushare=env.source,
        lake_root=env.lake,
        staging_root=env.staging,
        operation_id="shared",
        trade_date=DAY,
    )
    assert result["row_count"] == 3 and sentinel.read_bytes() == b"preserve concept"
    assert not raw_moneyflow_path(env.lake, "moneyflow_cnt_ths", DAY).exists()


@pytest.mark.parametrize(
    "dataset",
    (
        "unknown_moneyflow",
        "moneyflow_mkt_dc",
        "../moneyflow_dc",
    ),
)
@pytest.mark.parametrize("layer", ("raw", "silver"))
def test_unapproved_sources_remain_rejected_before_io(env, dataset, layer):
    kwargs = {
        "dataset": dataset,
        "lake_root": env.lake,
        "staging_root": env.staging,
        "operation_id": "invalid",
        "trade_date": DAY,
    }
    if layer == "raw":
        kwargs["tushare"] = env.source
        kwargs["instance"] = env.instance
    else:
        kwargs["expected_raw_hash"] = "0" * 64
    with pytest.raises(MoneyflowContractError, match="daily_update_dataset"):
        getattr(update, "update_daily_moneyflow_" + layer)(**kwargs)
    assert not env.source.calls and not (env.staging / "moneyflow").exists()
