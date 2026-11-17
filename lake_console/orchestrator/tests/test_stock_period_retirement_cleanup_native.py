"""Real temporary producer jobs and native lineage; no formal resources.

The literal 21-column fixture follows the verified real producer contract. Real
identity-maintenance jobs record unchanged historical Raw (an absent I key is
removed); real Silver updates run while the synthetic issuers are L. Only then
stock_basic/lifecycle change to D. HTTP/upstream acceptance use market's explicit
substitutes. Independent expected rows preserve all 21 values including NULLs.
"""

import json
import time
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import dagster as dg
import pytest

from orchestrator.defs import paths, stock_period_source
from orchestrator.defs import stock_period_retirement_cleanup as cleanup
from orchestrator.defs.asset_guards.stock_period_delivery import (
    native_run_records,
    silver_completion_consumed,
)
from orchestrator.defs.asset_guards.stock_period_retirement import (
    failure_origin,
    latest_retirement_result,
)
from orchestrator.defs.io.stock_period_raw import (
    connection,
    execute,
    file_digest,
    file_version,
)
from orchestrator.defs.io.stock_period_raw import target_path as raw_path
from orchestrator.defs.jobs.raw_stock_period_history_repair import (
    raw_stock_period_history_repair_job,
)
from orchestrator.defs.jobs.silver_stock_period_retirement_cleanup import (
    silver_stock_period_retirement_cleanup_job,
)
from orchestrator.defs.run_contracts.stock_period_delivery import (
    COMPLETION_KEY,
    FREQUENCY_TAG,
    SILVER_SCOPE_KEY,
)
from orchestrator.defs.run_contracts.stock_period_history_repair import (
    StockPeriodHistoryRepairConfig,
    build_history_repair_run_config,
)
from orchestrator.defs.run_contracts.stock_period_retirement_cleanup import (
    JOB_NAME,
    OP_NAME,
    RESULT_KEY,
    WORK_KEY,
    StockPeriodRetirementCleanupConfig,
    build_retirement_run_config,
)
from orchestrator.defs.run_contracts.stock_period_silver import (
    SPECS,
    asset_name,
    check_names,
    target_path,
)
from orchestrator.defs.sensors.silver_stock_period_retirement_cleanup_job_sensor import (
    silver_stock_period_retirement_cleanup_job_sensor,
)
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash as codes_hash,
)
from tests.test_stock_period_native_daily import A, D, I, S, raw_job, reference_for
from tests.test_stock_period_native_daily import market as market  # noqa: PLC0414
from tests.test_stock_period_silver_contracts import literal_row, write_raw

C, B, ALIAS = "000016.SZ", "920799.BJ", "800001.BJ"
PERIODS = {
    "week": ["2014-01-03", "2020-01-31", "2026-11-06"],
    "month": ["2014-01", "2020-01", "2026-10"],
}


def label(freq, period):
    return period.replace("-", "") if freq == "week" else period.replace("-", "") + "31"


def facts(market, *, retired):
    life, identity, basic = (
        paths.silver_stock_lifecycle_path(market.root),
        paths.silver_stock_identity_map_path(market.root),
        paths.raw_stock_basic_path(market.root),
    )
    basic.parent.mkdir(parents=True, exist_ok=True)
    with connection(market.tmp / "facts") as con:
        con.execute(
            "CREATE TEMP TABLE life AS SELECT * FROM read_parquet(?)", [str(life)]
        )
        con.execute("DELETE FROM life WHERE ts_code IN (?,?)", [C, B])
        con.execute(
            "INSERT INTO life VALUES (?, ?, DATE '1991-01-01',NULL::DATE,true),(?, ?,DATE '1991-01-01',NULL::DATE,true)",
            [C, "D" if retired else "L", B, "D" if retired else "L"],
        )
        if retired:
            con.execute(
                "UPDATE life SET delist_date=DATE '2026-11-10' WHERE ts_code IN (?,?)",
                [C, B],
            )
        execute(con, "COPY life TO ? (FORMAT PARQUET)", [str(life)])
        con.execute(
            "CREATE TEMP TABLE ids AS SELECT * FROM read_parquet(?)", [str(identity)]
        )
        con.execute(
            "INSERT INTO ids SELECT * FROM (VALUES (?,?,'confirmed'),(?,?,'confirmed'),(?,?,'confirmed'),('000099.SZ','000001.SZ','confirmed')) v(s,l,c) WHERE s NOT IN (SELECT source_ts_code FROM ids)",
            [C, C, B, B, ALIAS, B],
        )
        execute(con, "COPY ids TO ? (FORMAT PARQUET)", [str(identity)])
        execute(
            con,
            "COPY (SELECT ts_code,list_status FROM life UNION ALL SELECT '000099.SZ','D') TO ? (FORMAT PARQUET)",
            [str(basic)],
        )


def run_silver(market, instance, freq, ref, anchor):
    return market.defs.resolve_job_def(
        asset_name(freq) + "_update_job"
    ).execute_in_process(
        instance=instance,
        partition_key=anchor,
        run_config={
            "ops": {
                asset_name(freq): {
                    "config": {"intent": "update", "source_completion": ref}
                }
            }
        },
    )


def history(ready, freq, periods):
    config = StockPeriodHistoryRepairConfig(
        intent="identity_maintenance",
        business_date=D,
        frequencies=[freq],
        stock_codes=[],
        codes_hash=codes_hash([]),
        remove_keys=[
            {"ts_code": I, "trade_date": label(freq, p), "freq": freq} for p in periods
        ],
    )
    return ready.defs.resolve_job_def(
        raw_stock_period_history_repair_job.name
    ).execute_in_process(
        instance=ready.instance, run_config=build_history_repair_run_config(config)
    )


@pytest.fixture
def ready(market):
    facts(market, retired=False)
    with dg.DagsterInstance.local_temp(
        str(market.tmp / "instance"), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        definitions = dg.Definitions.merge(
            market.defs,
            dg.Definitions(
                jobs=[
                    silver_stock_period_retirement_cleanup_job,
                    raw_stock_period_history_repair_job,
                ]
            ),
        )
        ready = NS(
            market=market,
            instance=instance,
            defs=definitions,
            raw={},
            silver={},
            refs={},
            old={},
            untouched={},
            historical_silver={},
        )
        for freq, periods in PERIODS.items():
            clean = "2019-01-04" if freq == "week" else "2019-01"
            instance.add_dynamic_partitions(
                "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months",
                periods + [clean],
            )
            with connection(market.tmp / ("history_" + freq)) as con:
                for period, retired_code in zip(
                    periods + [clean], [C, ALIAS, B, None], strict=True
                ):
                    rows = [
                        literal_row(
                            A, label(freq, period), freq, asof="20261109", qfq="4.0000"
                        )
                    ]
                    rows.append(
                        literal_row(
                            S, label(freq, period), freq, asof="20261109", qfq="2.0000"
                        )
                    )
                    if retired_code:
                        rows += [
                            literal_row(
                                retired_code,
                                label(freq, period),
                                freq,
                                asof="20261109",
                                qfq="9.0000",
                            )
                        ]
                    write_raw(con, raw_path(market.root, freq, period), rows)
            run = history(ready, freq, sorted(periods + [clean]))
            assert run.success
            historical = run_silver(
                market,
                instance,
                freq,
                reference_for(instance, run.run_id),
                max(periods + [clean]),
            )
            assert historical.success
            ready.historical_silver[freq] = historical
            ready.old[freq] = {
                p: rows_at(market, target_path(market.root, freq, p)) for p in periods
            }
            path = target_path(market.root, freq, clean)
            ready.untouched[freq] = (path, file_version(path), file_digest(path))
        facts(market, retired=True)
        for freq in PERIODS:
            ready.raw[freq] = raw_job(market, instance, freq)
            ready.refs[freq] = reference_for(instance, ready.raw[freq].run_id)
            ready.silver[freq] = run_silver(
                market,
                instance,
                freq,
                ready.refs[freq],
                "2026-11-13" if freq == "week" else "2026-11",
            )
            assert ready.silver[freq].success
        yield ready


def rows_at(market, path):
    with connection(market.tmp / "readback") as con:
        return con.execute(
            "SELECT * FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(path)],
        ).fetchall()


def snapshot(root):
    return {
        str(p): (file_version(p), file_digest(p))
        for p in sorted(root.rglob("*.parquet"))
    }


def configuration(ready, freq, codes=None):
    codes = sorted([C, B] if codes is None else codes)
    return StockPeriodRetirementCleanupConfig(
        business_date=D,
        freq=freq,
        stock_codes=codes,
        codes_hash=codes_hash(codes),
        source_completion=ready.refs[freq],
        source_silver_run_id=ready.silver[freq].run_id,
    )


def run_cleanup(ready, freq, *, config=None, parent=None, raise_on_error=True):
    job = ready.defs.resolve_job_def(JOB_NAME)
    config = build_retirement_run_config(config or configuration(ready, freq))
    if parent is None:
        return job.execute_in_process(
            instance=ready.instance, run_config=config, raise_on_error=raise_on_error
        )
    from dagster._core.definitions.job_base import InMemoryJob
    from dagster._core.execution.api import execute_run

    ancestor = ready.instance.get_run_by_id(parent)
    run = ready.instance.create_run_for_job(
        job_def=job,
        run_config=config,
        parent_run_id=parent,
        root_run_id=ancestor.root_run_id or parent,
    )
    return execute_run(
        InMemoryJob(job), run, ready.instance, raise_on_error=raise_on_error
    )


def observations(ready, run_id, key):
    return [
        r.asset_observation.metadata[key].value
        for r in native_run_records(ready.instance, [run_id], ["ASSET_OBSERVATION"])
        if key in r.asset_observation.metadata
    ]


def result_metadata(ready, run_id, freq):
    values = observations(ready, run_id, RESULT_KEY)
    assert len(values) == 1 and values[0]["freq"] == freq
    return values[0]


def test_confirmed_retirement_requires_both_facts_and_identity(ready):
    assert cleanup.load_confirmed_retirements(ready.market.root) == {
        C: {C},
        B: {B, ALIAS},
        "000004.SZ": {"000004.SZ"},
    }
    assert A not in cleanup.load_confirmed_retirements(ready.market.root)


@pytest.mark.parametrize("freq", ["week", "month"])
def test_real_sensor_cleanup_original_checks_raw_preserved(ready, monkeypatch, freq):
    import resource
    from contextlib import contextmanager

    from orchestrator.defs.io import stock_period_raw as raw_io

    context = NS(
        instance=ready.instance,
        dagster_run=ready.instance.get_run_by_id(ready.silver[freq].run_id),
    )
    request = cleanup.evaluate_retirement_sensor(context, ready.market.resource)
    assert isinstance(request, dg.RunRequest)
    assert (
        cleanup.evaluate_retirement_sensor(context, ready.market.resource).run_key
        == request.run_key
    )
    cfg = request.run_config["ops"][OP_NAME]["config"]
    assert (
        cfg["source_silver_run_id"] == ready.silver[freq].run_id
        and cfg["source_completion"] == ready.refs[freq]
    )
    raw_before = snapshot(ready.market.root / "raw")
    other = "month" if freq == "week" else "week"
    other_before = snapshot(
        target_path(ready.market.root, other, PERIODS[other][0]).parent.parent
    )
    publish = cleanup.publish_period
    writes = []
    measurements = {
        "duckdb_execute": 0,
        "candidate_bytes": [],
        "rows_before": [],
        "code_scans": [],
        "work_bytes_before_publish": [],
    }
    original_connection, original_counts = (
        raw_io.connection,
        cleanup.count_retirement_rows,
    )

    class MeasuredConnection:
        def __init__(self, con):
            self.con = con

        def execute(self, *args, **kwargs):
            measurements["duckdb_execute"] += 1
            return self.con.execute(*args, **kwargs)

        def __getattr__(self, key):
            return getattr(self.con, key)

    @contextmanager
    def measured_connection(*args, **kwargs):
        with original_connection(*args, **kwargs) as con:
            yield MeasuredConnection(con)

    def measured_counts(*args, **kwargs):
        counts = original_counts(*args, **kwargs)
        measurements["code_scans"].append(len(counts))
        return counts

    monkeypatch.setattr(raw_io, "connection", measured_connection)
    monkeypatch.setattr(cleanup, "connection", measured_connection)
    monkeypatch.setattr(cleanup, "count_retirement_rows", measured_counts)

    def checked_publish(item, **kw):
        assert Path(item["target"]).is_relative_to(
            target_path(ready.market.root, freq, PERIODS[freq][0]).parent.parent
        )
        writes.append(item["period"])
        measurements["candidate_bytes"].append(Path(item["candidate"]).stat().st_size)
        measurements["rows_before"].append(item["rows_before"])
        work = Path(item["candidate"]).parents[2]
        measurements["work_bytes_before_publish"].append(
            sum(p.stat().st_size for p in work.rglob("*") if p.is_file())
        )
        return publish(item, **kw)

    monkeypatch.setattr(cleanup, "publish_period", checked_publish)
    monkeypatch.setattr(
        stock_period_source,
        "HttpPage",
        lambda **kw: pytest.fail("cleanup must not download"),
    )
    started = time.monotonic()
    result = run_cleanup(ready, freq, config=StockPeriodRetirementCleanupConfig(**cfg))
    readback_started = time.monotonic()
    assert result.success and writes == PERIODS[freq]
    assert snapshot(ready.market.root / "raw") == raw_before
    assert (
        snapshot(target_path(ready.market.root, other, PERIODS[other][0]).parent.parent)
        == other_before
    )
    for p in PERIODS[freq]:
        assert rows_at(ready.market, target_path(ready.market.root, freq, p)) == [
            r for r in ready.old[freq][p] if r[0] in (A, S)
        ]
    path, version, sha = ready.untouched[freq]
    assert (file_version(path), file_digest(path)) == (version, sha)
    meta = result_metadata(ready, result.run_id, freq)
    assert (
        meta["file_count"],
        meta["rewritten_file_count"],
        meta["removed_row_count"],
    ) == (3, 3, 3)
    records = native_run_records(
        ready.instance,
        [result.run_id],
        ["ASSET_MATERIALIZATION", "ASSET_CHECK_EVALUATION", "ASSET_OBSERVATION"],
    )
    assert not observations(ready, result.run_id, COMPLETION_KEY) and not observations(
        ready, result.run_id, SILVER_SCOPE_KEY
    )
    mats = {
        r.asset_materialization.partition: r for r in records if r.asset_materialization
    }
    checks = [
        r.event_log_entry.dagster_event.event_specific_data
        for r in records
        if r.event_log_entry.dagster_event.event_type_value == "ASSET_CHECK_EVALUATION"
    ]
    assert len(checks) == 9
    for check in checks:
        assert check.passed and check.blocking and check.check_name in check_names(freq)
        assert (
            check.target_materialization_data.storage_id
            == mats[check.partition].storage_id
        )
        assert check.target_materialization_data.run_id == result.run_id
    assert silver_completion_consumed(
        ready.instance,
        ready.refs[freq],
        ["2026-11-13" if freq == "week" else "2026-11"],
        root=ready.market.root,
        business_date=D,
    )
    print(
        json.dumps(
            {
                "freq": freq,
                "N": 5,
                "F": 3,
                "W": 3,
                "removed_rows": 3,
                "result_bytes": len(json.dumps(meta).encode()),
                "measurements": measurements,
                "process_peak_rss_bytes": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss,
                "seconds": time.monotonic() - started,
                "readback_seconds": time.monotonic() - readback_started,
            }
        )
    )


@pytest.mark.parametrize("freq", ["week", "month"])
def test_empty_codes_and_zero_hits_record_result_without_rewriting(
    ready, monkeypatch, freq
):
    with monkeypatch.context() as m:
        m.setattr(
            cleanup,
            "count_retirement_rows",
            lambda *a, **kw: pytest.fail("empty must not enumerate"),
        )
        assert run_cleanup(ready, freq, config=configuration(ready, freq, [])).success
    before = snapshot(ready.market.root)
    result = run_cleanup(ready, freq, config=configuration(ready, freq, ["000004.SZ"]))
    assert result_metadata(ready, result.run_id, freq)["file_count"] == 0
    assert snapshot(ready.market.root) == before
    assert latest_retirement_result(ready.instance, freq) == {"000004.SZ"}


@pytest.mark.parametrize(
    "fault",
    [
        "before_candidate",
        "after_replace",
        "after_materialization",
        "final_counts",
        "cancel",
    ],
)
@pytest.mark.parametrize("freq", ["week", "month"])
def test_failure_blocks_new_even_empty_and_only_original_retry_unblocks(
    ready, monkeypatch, freq, fault
):
    before = snapshot(ready.market.root / "raw")
    original_publish, original_assemble, original_counts = (
        cleanup.publish_period,
        cleanup.assemble_retirement_period,
        cleanup.count_retirement_rows,
    )
    calls = []

    def publish(item, **kw):
        result = original_publish(item, **kw)
        calls.append(item["period"])
        if len(calls) == 1 and fault == "after_replace":
            raise RuntimeError("exit after replace before materialization")
        return result

    def assemble(*a, **kw):
        if fault == "before_candidate" or (fault == "after_materialization" and calls):
            raise RuntimeError("injected candidate failure")
        if fault == "cancel":
            from orchestrator.defs.io.stock_period_raw import PeriodCancelled

            raise PeriodCancelled("injected cancel at candidate boundary")
        return original_assemble(*a, **kw)

    def counts(*a, **kw):
        result = original_counts(*a, **kw)
        return (
            {PERIODS[freq][0]: 1}
            if fault == "final_counts" and "final_counts" in str(kw["work"])
            else result
        )

    with monkeypatch.context() as m:
        m.setattr(cleanup, "publish_period", publish)
        m.setattr(cleanup, "assemble_retirement_period", assemble)
        m.setattr(cleanup, "count_retirement_rows", counts)
        failed = run_cleanup(ready, freq, raise_on_error=False)
    assert not failed.success and not observations(ready, failed.run_id, RESULT_KEY)
    assert snapshot(ready.market.root / "raw") == before
    after = snapshot(ready.market.root)
    next_day = configuration(ready, freq, []).model_copy(
        update={"business_date": "2026-11-11"}
    )
    with monkeypatch.context() as m:
        m.setattr(
            cleanup,
            "retirement_source",
            lambda *a, **kw: pytest.fail("blocked must not read sources"),
        )
        blocked = run_cleanup(ready, freq, config=next_day, raise_on_error=False)
        blocked_again = run_cleanup(
            ready,
            freq,
            config=next_day,
            parent=blocked.run_id,
            raise_on_error=False,
        )
    for result in (blocked, blocked_again):
        assert not result.success and not observations(ready, result.run_id, WORK_KEY)
        assert (
            failure_origin(ready.instance, ready.instance.get_run_by_id(result.run_id))
            == failed.run_id
        )
    assert snapshot(ready.market.root) == after
    clean_versions = {
        p: file_version(target_path(ready.market.root, freq, p)) for p in calls
    }
    rerun = run_cleanup(ready, freq, parent=failed.run_id)
    meta = result_metadata(ready, rerun.run_id, freq)
    assert (
        rerun.success
        and meta["periods"] == PERIODS[freq]
        and meta["rewritten_file_count"] == 3 - len(calls)
    )
    assert all(
        file_version(target_path(ready.market.root, freq, p)) == v
        for p, v in clean_versions.items()
    )
    assert (
        len(
            native_run_records(
                ready.instance, [rerun.run_id], ["ASSET_CHECK_EVALUATION"]
            )
        )
        == 9
    )
    assert run_cleanup(ready, freq, config=configuration(ready, freq, [])).success
    assert snapshot(ready.market.root / "raw") == before


@pytest.mark.parametrize("freq", ["week", "month"])
def test_empty_schema_and_all_columns_preserved(ready, freq):
    p = PERIODS[freq][0]
    with connection(ready.market.tmp / "empty") as con:
        source, target = (
            raw_path(ready.market.root, freq, p),
            target_path(ready.market.root, freq, p),
        )
        for file in (source, target):
            execute(
                con,
                "COPY (SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=?) TO ? (FORMAT PARQUET)",
                [str(file), C, str(file)],
            )
    assert history(ready, freq, [p]).success
    raw_before = snapshot(ready.market.root / "raw")
    assert run_cleanup(ready, freq).success and rows_at(ready.market, target) == []
    with connection(ready.market.tmp / "schema") as con:
        assert (
            tuple(
                (r[0], r[1])
                for r in con.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                    [str(target)],
                ).fetchall()
            )
            == SPECS
        )
    assert snapshot(ready.market.root / "raw") == raw_before


@pytest.mark.parametrize("bad", ["code", "hash", "freq", "extra", "silver_id", "day"])
def test_invalid_intent_fails_before_history(ready, monkeypatch, bad):
    config = configuration(ready, "week").model_dump()
    config.update(
        {
            "code": {"stock_codes": [A], "codes_hash": codes_hash([A])},
            "hash": {"codes_hash": "wrong"},
            "freq": {"freq": "month"},
            "extra": {"resume_run_id": str(uuid4())},
            "silver_id": {"source_silver_run_id": str(uuid4())},
            "day": {"business_date": "2026-11-09"},
        }[bad]
    )
    monkeypatch.setattr(
        cleanup,
        "count_retirement_rows",
        lambda *a, **kw: pytest.fail("invalid must not scan"),
    )
    if bad == "extra":
        with pytest.raises(ValueError):
            StockPeriodRetirementCleanupConfig(**config)
    else:
        result = ready.defs.resolve_job_def(JOB_NAME).execute_in_process(
            instance=ready.instance,
            run_config={"ops": {OP_NAME: {"config": config}}},
            raise_on_error=False,
        )
        assert not result.success


@pytest.mark.parametrize(
    "fault",
    [
        "missing_column",
        "wrong_type",
        "wrong_period",
        "duplicate",
        "other_price",
        "corrupt",
        "reference_changed",
    ],
)
def test_invalid_candidate_never_clears_or_changes_raw(ready, monkeypatch, fault):
    target = target_path(ready.market.root, "week", PERIODS["week"][0])
    raw_before = snapshot(ready.market.root / "raw")
    if fault == "corrupt":
        target.write_bytes(b"not parquet")
    elif fault == "reference_changed":
        assemble = cleanup.assemble_retirement_period

        def changed(*a, **kw):
            result = assemble(*a, **kw)
            paths.silver_stock_lifecycle_path(ready.market.root).touch()
            return result

        monkeypatch.setattr(cleanup, "assemble_retirement_period", changed)
    else:
        selections = {
            "missing_column": "* EXCLUDE (pct_chg)",
            "wrong_type": "* REPLACE (close_qfq::DOUBLE AS close_qfq)",
            "wrong_period": "* REPLACE ('20140110' AS trade_date)",
            "duplicate": "*",
            "other_price": "* REPLACE (CASE WHEN ts_code='000001.SZ' THEN 99::DECIMAL(18,4) ELSE close_qfq END AS close_qfq)",
        }
        with connection(ready.market.tmp / "bad") as con:
            query = f"SELECT {selections[fault]} FROM read_parquet(?,hive_partitioning=false)"
            params = [str(target)]
            if fault == "duplicate":
                query += (
                    " UNION ALL SELECT * FROM read_parquet(?,hive_partitioning=false)"
                )
                params += [str(target)]
            execute(
                con, f"COPY ({query}) TO ? (FORMAT PARQUET)", params + [str(target)]
            )
    result = run_cleanup(ready, "week", raise_on_error=False)
    assert not result.success and not observations(ready, result.run_id, RESULT_KEY)
    assert (
        latest_retirement_result(ready.instance, "week") == set()
        and snapshot(ready.market.root / "raw") == raw_before
    )


def test_raw_alone_non_daily_and_unbound_silver_cannot_trigger(ready):
    context = NS(
        instance=ready.instance,
        dagster_run=ready.instance.get_run_by_id(ready.raw["week"].run_id),
    )
    assert isinstance(
        cleanup.evaluate_retirement_sensor(context, ready.market.resource),
        dg.SkipReason,
    )
    run = ready.instance.get_run_by_id(ready.silver["week"].run_id)
    for intent in [
        "bootstrap",
        "factor_repair",
        "closed_period",
        "history_maintenance",
    ]:
        fake = NS(
            job_name=run.job_name,
            status=run.status,
            run_id=run.run_id,
            run_config={"ops": {asset_name("week"): {"config": {"intent": intent}}}},
        )
        assert isinstance(
            cleanup.evaluate_retirement_sensor(
                NS(instance=ready.instance, dagster_run=fake), ready.market.resource
            ),
            dg.SkipReason,
        )
    from orchestrator.defs.assets.stock_weekly import silver_stock_weekly

    job = dg.define_asset_job("silver_stock_weekly_update_job")
    defs = dg.Definitions(
        assets=[silver_stock_weekly],
        jobs=[job],
        resources={"lake_root": ready.market.resource},
    )
    result = defs.resolve_job_def(job.name).execute_in_process(
        instance=ready.instance, partition_key="2026-11-13", run_config=run.run_config
    )
    assert result.success
    assert isinstance(
        cleanup.evaluate_retirement_sensor(
            NS(
                instance=ready.instance,
                dagster_run=ready.instance.get_run_by_id(result.run_id),
            ),
            ready.market.resource,
        ),
        dg.SkipReason,
    )


def test_other_frequency_old_raw_failure_and_idempotent_repeat(ready):
    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            cleanup,
            "assemble_retirement_period",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("fault")),
        )
        assert not run_cleanup(ready, "month", raise_on_error=False).success

    @dg.job(name="raw_stock_period_retirement_cleanup_job")
    def legacy_job():
        pass

    legacy = ready.instance.create_run_for_job(
        job_def=legacy_job,
        tags={FREQUENCY_TAG: "week"},
    )
    ready.instance.report_run_failed(legacy)
    assert run_cleanup(ready, "week").success
    before = snapshot(ready.market.root)
    again = run_cleanup(ready, "week")
    assert (
        result_metadata(ready, again.run_id, "week")["file_count"] == 0
        and snapshot(ready.market.root) == before
    )
    assert latest_retirement_result(ready.instance, "week") == {C, B}


def test_result_cumulative_and_one_indexed_observation(ready, monkeypatch):
    assert run_cleanup(ready, "week", config=configuration(ready, "week", [C])).success
    assert run_cleanup(ready, "week", config=configuration(ready, "week", [B])).success
    monkeypatch.setattr(
        ready.instance,
        "get_records_for_run",
        lambda *a, **kw: pytest.fail("must not scan history"),
    )
    assert latest_retirement_result(ready.instance, "week") == {C, B}


def test_new_definitions_stopped_and_legacy_removed(ready):
    sensor = silver_stock_period_retirement_cleanup_job_sensor
    assert sensor.default_status == dg.DefaultSensorStatus.STOPPED and set(
        sensor.required_resource_keys
    ) == {"lake_root"}
    base = Path(cleanup.__file__).parent
    for directory, name in [
        ("jobs", "raw_stock_period_retirement_cleanup"),
        ("ops", "raw_stock_period_retirement_cleanup"),
        ("sensors", "raw_stock_period_retirement_cleanup_job_sensor"),
    ]:
        assert not (base / directory / (name + ".py")).exists()
    assert not hasattr(
        __import__(
            "orchestrator.defs.io.stock_period_raw", fromlist=["count_retirement_rows"]
        ),
        "count_retirement_rows",
    )


@pytest.mark.parametrize(
    "fault", ["missing", "version", "freq", "hash", "producer", "periods", "old_raw"]
)
def test_invalid_success_result_does_not_skip_retirements(ready, fault):
    first = run_cleanup(ready, "week")
    meta = result_metadata(ready, first.run_id, "week")

    @dg.op(out={})
    def bad(context):
        context.instance.add_run_tags(context.run_id, {FREQUENCY_TAG: "week"})
        if fault == "missing":
            return
        result = {**meta, "producer_run_id": context.run_id}
        if fault == "version":
            result["version"] = "invalid"
        if fault == "freq":
            result["freq"] = "month"
        if fault == "hash":
            result["cleared_codes_hash"] = "invalid"
        if fault == "producer":
            result["producer_run_id"] = first.run_id
        if fault == "periods":
            result["periods_hash"] = "invalid"
        asset = dg.AssetKey(
            "raw_tushare_stk_period_bar_adj_week"
            if fault == "old_raw"
            else asset_name("week")
        )
        yield dg.AssetObservation(
            asset_key=asset, metadata={RESULT_KEY: dg.MetadataValue.json(result)}
        )

    @dg.job(name=JOB_NAME)
    def invalid():
        bad()

    assert invalid.execute_in_process(instance=ready.instance).success
    with pytest.raises(ValueError, match="period_retirement_result"):
        latest_retirement_result(ready.instance, "week")
    result = run_cleanup(
        ready, "week", config=configuration(ready, "week", []), raise_on_error=False
    )
    assert not result.success and not observations(ready, result.run_id, RESULT_KEY)


def test_native_canceled_previous_run_blocks_and_original_rerun_succeeds(
    ready, monkeypatch
):
    publish = cleanup.publish_period

    def canceled(item, **kw):
        publish(item, **kw)
        raise RuntimeError("cancel after real committed file")

    with monkeypatch.context() as m:
        m.setattr(cleanup, "publish_period", canceled)
        failed = run_cleanup(ready, "week", raise_on_error=False)
    ready.instance.report_run_canceled(ready.instance.get_run_by_id(failed.run_id))
    assert (
        ready.instance.get_run_by_id(failed.run_id).status
        == dg.DagsterRunStatus.CANCELED
    )
    before = snapshot(ready.market.root)
    blocked = run_cleanup(
        ready, "week", config=configuration(ready, "week", []), raise_on_error=False
    )
    assert not blocked.success and snapshot(ready.market.root) == before
    assert run_cleanup(ready, "week", parent=failed.run_id).success


def test_completion_order_controls_result_not_creation_order(ready):
    first = run_cleanup(ready, "week", config=configuration(ready, "week", [C]))
    second = run_cleanup(ready, "week", config=configuration(ready, "week", [B]))
    assert latest_retirement_result(ready.instance, "week") == {C, B}
    from dagster._core.events import DagsterEvent
    from dagster._core.events.log import EventLogEntry

    ready.instance.handle_new_event(
        EventLogEntry(
            error_info=None,
            level=20,
            user_message="late original completion",
            run_id=first.run_id,
            timestamp=time.time() + 1,
            dagster_event=DagsterEvent(
                event_type_value="PIPELINE_SUCCESS", job_name=JOB_NAME
            ),
        )
    )
    assert latest_retirement_result(ready.instance, "week") == {C}
    assert second.success


def test_real_process_exit_after_replace_reexecutes_complete_scope(ready):
    import multiprocessing
    import os
    import signal

    marker = ready.market.tmp / "committed_run"
    raw_before = snapshot(ready.market.root / "raw")

    def child():
        with dg.DagsterInstance.local_temp(
            str(ready.market.tmp / "instance"),
            overrides={"telemetry": {"enabled": False}},
        ) as instance:
            ready.instance = instance
            publish = cleanup.publish_period

            def exit_after_replace(item, **kw):
                value = publish(item, **kw)
                run = instance.get_runs(
                    filters=dg.RunsFilter(
                        job_name=JOB_NAME, statuses=[dg.DagsterRunStatus.STARTED]
                    ),
                    limit=1,
                )[0]
                marker.write_text(run.run_id)
                os.kill(os.getpid(), signal.SIGKILL)
                return value

            cleanup.publish_period = exit_after_replace
            run_cleanup(ready, "week")

    process = multiprocessing.get_context("fork").Process(target=child)
    process.start()
    process.join(30)
    try:
        assert process.exitcode == -signal.SIGKILL and marker.exists()
        run_id = marker.read_text()
        ready.instance.report_run_failed(ready.instance.get_run_by_id(run_id))
        # Monitoring's terminal state is explicit; no worker auto-recovery.
        assert not run_cleanup(
            ready, "week", config=configuration(ready, "week", []), raise_on_error=False
        ).success
        rerun = run_cleanup(ready, "week", parent=run_id)
        assert (
            result_metadata(ready, rerun.run_id, "week")["periods"] == PERIODS["week"]
        )
        assert result_metadata(ready, rerun.run_id, "week")["rewritten_file_count"] == 2
        assert snapshot(ready.market.root / "raw") == raw_before
    finally:
        if process.is_alive():
            process.kill()
            process.join()


def test_both_retirement_facts_and_confirmed_identity_are_required(ready):
    with connection(ready.market.tmp / "contradiction") as con:
        basic = paths.raw_stock_basic_path(ready.market.root)
        life = paths.silver_stock_lifecycle_path(ready.market.root)
        identity = paths.silver_stock_identity_map_path(ready.market.root)
        execute(
            con,
            "COPY (SELECT * REPLACE (CASE WHEN ts_code=? THEN 'L' ELSE list_status END AS list_status) FROM read_parquet(?)) TO ? (FORMAT PARQUET)",
            [C, str(basic), str(basic)],
        )
        execute(
            con,
            "COPY (SELECT * REPLACE (CASE WHEN ts_code=? THEN 'L' ELSE list_status END AS list_status) FROM read_parquet(?)) TO ? (FORMAT PARQUET)",
            [B, str(life), str(life)],
        )
        execute(
            con,
            "COPY (SELECT * REPLACE (CASE WHEN source_ts_code='000004.SZ' THEN 'unknown' ELSE confidence END AS confidence) FROM read_parquet(?)) TO ? (FORMAT PARQUET)",
            [str(identity), str(identity)],
        )
    assert cleanup.load_confirmed_retirements(ready.market.root) == {}
    before = snapshot(ready.market.root)
    assert not run_cleanup(ready, "week", raise_on_error=False).success
    assert snapshot(ready.market.root) == before


@pytest.mark.parametrize("freq", ["week", "month"])
def test_real_non_daily_silver_success_does_not_trigger_cleanup(ready, freq):
    run = ready.instance.get_run_by_id(ready.historical_silver[freq].run_id)
    assert run.status == dg.DagsterRunStatus.SUCCESS
    assert run.run_config["ops"][asset_name(freq)]["config"]["intent"] == "update"
    assert isinstance(
        cleanup.evaluate_retirement_sensor(
            NS(instance=ready.instance, dagster_run=run), ready.market.resource
        ),
        dg.SkipReason,
    )


def test_actual_canceling_state_interrupts_sql_and_blocks_new_request(
    ready, monkeypatch
):
    raw_before = snapshot(ready.market.root / "raw")
    elapsed = []

    def long_sql(con, unit, codes, **kw):
        run = ready.instance.get_runs(
            filters=dg.RunsFilter(
                job_name=JOB_NAME, statuses=[dg.DagsterRunStatus.STARTED]
            ),
            limit=1,
        )[0]
        ready.instance.report_run_canceling(run)
        started = time.monotonic()
        try:
            execute(
                con,
                "SELECT sum(i%97) FROM range(1000000000000) t(i)",
                cancel=kw["cancel"],
            )
        finally:
            elapsed.append(time.monotonic() - started)
        pytest.fail("canceled SQL must not finish")

    with monkeypatch.context() as m:
        m.setattr(cleanup, "assemble_retirement_period", long_sql)
        failed = run_cleanup(ready, "week", raise_on_error=False)
    assert not failed.success and elapsed
    assert not observations(ready, failed.run_id, RESULT_KEY)
    from orchestrator.defs.asset_guards.stock_period_retirement import (
        require_previous_retirement_complete,
    )

    with pytest.raises(dg.Failure) as error:
        require_previous_retirement_complete(
            ready.instance, NS(parent_run_id=None), configuration(ready, "week", [])
        )
    assert error.value.allow_retries is False
    assert error.value.metadata["original_failed_run_id"].value == failed.run_id
    assert snapshot(ready.market.root / "raw") == raw_before
    assert run_cleanup(ready, "week", parent=failed.run_id).success
    print(json.dumps({"cancel_sql_seconds": elapsed[0]}))
