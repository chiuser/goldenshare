"""Exercise the original asset receipts and the new audit jobs in a temporary lake."""

import hashlib
import resource
from datetime import date, datetime
from functools import partial
from time import perf_counter

import dagster as dg
import duckdb
import pytest

from orchestrator.defs import resources
from orchestrator.defs.assets import (
    index_mins,
    index_mins_raw,
    index_mins_silver,
    index_mins_silver_defs,
)
from orchestrator.defs.checks import index_mins_checks
from orchestrator.defs.daily_data_audit import index_minute_audit, jobs
from orchestrator.defs.daily_data_audit.evidence import (
    INDEX_MINUTE_META,
    SHANGHAI,
    get_completeness,
    read_summary,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io import minute_partition_writer
from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.prod_db.index_mins import IndexMinsActivePool
from orchestrator.defs.sensors import (
    daily_data_audit_index_minute_sensor as automatic_audit,
)
from tests.test_index_mins_replace_existing import (
    CODE,
    FakeProd,
    fake_source,
    write_source,
)

DAY = "2026-11-19"
RAW = "raw_index_mins_1m"
SILVER = "silver_index_mins_1m"


def _clocks(frequency):
    return tuple(
        f"{minute // 60:02d}:{minute % 60:02d}:00"
        for minute in (
            *range(570, 691, frequency),
            *range(780 + frequency, 901, frequency),
        )
    )


@pytest.fixture
def isolated(tmp_path, monkeypatch, request):
    root = tmp_path / "lake"
    for layer in ("raw", "silver", "gold"):
        (root / layer).mkdir(parents=True)
    staging = tmp_path / "staging"
    staging.mkdir()
    connect = partial(
        connect_configured_duckdb, DuckDBConnectionSettings(temp_directory=tmp_path)
    )
    for module in (resources, index_mins, index_mins_silver, minute_partition_writer):
        monkeypatch.setattr(module, "connect_configured_duckdb", connect)
    for module in (index_minute_audit, minute_partition_writer):
        monkeypatch.setattr(module, "DEFAULT_LAKE_ROOT", str(root))
        monkeypatch.setattr(module, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(jobs, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(
        jobs, "read_calendar", lambda *_: {date.fromisoformat(DAY): True}
    )
    code_count = getattr(request, "param", 1)
    codes = (
        (CODE,)
        if code_count == 1
        else tuple(f"{n:06}.SH" for n in range(1, code_count + 1))
    )
    pool_hash = hashlib.sha256("\n".join(codes).encode()).hexdigest()
    monkeypatch.setattr(
        index_mins_raw,
        "load_prod_index_mins_active_pool",
        lambda **_: IndexMinsActivePool(codes, pool_hash),
    )
    incoming = {}
    fake_source(monkeypatch, incoming)
    assets = [
        dg.AssetSpec("silver_index_basic"),
        *index_mins_raw.RAW_INDEX_MINS_ASSETS,
        *index_mins_silver_defs.SILVER_INDEX_MINS_ASSETS,
        *(getattr(index_mins_checks, name) for name in index_mins_checks.__all__),
    ]
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    with dg.DagsterInstance.local_temp(
        str(instance_dir), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        instance.add_dynamic_partitions(cn_a_index_mins_trade_days.name, [DAY])

        def publish(asset, clocks=None, *, replace=False):
            if asset.startswith("raw_"):
                frequency = int(asset.rsplit("_", 1)[1][:-1])
                freq = f"{frequency}min"
                incoming[freq] = tmp_path / f"provided-{freq}.parquet"
                write_source(
                    incoming[freq], freq, clocks or _clocks(frequency), day=DAY
                )
                if code_count > 1:
                    expanded = tmp_path / f"provided-expanded-{freq}.parquet"
                    with connect() as connection:
                        connection.execute(
                            """
                            CREATE TEMP TABLE expanded_sample AS
                            SELECT code AS ts_code, bars.* EXCLUDE (ts_code)
                            FROM read_parquet(?) bars CROSS JOIN unnest(?::VARCHAR[]) c(code)
                        """,
                            [str(incoming[freq]), list(codes)],
                        )
                        connection.execute(
                            "COPY expanded_sample TO ? (FORMAT PARQUET)",
                            [str(expanded)],
                        )
                    incoming[freq] = expanded
            run = dg.materialize(
                assets,
                selection=dg.AssetSelection.assets(dg.AssetKey(asset)),
                resources={
                    "lake_root": resources.LakeRootResource(root_path=str(root)),
                    "duckdb": resources.DuckDBResource(),
                    "prod_postgres": FakeProd(),
                },
                partition_key=DAY,
                instance=instance,
                run_config={
                    "ops": {asset: {"config": {"write_mode": "replace_existing"}}}
                }
                if replace
                else None,
            )
            assert run.success and run.get_asset_check_evaluations()[0].passed
            return run

        yield instance, root, publish


def _run_audit(
    instance, root, asset, *, business_date=DAY, requested_version=None, success=True
):
    frequency = int(asset.rsplit("_", 1)[1][:-1])
    folder = "raw/tushare" if asset.startswith("raw_") else "silver/quote"
    path = (
        root
        / folder
        / "index_mins"
        / f"freq={frequency}min"
        / f"trade_date={business_date}"
        / "part-000.parquet"
    )
    result = index_minute_audit.daily_data_audit_index_minute_job.execute_in_process(
        instance=instance,
        raise_on_error=success,
        run_config={
            "ops": {
                "audit_index_minute": {
                    "config": {
                        "asset_key": asset,
                        "business_date": business_date,
                        "frequency": frequency,
                        "target_version": requested_version
                        or hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                }
            }
        },
    )
    if not success:
        assert not result.success
        return None
    assert result.success
    record = instance.get_records_for_run(
        result.run_id, of_type=dg.DagsterEventType.STEP_OUTPUT
    ).records[0]
    return record.event_log_entry.dagster_event.step_output_data.metadata[
        INDEX_MINUTE_META
    ].value


def _summary(instance, *changed):
    run = jobs.daily_data_audit_summary_job.execute_in_process(
        instance=instance,
        run_config={
            "ops": {
                "generate_data_audit_summary": {
                    "config": {
                        "business_date": DAY,
                        "changed_asset_keys": list(changed),
                    }
                }
            }
        },
    )
    assert run.success
    summary = read_summary(instance, date.fromisoformat(DAY))
    return {row["scope"]["asset_key"]: row for row in summary["rows"]}


def test_native_one_minute_raw_silver_and_report(isolated, monkeypatch):
    instance, root, publish = isolated
    publish(RAW)
    publish(SILVER)
    before = _summary(instance)
    assert before[SILVER]["update"]["status"] == "updated"
    assert before[SILVER]["completeness"]["status"] == "pending"
    raw = _run_audit(instance, root, RAW)
    silver = _run_audit(instance, root, SILVER)
    for result, files, rows in ((raw, 1, 241), (silver, 2, 482)):
        assert result["completeness"]["status"] == "complete"
        assert result["completeness"]["expected_count"] == 241
        assert result["completeness"]["actual_count"] == 241
        assert result["read_volume"]["key_files"] == files
        assert result["read_volume"]["key_rows"] == rows
    assert (
        silver["version"]["inputs"][0]["target_version"]
        == raw["version"]["target_version"]
    )

    def no_scan(*_args):
        pytest.fail("report attempted to scan minute data")

    monkeypatch.setattr(index_minute_audit, "_stage_keys", no_scan)
    monkeypatch.setattr(index_minute_audit.hashlib, "file_digest", no_scan)
    after = _summary(instance, RAW, SILVER)
    for asset in (RAW, SILVER):
        assert after[asset]["completeness"]["status"] == "complete"
        assert (
            after[asset]["completeness"]["evidence"][-1]["type"] == "independent_audit"
        )
        assert after[asset]["update"] == before[asset]["update"]
    assert all(after[key] == before[key] for key in before if key not in (RAW, SILVER))
    assert (
        get_completeness(instance, after[SILVER]["scope"], after[SILVER]["version"])
        == after[SILVER]["completeness"]
    )
    wrong_input = {**after[SILVER]["version"], "inputs": []}
    assert get_completeness(instance, after[SILVER]["scope"], wrong_input) is None
    [receipt] = (root.parent / "staging" / "minute_partitions" / "raw_index_mins").glob(
        "target=*/run_id=*/receipt.json"
    )
    receipt.unlink()
    replay = _run_audit(instance, root, RAW)
    assert replay["completeness"] == raw["completeness"]
    assert replay["read_volume"] == {"key_files": 0, "key_rows": 0, "sha256_bytes": 0}


def test_wrong_clock_same_count_and_upstream_gap_reads_no_silver(isolated, monkeypatch):
    instance, root, publish = isolated
    good = _clocks(1)
    publish(RAW, tuple("12:30:00" if clock == "14:00:00" else clock for clock in good))
    publish(SILVER)
    raw = _run_audit(instance, root, RAW)
    status = raw["completeness"]
    assert status["status"] == "gap"
    assert status["expected_count"] == status["actual_count"] == 241
    assert status["missing_count"] == status["extra_count"] == 1
    assert {sample["trade_time"] for sample in status["samples"]} == {
        "2026-11-19 14:00:00",
        "2026-11-19 12:30:00",
    }

    def no_scan(*_args):
        pytest.fail("Silver scanned despite an upstream gap")

    monkeypatch.setattr(index_minute_audit, "_stage_keys", no_scan)
    silver = _run_audit(instance, root, SILVER)
    assert silver["completeness"]["reason"]["code"] == "upstream_gap"
    assert silver["read_volume"] == {"key_files": 0, "key_rows": 0, "sha256_bytes": 0}
    report = _summary(instance)
    assert report[RAW]["completeness"]["status"] == "gap"
    assert report[SILVER]["completeness"]["status"] == "pending"
    assert report[SILVER]["update"]["status"] == "updated"


def test_original_producers_cover_all_twelve_audit_assets(isolated):
    instance, root, publish = isolated
    day = date.fromisoformat(DAY)
    expected = {1: 241, 5: 49, 15: 17, 30: 9, 60: 5, 90: 3, 120: 2}
    ready_batches = (
        {f"raw_index_mins_{freq}m" for freq in (1, 5, 15, 30, 60)},
        {f"silver_index_mins_{freq}m" for freq in (1, 5, 15, 30, 60)},
        {"silver_index_mins_90m", "silver_index_mins_120m"},
    )
    for assets in ready_batches:
        for asset in sorted(assets):
            publish(asset)
    for assets in ready_batches:
        requests = index_minute_audit.index_minute_audit_requests(instance, day, datetime.now(SHANGHAI), root)
        configs = [request.run_config["ops"]["audit_index_minute"]["config"] for request in requests]
        assert {config["asset_key"] for config in configs} == assets
        for config in configs:
            asset, frequency = config["asset_key"], config["frequency"]
            result = _run_audit(instance, root, asset, requested_version=config["target_version"])
            assert result["completeness"]["status"] == "complete", (asset, result["completeness"])
            assert result["completeness"]["expected_count"] == expected[frequency]
            assert result["read_volume"]["key_files"] == (1 if asset.startswith("raw_") else 2)
            if frequency in (90, 120):
                assert result["version"]["inputs"][0]["asset_key"] == (
                    "silver_index_mins_30m" if frequency == 90 else "silver_index_mins_60m"
                )
    assert index_minute_audit.index_minute_audit_requests(instance, day, datetime.now(SHANGHAI), root) == []
    report = _summary(instance)
    assert len(index_minute_audit.INDEX_MINUTE_ASSETS) == 12
    assert all(
        report[asset]["completeness"]["status"] == "complete"
        for asset in index_minute_audit.INDEX_MINUTE_ASSETS
    )
    assert report["gold_index_mins_1m"]["completeness"]["status"] != "complete"


def test_published_result_cannot_survive_a_new_target_or_input_version(isolated):
    instance, root, publish = isolated
    publish(RAW)
    publish(SILVER)
    raw = _run_audit(instance, root, RAW)
    _run_audit(instance, root, SILVER)
    assert _summary(instance)[SILVER]["completeness"]["status"] == "complete"
    times = _clocks(1)
    publish(RAW, times[:-1], replace=True)
    _run_audit(
        instance,
        root,
        RAW,
        requested_version=raw["version"]["target_version"],
        success=False,
    )
    report = _summary(instance, RAW)
    for asset in (RAW, SILVER):
        assert report[asset]["update"]["status"] == "updated"
        assert report[asset]["completeness"]["status"] == "pending"
        assert not any(
            item["type"] == "independent_audit"
            for item in report[asset]["completeness"]["evidence"]
        )


def test_late_audit_result_refreshes_its_historical_report_once(isolated, monkeypatch):
    instance, root, publish = isolated
    publish(RAW)
    before = _summary(instance)
    _run_audit(instance, root, RAW)
    run = instance.get_runs(
        filters=dg.RunsFilter(job_name="daily_data_audit_index_minute_job"), limit=1
    )[0]

    def no_stat(*_):
        pytest.fail("the report sensor must only read Dagster records")

    repo = dg.Definitions(
        jobs=[jobs.daily_data_audit_summary_job],
        sensors=[jobs.daily_data_audit_summary_refresh_sensor],
    ).get_repository_def()

    def tick(cursor=None):
        with monkeypatch.context() as patch:
            patch.setattr(index_minute_audit, "stat_version", no_stat)
            return jobs.daily_data_audit_summary_refresh_sensor.evaluate_tick(
                dg.build_sensor_context(
                    instance=instance, repository_def=repo, cursor=cursor
                )
            )

    evaluation = tick()
    [request] = evaluation.run_requests
    assert (
        request.run_key
        == f"daily_data_audit_summary_job:index-minute:{DAY}:{run.run_id}"
    )
    assert request.tags["audit/business_date"] == DAY
    assert request.run_config["ops"]["generate_data_audit_summary"]["config"][
        "changed_asset_keys"
    ] == [RAW]
    assert jobs.daily_data_audit_summary_job.execute_in_process(
        instance=instance,
        run_config=request.run_config,
    ).success
    after = {
        row["scope"]["asset_key"]: row
        for row in read_summary(instance, date.fromisoformat(DAY))["rows"]
    }
    assert after[RAW]["completeness"]["status"] == "complete"
    assert after[RAW]["update"] == before[RAW]["update"]
    assert all(
        after[asset] == before[asset] for asset in before if asset not in (RAW, SILVER)
    )
    assert not tick(evaluation.cursor).run_requests
    assert date.fromisoformat(DAY) < datetime.now(SHANGHAI).date()


def test_automatic_audit_waits_for_upstream_and_refreshes_published_gold(isolated, monkeypatch):
    instance, root, publish = isolated
    day = date.fromisoformat(DAY)
    gold_key = "gold_index_mins_1m"
    publish(RAW)
    publish(SILVER)

    @dg.asset(
        name=gold_key, deps=[SILVER], partitions_def=cn_a_index_mins_trade_days,
    )
    def gold():
        return dg.MaterializeResult(metadata={"dagster/row_count": 241})

    @dg.asset_check(asset=gold, name="gold_index_mins_1m_core_check")
    def core_check():
        return dg.AssetCheckResult(passed=True)

    assert dg.materialize(
        [dg.AssetSpec(SILVER, partitions_def=cn_a_index_mins_trade_days), gold, core_check],
        selection=[gold_key], partition_key=DAY, instance=instance,
    ).success
    initial = _summary(instance)
    assert initial[gold_key]["completeness"]["status"] == "pending"
    monkeypatch.setattr(automatic_audit, "DEFAULT_LAKE_ROOT", str(root))
    monkeypatch.setattr(automatic_audit, "read_calendar", lambda *_: {day: True})
    sensor = automatic_audit.daily_data_audit_index_minute_job_sensor
    assert sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert sensor.minimum_interval_seconds == 600
    repository = dg.Definitions(
        jobs=[index_minute_audit.daily_data_audit_index_minute_job, jobs.daily_data_audit_summary_job],
        sensors=[sensor, jobs.daily_data_audit_summary_refresh_sensor],
    ).get_repository_def()

    def tick():
        return sensor.evaluate_tick(dg.build_sensor_context(instance=instance, repository_def=repository))

    def execute(request):
        assert index_minute_audit.daily_data_audit_index_minute_job.execute_in_process(
            instance=instance, run_config=request.run_config, tags={"dagster/run_key": request.run_key},
        ).success

    [raw_request] = tick().run_requests
    assert raw_request.run_config["ops"]["audit_index_minute"]["config"]["asset_key"] == RAW
    execute(raw_request)
    [silver_request] = tick().run_requests
    assert silver_request.run_config["ops"]["audit_index_minute"]["config"]["asset_key"] == SILVER
    execute(silver_request)
    assert not tick().run_requests

    [refresh] = jobs.daily_data_audit_summary_refresh_sensor.evaluate_tick(
        dg.build_sensor_context(instance=instance, repository_def=repository)
    ).run_requests
    assert refresh.run_config["ops"]["generate_data_audit_summary"]["config"]["changed_asset_keys"] == [
        gold_key, RAW, SILVER,
    ]
    assert jobs.daily_data_audit_summary_job.execute_in_process(
        instance=instance, run_config=refresh.run_config,
    ).success
    rows = {row["scope"]["asset_key"]: row for row in read_summary(instance, day)["rows"]}
    assert all(rows[asset]["completeness"]["status"] == "complete" for asset in (RAW, SILVER, gold_key))
    assert rows[gold_key]["version"]["inputs"][0]["asset_key"] == SILVER

    publish(RAW, replace=True)
    after = _summary(instance)
    assert after[gold_key]["completeness"]["status"] == "pending"


def test_automatic_audit_skips_an_already_submitted_version(isolated):
    instance, root, publish = isolated
    day = date.fromisoformat(DAY)
    publish(RAW)
    [request] = index_minute_audit.index_minute_audit_requests(
        instance, day, datetime.now(SHANGHAI), root,
    )
    instance.create_run_for_job(
        index_minute_audit.daily_data_audit_index_minute_job,
        run_config=request.run_config, tags={"dagster/run_key": request.run_key},
    )
    assert index_minute_audit.index_minute_audit_requests(
        instance, day, datetime.now(SHANGHAI), root,
    ) == []


def test_missing_promotion_receipt_cannot_use_unbound_counts(isolated, monkeypatch):
    instance, root, publish = isolated
    publish(RAW)
    [receipt] = (root.parent / "staging" / "minute_partitions" / "raw_index_mins").glob(
        "target=*/run_id=*/receipt.json"
    )
    receipt.unlink()

    def no_scan(*_):
        pytest.fail("data was scanned without a same-version receipt")

    monkeypatch.setattr(index_minute_audit, "_stage_keys", no_scan)
    result = _run_audit(instance, root, RAW)
    assert result["completeness"]["status"] == "pending"
    assert result["version"]["target_version"] is None
    assert _summary(instance)[RAW]["update"]["status"] == "updated"


def test_duplicate_keys_are_counted_separately():
    with duckdb.connect(":memory:") as connection:
        connection.execute("""
            CREATE TEMP TABLE target_keys AS
            SELECT '000001.SH' AS ts_code, '1min' AS freq, TIMESTAMP '2026-11-19 09:30' AS trade_time
            FROM range(3)
        """)
        counts = index_minute_audit._compare_keys(
            connection,
            "SELECT DISTINCT * FROM target_keys",
            [],
        )
    assert counts[:5] == (1, 3, 0, 0, 2)
    assert counts[5] == [
        {
            "issue": "duplicate",
            "ts_code": "000001.SH",
            "freq": "1min",
            "trade_time": "2026-11-19 09:30:00",
        }
    ]


def test_derived_window_requires_auction_input():
    clocks = (
        "10:00",
        "10:30",
        "11:00",
        "11:30",
        "13:30",
        "14:00",
        "14:30",
        "15:00",
    )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TEMP TABLE source_keys AS
            SELECT '000001.SH' AS ts_code, '30min' AS freq, trade_time
            FROM unnest(?::TIMESTAMP[]) t(trade_time)
        """,
            [[datetime.fromisoformat(f"{DAY}T{clock}") for clock in clocks]],
        )
        assert (
            index_minute_audit._expected_silver(
                connection,
                date.fromisoformat(DAY),
                90,
                30,
                False,
            )
            is None
        )


def test_audit_cannot_borrow_evidence_from_another_day(isolated, monkeypatch):
    instance, root, publish = isolated
    publish(RAW)
    approved = _run_audit(instance, root, RAW)

    def no_scan(*_):
        pytest.fail("the other date has no current publication")

    monkeypatch.setattr(index_minute_audit, "_stage_keys", no_scan)
    other = _run_audit(
        instance,
        root,
        RAW,
        business_date="2026-11-20",
        requested_version=approved["version"]["target_version"],
    )
    assert other["scope"]["business_date"] == "2026-11-20"
    assert other["target_publication_run_id"] is None
    assert other["completeness"]["status"] == "pending"


def test_historical_fallback_requires_the_approved_same_version_source(isolated):
    instance, root, publish = isolated
    publish("raw_index_mins_5m")
    _run_audit(instance, root, "raw_index_mins_5m")
    scope = dg.StaticPartitionsDefinition([DAY])
    target = (
        root
        / "silver/quote/index_mins/freq=15min"
        / f"trade_date={DAY}"
        / "part-000.parquet"
    )
    source = (
        root
        / "raw/tushare/index_mins/freq=5min"
        / f"trade_date={DAY}"
        / "part-000.parquet"
    )
    # The fallback materialization fields are from IndexMinsSilverWriteResult.
    # The test explicitly provides a versioned promotion receipt that legacy
    # runless bootstrap events alone do not contain.
    fields = {
        "source_mode": "derived_fallback",
        "source_freq": "5min",
        "source_empty_reason": "source_probe_target_frequency_empty",
        "source_revision": "approved-source-revision",
    }

    @dg.asset(name="silver_index_mins_15m", partitions_def=scope)
    def fallback(context):
        publication = minute_partition_writer.MinutePartitionPublication(
            dataset="silver_index_mins",
            target=target,
            day=DAY,
            freq=15,
            publication_id=context.run_id,
            source_paths=(source,),
        )

        def build(candidate):
            write_source(candidate, "15min", _clocks(15), day=DAY)
            return {**fields, "written_row_count": 17}

        publication.run(build)
        return dg.MaterializeResult(
            metadata={f"goldenshare/{key}": value for key, value in fields.items()}
        )

    result = dg.materialize([fallback], instance=instance, partition_key=DAY)
    assert result.success
    [receipt] = (
        root.parent / "staging" / "minute_partitions" / "silver_index_mins"
    ).glob("target=*/run_id=*/receipt.json")
    invalid = receipt.read_text().replace(
        "approved-source-revision", "wrong-source-revision"
    )
    original = receipt.read_text()
    receipt.write_text(invalid)
    pending = _run_audit(instance, root, "silver_index_mins_15m")
    assert pending["completeness"]["reason"]["code"] == "reference_missing"
    assert pending["read_volume"]["key_files"] == 0
    receipt.write_text(original)
    approved = _run_audit(instance, root, "silver_index_mins_15m")
    assert approved["completeness"]["status"] == "complete"
    assert approved["completeness"]["expected_count"] == 17
    assert approved["completeness"]["exceptions"] == [
        {
            "type": "source_empty_fallback",
            "source": "raw_index_mins_5m",
        }
    ]


@pytest.mark.parametrize("isolated", [530], indirect=True)
def test_sample_scale_one_minute_chain(isolated):
    instance, root, publish = isolated
    publish(RAW)
    publish(SILVER)
    for asset, rows, files in ((RAW, 127730, 1), (SILVER, 255460, 2)):
        started = perf_counter()
        result = _run_audit(instance, root, asset)
        elapsed = perf_counter() - started
        assert result["completeness"]["status"] == "complete"
        assert result["completeness"]["expected_count"] == 127730
        assert result["read_volume"]["key_files"] == files
        assert result["read_volume"]["key_rows"] == rows
        print(f"{asset}: {elapsed:.3f}s, {result['read_volume']}")
    report = _summary(instance)
    assert (
        report[RAW]["completeness"]["actual_count"]
        == report[SILVER]["completeness"]["actual_count"]
        == 127730
    )
    print(
        f"sample process peak RSS (macOS bytes): {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}"
    )
