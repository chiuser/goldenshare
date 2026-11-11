"""Real single-frequency jobs/files and native lineage; no formal resources.

Raw stock_basic projects ts_code/list_status VARCHAR from its real producer;
lifecycle and identity use the existing native fixture's real column contracts.
000016.SZ is the documented retirement case. 920799.BJ is deliberately D here
only to test its documented pre-listing bar. Alias relations below are explicit
synthetic cases, not claims about these issuers. Expected rows are literal.
"""

import json
from decimal import Decimal
from types import SimpleNamespace as NS

import dagster as dg
import pytest
from dagster._core.events import DagsterEventType

from orchestrator.defs import paths, stock_period_source
from orchestrator.defs import stock_period_retirement_cleanup as cleanup
from orchestrator.defs.asset_guards.stock_period_delivery import read_completion
from orchestrator.defs.asset_guards.stock_period_retirement import (
    latest_retirement_result,
)
from orchestrator.defs.io.stock_period_raw import connection, execute, file_version
from orchestrator.defs.io.stock_period_raw import target_path as raw_path
from orchestrator.defs.jobs.raw_stock_period_retirement_cleanup import (
    raw_stock_period_retirement_cleanup_job,
)
from orchestrator.defs.run_contracts.stock_period_delivery import (
    COMPLETION_KEY,
    WORK_KEY,
)
from orchestrator.defs.run_contracts.stock_period_retirement_cleanup import (
    JOB_NAME,
    StockPeriodRetirementCleanupConfig,
    build_retirement_run_config,
    retirement_result_check_name,
)
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash as codes_hash,
)
from tests.test_stock_period_native_daily import (
    A,
    D,
    I,
    N,
    price_rows,
    raw_job,
    reference_for,
)
from tests.test_stock_period_native_daily import (
    market as market,  # noqa: PLC0414 -- pytest fixture re-export
)
from tests.test_stock_period_silver_contracts import literal_row, write_raw

C, B, ALIAS = "000016.SZ", "920799.BJ", "800001.BJ"


def write_retirement_facts(market):
    (market.tmp / "instance" / "dagster.yaml").write_text(
        "telemetry:\n  enabled: false\n"
    )
    basic = paths.raw_stock_basic_path(market.root)
    basic.parent.mkdir(parents=True, exist_ok=True)
    life = paths.silver_stock_lifecycle_path(market.root)
    identity = paths.silver_stock_identity_map_path(market.root)
    with connection(market.tmp / "retired_facts") as con:
        con.execute(
            "CREATE TEMP TABLE life AS SELECT * FROM read_parquet(?)", [str(life)]
        )
        con.execute(
            "INSERT INTO life VALUES ('000016.SZ','D',DATE '1991-01-01',DATE '2026-10-28',true),"
            "('920799.BJ','D',DATE '2020-07-27',DATE '2026-11-09',true)"
        )
        execute(con, "COPY life TO ? (FORMAT PARQUET)", [str(life)])
        con.execute(
            "CREATE TEMP TABLE identities AS SELECT * FROM read_parquet(?)",
            [str(identity)],
        )
        con.execute(
            "INSERT INTO identities VALUES ('000016.SZ','000016.SZ','confirmed'),"
            "('920799.BJ','920799.BJ','confirmed'),('800001.BJ','920799.BJ','confirmed'),"
            "('000099.SZ','000001.SZ','confirmed')"
        )
        execute(con, "COPY identities TO ? (FORMAT PARQUET)", [str(identity)])
        execute(
            con,
            "COPY (SELECT * FROM (VALUES ('000016.SZ','D'),('920799.BJ','D'),"
            "('000099.SZ','D'),('000001.SZ','L')) v(ts_code,list_status)) TO ? (FORMAT PARQUET)",
            [str(basic)],
        )


@pytest.fixture
def ready(market):
    write_retirement_facts(market)
    with dg.DagsterInstance.local_temp(str(market.tmp / "instance")) as instance:
        results = {freq: raw_job(market, instance, freq) for freq in ["week", "month"]}
        refs = {
            freq: reference_for(instance, run.run_id) for freq, run in results.items()
        }
        affected = {}
        untouched = {}
        with connection(market.tmp / "old_history") as con:
            for freq, periods in [
                ("week", ["2000-01-07", "2020-01-31", "2026-11-06"]),
                ("month", ["2000-01", "2020-01", "2026-10"]),
            ]:
                affected[freq] = periods
                for index, period in enumerate(periods):
                    label = (
                        period.replace("-", "")
                        if freq == "week"
                        else period.replace("-", "") + "31"
                    )
                    retired = (
                        [C] if index == 0 else [B, ALIAS] if index == 1 else [C, B]
                    )
                    rows = [
                        literal_row(code, label, freq, asof="20261110", qfq="9.0000")
                        for code in retired
                    ]
                    rows.append(
                        literal_row(A, label, freq, asof="20261110", qfq="4.0000")
                    )
                    if freq == "month" and period == "2026-10":
                        rows = [
                            literal_row(
                                code, "20261031", freq, asof="20261110", qfq="9.0000"
                            )
                            for code in retired
                        ] + [
                            literal_row(
                                A, "20261031", freq, asof="20261110", qfq="4.0000"
                            )
                        ]
                    write_raw(con, raw_path(market.root, freq, period), rows)
                period = "2019-01-04" if freq == "week" else "2019-01"
                label = "20190104" if freq == "week" else "20190131"
                path = raw_path(market.root, freq, period)
                write_raw(
                    con,
                    path,
                    [literal_row(A, label, freq, asof="20261110", qfq="4.0000")],
                )
                untouched[freq] = (path, file_version(path))
                instance.add_dynamic_partitions(
                    "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months",
                    periods + [period],
                )
        definitions = dg.Definitions.merge(
            market.defs, dg.Definitions(jobs=[raw_stock_period_retirement_cleanup_job])
        )
        yield NS(
            market=market,
            instance=instance,
            refs=refs,
            raw=results,
            affected=affected,
            untouched=untouched,
            defs=definitions,
        )


def configuration(ready, freq, codes=None):
    codes = sorted([C, B] if codes is None else codes)
    return StockPeriodRetirementCleanupConfig(
        business_date=D,
        freq=freq,
        stock_codes=codes,
        codes_hash=codes_hash(codes),
        source_completion=ready.refs[freq],
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
    result = execute_run(
        InMemoryJob(job), run, ready.instance, raise_on_error=raise_on_error
    )
    assert ready.instance.get_run_by_id(run.run_id).parent_run_id == parent
    return result


def completion(ready, run_id):
    records = ready.instance.get_records_for_run(
        run_id, of_type=DagsterEventType.ASSET_OBSERVATION
    ).records
    values = [
        r.asset_observation.metadata[COMPLETION_KEY].value
        for r in records
        if COMPLETION_KEY in r.asset_observation.metadata
    ]
    if not values:
        return None
    assert len(values) == 1
    return {
        key: values[0][key] for key in ["producer_run_id", "freq", "upstream_batch_id"]
    }


def result_metadata(ready, run_id, freq):
    records = ready.instance.get_records_for_run(
        run_id, of_type=DagsterEventType.ASSET_CHECK_EVALUATION
    ).records
    values = [r.event_log_entry.dagster_event.event_specific_data for r in records]
    result = next(
        v for v in values if v.check_name == retirement_result_check_name(freq)
    )
    return {k: v.value for k, v in result.metadata.items()}


def test_confirmed_retirement_requires_both_facts_and_identity(ready):
    actual = cleanup.load_confirmed_retirements(ready.market.root)
    assert set(actual) == {C, B}
    assert actual[B] == {B, ALIAS}
    assert A not in actual  # Old D alias points to a currently-listed security.


@pytest.mark.parametrize("freq", ["week", "month"])
def test_sensor_submits_only_its_successful_raw_frequency(ready, freq):
    context = NS(
        instance=ready.instance,
        dagster_run=ready.instance.get_run_by_id(ready.raw[freq].run_id),
    )
    first = cleanup.evaluate_retirement_sensor(context, ready.market.resource)
    again = cleanup.evaluate_retirement_sensor(context, ready.market.resource)
    assert isinstance(first, dg.RunRequest) and first.run_key == again.run_key
    config = first.run_config["ops"]["raw_stock_period_retirement_cleanup_op"]["config"]
    assert (
        config["freq"] == freq
        and config["business_date"] == D
        and config["stock_codes"] == [C, B]
    )
    assert config["source_completion"] == ready.refs[freq]


@pytest.mark.parametrize("freq", ["week", "month"])
def test_real_single_frequency_cleanup_and_silver(ready, monkeypatch, freq):
    other = "month" if freq == "week" else "week"
    before = {
        p: file_version(raw_path(ready.market.root, other, p))
        for p in ready.affected[other]
    }
    monkeypatch.setattr(
        stock_period_source,
        "HttpPage",
        lambda **kw: pytest.fail("cleanup must not request Tushare"),
    )
    result = run_cleanup(ready, freq)
    assert result.success
    ref = completion(ready, result.run_id)
    origin = read_completion(ready.instance, ref, root=ready.market.root)
    assert sorted(p for f, p in origin["items"]) == ready.affected[freq]
    for period in ready.affected[freq]:
        assert price_rows(ready.market, raw_path(ready.market.root, freq, period)) == {
            A: Decimal(4)
        }
    for period, version in before.items():
        assert file_version(raw_path(ready.market.root, other, period)) == version
    assert file_version(ready.untouched[freq][0]) == ready.untouched[freq][1]
    assert latest_retirement_result(ready.instance, freq) == {C, B}
    assert latest_retirement_result(ready.instance, other) == set()
    meta = result_metadata(ready, result.run_id, freq)
    assert (
        meta["file_count"] == 3
        and meta["rewritten_file_count"] == 3
        and meta["cleared_codes"] == [C, B]
    )
    assert (
        len(
            ready.instance.get_records_for_run(
                result.run_id, of_type=DagsterEventType.ASSET_CHECK_EVALUATION
            ).records
        )
        == 10
    )
    name = "weekly" if freq == "week" else "monthly"
    anchor = ready.affected[freq][-1]
    silver = ready.defs.resolve_job_def(
        f"silver_stock_{name}_update_job"
    ).execute_in_process(
        instance=ready.instance,
        partition_key=anchor,
        run_config={
            "ops": {
                f"silver_stock_{name}": {
                    "config": {"intent": "update", "source_completion": ref}
                }
            }
        },
    )
    assert silver.success
    from orchestrator.defs.run_contracts.stock_period_silver import target_path

    assert price_rows(ready.market, target_path(ready.market.root, freq, anchor)) == {
        A: Decimal(4)
    }


@pytest.mark.parametrize("freq", ["week", "month"])
def test_empty_list_does_not_enumerate_or_read_history(ready, monkeypatch, freq):
    monkeypatch.setattr(
        cleanup,
        "count_retirement_rows",
        lambda *a, **kw: pytest.fail("zero scans history"),
    )
    monkeypatch.setattr(
        cleanup,
        "assemble_retirement_period",
        lambda *a, **kw: pytest.fail("zero candidate"),
    )
    result = run_cleanup(ready, freq, config=configuration(ready, freq, []))
    assert result.success and completion(ready, result.run_id) is None
    assert result_metadata(ready, result.run_id, freq)["file_count"] == 0


@pytest.mark.parametrize("after_replace", [False, True])
def test_real_native_parent_rebuilds_full_scope_without_replacing_clean_file(
    ready, monkeypatch, after_replace
):
    publish = cleanup.publish_period
    seen = []

    def fault(item, **kwargs):
        seen.append(item["period"])
        if after_replace:
            value = publish(item, **kwargs)
            if len(seen) == 1:
                raise RuntimeError("replace completed before event")
            return value
        if len(seen) == 2:
            raise RuntimeError("second file failed")
        return publish(item, **kwargs)

    monkeypatch.setattr(cleanup, "publish_period", fault)
    failed = run_cleanup(ready, "week", raise_on_error=False)
    assert not failed.success and completion(ready, failed.run_id) is None
    assert latest_retirement_result(ready.instance, "week") == set()
    first = raw_path(ready.market.root, "week", ready.affected["week"][0])
    version = file_version(first)
    monkeypatch.setattr(cleanup, "publish_period", publish)
    success = run_cleanup(ready, "week", parent=failed.run_id)
    assert success.success and file_version(first) == version
    origin = read_completion(
        ready.instance, completion(ready, success.run_id), root=ready.market.root
    )
    assert len(origin["items"]) == 3
    assert result_metadata(ready, success.run_id, "week")["rewritten_file_count"] == 2


def test_zero_physical_hits_still_records_verified_completion(ready):
    first = run_cleanup(ready, "month")
    assert first.success
    again = run_cleanup(ready, "month")
    assert again.success and completion(ready, again.run_id) is None
    meta = result_metadata(ready, again.run_id, "month")
    assert meta["file_count"] == 0 and meta["cleared_codes"] == [C, B]
    assert meta["stock_codes"] == [C, B]


def test_unconfirmed_code_refuses_before_any_history_io(ready, monkeypatch):
    monkeypatch.setattr(
        cleanup,
        "count_retirement_rows",
        lambda *a, **kw: pytest.fail("invalid code read history"),
    )
    result = run_cleanup(
        ready, "week", config=configuration(ready, "week", [A]), raise_on_error=False
    )
    assert not result.success and completion(ready, result.run_id) is None


def test_result_is_cumulative_and_independent_of_business_date_filter(ready):
    first = run_cleanup(ready, "week", config=configuration(ready, "week", [C]))
    assert first.success
    second = run_cleanup(ready, "week", config=configuration(ready, "week", [B]))
    assert second.success
    assert latest_retirement_result(ready.instance, "week") == {C, B}
    assert result_metadata(ready, second.run_id, "week")["stock_codes"] == [B]


def test_sensor_definition_and_real_resource_injection(ready):
    from orchestrator.defs.sensors.raw_stock_period_retirement_cleanup_job_sensor import (
        raw_stock_period_retirement_cleanup_job_sensor as sensor,
    )

    assert (
        sensor.default_status == dg.DefaultSensorStatus.STOPPED
        and sensor.required_resource_keys == {"lake_root"}
    )
    assert sensor.tags["goldenshare/sensor_target_layer"] == "raw"
    with dg.build_run_status_sensor_context(
        sensor_name=sensor.name,
        dagster_instance=ready.instance,
        dagster_run=ready.instance.get_run_by_id(ready.raw["week"].run_id),
        dagster_event=ready.raw["week"].get_run_success_event(),
        resources={"lake_root": ready.market.resource},
    ) as ctx:
        assert isinstance(sensor(ctx), dg.RunRequest)


@pytest.mark.parametrize(
    "change", [{"freq": "month"}, {"codes_hash": "wrong"}, {"stock_codes": [A]}]
)
def test_configuration_refuses_wrong_hash_or_frequency(ready, change):
    with pytest.raises(ValueError):
        configuration(ready, "week").model_copy(update=change).validate_intent()


@pytest.mark.parametrize("freq", ["week", "month"])
def test_emptied_market_file_has_valid_native_delivery_and_silver(ready, freq):
    period = ready.affected[freq][-1]
    label = period.replace("-", "") if freq == "week" else "20261031"
    with connection(ready.market.tmp / "empty_candidate") as con:
        write_raw(
            con,
            raw_path(ready.market.root, freq, period),
            [literal_row(C, label, freq, asof="20261110", qfq="9.0000")],
        )
    result = run_cleanup(ready, freq)
    assert result.success
    ref = completion(ready, result.run_id)
    origin = read_completion(ready.instance, ref, root=ready.market.root)
    assert (
        origin["items"][(freq, period)]["rows"] == 0
        and origin["items"][(freq, period)]["source_asof"] is None
    )
    name = "weekly" if freq == "week" else "monthly"
    silver = ready.defs.resolve_job_def(
        f"silver_stock_{name}_update_job"
    ).execute_in_process(
        instance=ready.instance,
        partition_key=period,
        run_config={
            "ops": {
                f"silver_stock_{name}": {
                    "config": {"intent": "update", "source_completion": ref}
                }
            }
        },
    )
    assert silver.success
    from orchestrator.defs.run_contracts.stock_period_silver import target_path

    assert price_rows(ready.market, target_path(ready.market.root, freq, period)) == {}


def test_candidate_scans_and_plan_persistence_are_frequency_bounded(ready, monkeypatch):
    count = cleanup.count_retirement_rows
    assemble = cleanup.assemble_retirement_period
    scans = []
    units = []

    def counted(root, freq, codes, **kwargs):
        scans.append(freq)
        return count(root, freq, codes, **kwargs)

    def checked(**kwargs):
        units.append(kwargs["freq"])
        run = ready.instance.get_runs(
            filters=dg.RunsFilter(statuses=[dg.DagsterRunStatus.STARTED]), limit=1
        )[0]
        observations = ready.instance.get_records_for_run(
            run.run_id, of_type=DagsterEventType.ASSET_OBSERVATION
        ).records
        plans = [
            r.asset_observation.metadata[WORK_KEY].value
            for r in observations
            if WORK_KEY in r.asset_observation.metadata
        ]
        assert (
            len(plans) == 1
            and plans[0]["freq"] == "week"
            and plans[0]["periods"] == ready.affected["week"]
        )
        return assemble(**kwargs)

    monkeypatch.setattr(cleanup, "count_retirement_rows", counted)
    monkeypatch.setattr(cleanup, "assemble_retirement_period", checked)
    from orchestrator.defs.io import stock_period_raw as io

    monkeypatch.setattr(io, "read_json", lambda *a: pytest.fail("old control JSON"))
    monkeypatch.setattr(
        io, "assemble", lambda *a, **k: pytest.fail("old mixed assembler")
    )
    for file in ["baseline.json", "daily.json"]:
        (ready.market.staging / "stock_period" / file).write_text("invalid old control")
    assert (
        run_cleanup(ready, "week").success
        and scans == ["week", "week"]
        and units == ["week"] * 3
    )


def test_raw_success_without_original_checks_does_not_submit(ready):
    from orchestrator.defs.assets.stock_weekly import (
        raw_tushare_stk_period_bar_adj_week,
    )

    job = dg.define_asset_job("raw_stk_period_bar_adj_week_update_job")
    definitions = dg.Definitions(
        assets=[raw_tushare_stk_period_bar_adj_week],
        jobs=[job],
        resources={"lake_root": ready.market.resource},
    )
    result = definitions.resolve_job_def(job.name).execute_in_process(
        instance=ready.instance,
        partition_key="2026-11-13",
        run_config={
            "ops": {
                "raw_tushare_stk_period_bar_adj_week": {
                    "config": {"automatic_intent_date": D}
                }
            }
        },
    )
    assert result.success
    decision = cleanup.evaluate_retirement_sensor(
        NS(
            instance=ready.instance,
            dagster_run=ready.instance.get_run_by_id(result.run_id),
        ),
        ready.market.resource,
    )
    assert isinstance(decision, dg.SkipReason)


@pytest.mark.parametrize(
    "intent", ["closed_period", "factor_repair", "retirement_cleanup"]
)
def test_sensor_rejects_non_daily_and_recursive_notifications(ready, intent):
    run = NS(
        job_name="raw_stk_period_bar_adj_week_update_job",
        run_config={
            "ops": {
                "raw_tushare_stk_period_bar_adj_week": {
                    "config": {"automatic_intent_date": D, "intent": intent}
                }
            }
        },
    )
    assert isinstance(
        cleanup.evaluate_retirement_sensor(
            NS(instance=ready.instance, dagster_run=run), ready.market.resource
        ),
        dg.SkipReason,
    )
    run = NS(job_name=JOB_NAME)
    assert isinstance(
        cleanup.evaluate_retirement_sensor(
            NS(instance=ready.instance, dagster_run=run), ready.market.resource
        ),
        dg.SkipReason,
    )


@pytest.mark.parametrize("had_prior_work", [False, True])
def test_reexecution_skips_ancestors_without_work_scope(
    ready, monkeypatch, had_prior_work
):
    publish = cleanup.publish_period
    load = cleanup.load_confirmed_retirements
    seen = []
    if had_prior_work:

        def fault(item, **kwargs):
            seen.append(item["period"])
            if len(seen) == 2:
                raise RuntimeError("partial write")
            return publish(item, **kwargs)

        monkeypatch.setattr(cleanup, "publish_period", fault)
    else:
        monkeypatch.setattr(
            cleanup,
            "load_confirmed_retirements",
            lambda *a: (_ for _ in ()).throw(RuntimeError("before scope")),
        )
    first = run_cleanup(ready, "week", raise_on_error=False)
    assert not first.success
    monkeypatch.setattr(
        cleanup,
        "load_confirmed_retirements",
        lambda *a: (_ for _ in ()).throw(RuntimeError("intermediate before scope")),
    )
    middle = run_cleanup(ready, "week", parent=first.run_id, raise_on_error=False)
    assert not middle.success
    monkeypatch.setattr(cleanup, "publish_period", publish)
    monkeypatch.setattr(cleanup, "load_confirmed_retirements", load)
    last = run_cleanup(ready, "week", parent=middle.run_id)
    assert (
        last.success and result_metadata(ready, last.run_id, "week")["file_count"] == 3
    )
    assert result_metadata(ready, last.run_id, "week")["rewritten_file_count"] == (
        2 if had_prior_work else 3
    )


@pytest.mark.parametrize(
    "fault", ["missing", "passed", "version", "freq", "hash", "nonblocking_failure"]
)
def test_latest_success_with_invalid_result_cannot_be_treated_as_empty(ready, fault):
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
    )

    first = run_cleanup(ready, "week")
    assert first.success
    metadata = result_metadata(ready, first.run_id, "week")

    @dg.op(out={})
    def wrong_result(context):
        # Deliberately invalid native producer; proves the reader rejects bad evidence.
        from orchestrator.defs.run_contracts.stock_period_delivery import (
            period_run_tags,
        )

        context.instance.add_run_tags(
            context.run_id,
            period_run_tags(business_date=D, kind="retirement_cleanup", freq="week"),
        )
        if fault == "missing":
            return
        meta = {**metadata, "producer_run_id": context.run_id}
        if fault == "version":
            meta["version"] = "invalid"
        if fault == "freq":
            meta["freq"] = "month"
        if fault == "hash":
            meta["cleared_codes_hash"] = "invalid"
        yield AssetCheckEvaluation(
            asset_key=dg.AssetKey("raw_tushare_stk_period_bar_adj_week"),
            check_name=retirement_result_check_name("week"),
            passed=fault not in ("passed", "nonblocking_failure"),
            blocking=fault != "nonblocking_failure",
            partition="2026-11-13",
            metadata=meta,
        )

    @dg.job(name=JOB_NAME)
    def invalid_result_job():
        wrong_result()

    result = invalid_result_job.execute_in_process(
        instance=ready.instance, raise_on_error=False
    )
    if fault == "passed":
        # A real failed blocking check fails its run; the prior SUCCESS remains authoritative.
        assert not result.success and latest_retirement_result(
            ready.instance, "week"
        ) == {C, B}
        return
    assert result.success
    with pytest.raises(ValueError, match="period_retirement_result"):
        latest_retirement_result(ready.instance, "week")


def test_result_lookup_reads_one_indexed_result_not_all_original_checks(
    ready, monkeypatch
):
    from contextlib import contextmanager

    from orchestrator.defs.asset_guards import stock_period_retirement as guard

    assert run_cleanup(ready, "week").success
    get_runs = ready.instance.get_run_records
    connection_ = ready.instance.event_log_storage.index_connection
    limits = []
    queries = []

    def runs(**kwargs):
        limits.append(kwargs["limit"])
        assert kwargs["order_by"] == "end_time" and not kwargs["ascending"]
        return get_runs(**kwargs)

    @contextmanager
    def connected():
        with connection_() as con:

            class Proxy:
                def execute(self, statement):
                    queries.append(statement)
                    return con.execute(statement)

            yield Proxy()

    monkeypatch.setattr(ready.instance, "get_run_records", runs)
    monkeypatch.setattr(ready.instance.event_log_storage, "index_connection", connected)
    monkeypatch.setattr(
        guard,
        "native_run_records",
        lambda *a: pytest.fail("unbounded original check read"),
    )
    assert latest_retirement_result(ready.instance, "week") == {C, B}
    assert limits == [1] and len(queries) == 1 and queries[0]._limit_clause.value == 1
    params = queries[0].compile().params
    assert retirement_result_check_name("week") in params.values()


def test_cumulative_result_uses_completion_order_when_creation_order_differs(ready):
    from dagster._core.definitions.job_base import InMemoryJob
    from dagster._core.execution.api import execute_run

    job = ready.defs.resolve_job_def(JOB_NAME)
    pending = ready.instance.create_run_for_job(
        job_def=job,
        run_config=build_retirement_run_config(configuration(ready, "week", [C])),
    )
    assert run_cleanup(ready, "week", config=configuration(ready, "week", [B])).success
    last = execute_run(InMemoryJob(job), pending, ready.instance, raise_on_error=True)
    assert last.success
    assert result_metadata(ready, last.run_id, "week")["cleared_codes"] == sorted(
        [C, B]
    )
    assert latest_retirement_result(ready.instance, "week") == {C, B}


def test_sensor_requires_only_its_own_raw_success(market):
    write_retirement_facts(market)
    with dg.DagsterInstance.local_temp(str(market.tmp / "instance")) as instance:
        result = raw_job(market, instance, "week")
        assert result.success
        decision = cleanup.evaluate_retirement_sensor(
            NS(instance=instance, dagster_run=instance.get_run_by_id(result.run_id)),
            market.resource,
        )
        assert isinstance(decision, dg.RunRequest)


def test_configuration_extra_and_private_resume_fields_are_rejected(ready):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StockPeriodRetirementCleanupConfig(
            **configuration(ready, "week").model_dump(), execution_id="a" * 64
        )


def day_inputs(ready, day):
    suspension = paths.silver_stock_suspend_daily_path(ready.market.root, day)
    suspension.parent.mkdir(parents=True, exist_ok=True)
    with connection(ready.market.tmp / "day_inputs") as con:
        execute(
            con,
            "COPY (SELECT NULL::VARCHAR ts_code,NULL::DATE trade_date,NULL::VARCHAR suspend_type,NULL::VARCHAR suspend_timing WHERE false) TO ? (FORMAT PARQUET)",
            [str(suspension)],
        )
        execute(
            con,
            "COPY (SELECT 'SSE' exchange,d::DATE trade_date,true is_open,NULL::DATE pretrade_date "
            "FROM (VALUES ('2026-11-09'),('2026-11-10'),('2026-11-11')) v(d)) TO ? (FORMAT PARQUET)",
            [str(paths.silver_trade_calendar_path(ready.market.root))],
        )


def run_day_raw(ready, monkeypatch, day, codes):
    class Wire:
        def __init__(self, **kwargs):
            pass

        def __call__(self, params):
            rows = [
                literal_row(
                    code,
                    params["trade_date"],
                    params["freq"],
                    asof=day.replace("-", ""),
                    qfq="15.0000",
                )
                for code in codes
            ]
            from orchestrator.defs.run_contracts.stock_period import FIELDS

            return json.dumps(
                {"code": 0, "data": {"fields": list(FIELDS), "items": rows}}
            ).encode()

    monkeypatch.setattr(stock_period_source, "HttpPage", Wire)
    day_inputs(ready, day)
    result = ready.defs.resolve_job_def(
        "raw_stk_period_bar_adj_week_update_job"
    ).execute_in_process(
        instance=ready.instance,
        partition_key="2026-11-13",
        run_config={
            "ops": {
                "raw_tushare_stk_period_bar_adj_week": {
                    "config": {"automatic_intent_date": day}
                }
            }
        },
    )
    assert result.success
    return result


def test_previous_business_day_completed_codes_are_not_submitted_again(
    ready, monkeypatch
):
    day = "2026-11-09"
    raw = run_day_raw(ready, monkeypatch, day, [A, I, "000002.SZ", "000004.SZ"])
    config = StockPeriodRetirementCleanupConfig(
        business_date=day,
        freq="week",
        stock_codes=[C],
        codes_hash=codes_hash([C]),
        source_completion=reference_for(ready.instance, raw.run_id),
    )
    result = run_cleanup(ready, "week", config=config)
    assert result.success
    assert result_metadata(ready, result.run_id, "week")["business_date"] == day
    request = cleanup.evaluate_retirement_sensor(
        NS(
            instance=ready.instance,
            dagster_run=ready.instance.get_run_by_id(ready.raw["week"].run_id),
        ),
        ready.market.resource,
    )
    assert isinstance(request, dg.RunRequest)
    assert request.run_config["ops"]["raw_stock_period_retirement_cleanup_op"][
        "config"
    ]["stock_codes"] == [B]


def test_late_retirement_is_processed_after_next_days_raw_success(ready, monkeypatch):
    assert run_cleanup(ready, "week").success
    life = paths.silver_stock_lifecycle_path(ready.market.root)
    basic = paths.raw_stock_basic_path(ready.market.root)
    with connection(ready.market.tmp / "late_retired") as con:
        con.execute(
            "CREATE TEMP TABLE life AS SELECT * FROM read_parquet(?)", [str(life)]
        )
        con.execute(
            "UPDATE life SET list_status='D',delist_date=DATE '2026-11-11' WHERE ts_code='000003.SZ'"
        )
        execute(con, "COPY life TO ? (FORMAT PARQUET)", [str(life)])
        con.execute(
            "CREATE TEMP TABLE basic AS SELECT * FROM read_parquet(?)", [str(basic)]
        )
        con.execute("INSERT INTO basic VALUES ('000003.SZ','D')")
        execute(con, "COPY basic TO ? (FORMAT PARQUET)", [str(basic)])
    raw = run_day_raw(
        ready, monkeypatch, "2026-11-11", [A, N, "000002.SZ", "000005.SZ"]
    )
    request = cleanup.evaluate_retirement_sensor(
        NS(
            instance=ready.instance,
            dagster_run=ready.instance.get_run_by_id(raw.run_id),
        ),
        ready.market.resource,
    )
    values = request.run_config["ops"]["raw_stock_period_retirement_cleanup_op"][
        "config"
    ]
    assert values["business_date"] == "2026-11-11" and values["stock_codes"] == [I]
    output = run_cleanup(
        ready, "week", config=StockPeriodRetirementCleanupConfig(**values)
    )
    assert output.success and latest_retirement_result(ready.instance, "week") == {
        C,
        B,
        I,
    }


def test_nonzero_final_residual_cannot_publish_completion_or_clear_codes(
    ready, monkeypatch
):
    count = cleanup.count_retirement_rows
    calls = []

    def with_residual(*args, **kwargs):
        calls.append(1)
        value = count(*args, **kwargs)
        if len(calls) == 2:
            value[ready.affected["week"][-1]] = 1
        return value

    monkeypatch.setattr(cleanup, "count_retirement_rows", with_residual)
    result = run_cleanup(ready, "week", raise_on_error=False)
    assert not result.success and completion(ready, result.run_id) is None
    assert latest_retirement_result(ready.instance, "week") == set()


@pytest.mark.parametrize("freq", ["week", "month"])
def test_real_retry_delivery_drives_complete_silver_range(ready, monkeypatch, freq):
    # Independent audit regression: real parent lineage must drive Silver's full range.
    from orchestrator.defs.run_contracts.stock_period_silver import (
        target_path as silver_path,
    )

    original = cleanup.publish_period
    seen = []

    def interrupt(item, **kwargs):
        seen.append(item["period"])
        if len(seen) == 2:
            raise RuntimeError("audit interruption after first completed file")
        return original(item, **kwargs)

    monkeypatch.setattr(cleanup, "publish_period", interrupt)
    failed = run_cleanup(ready, freq, raise_on_error=False)
    assert not failed.success
    unchanged = raw_path(ready.market.root, freq, ready.affected[freq][0])
    version = file_version(unchanged)
    monkeypatch.setattr(cleanup, "publish_period", original)
    retried = run_cleanup(ready, freq, parent=failed.run_id)
    assert retried.success
    assert file_version(unchanged) == version
    ref = completion(ready, retried.run_id)
    origin = read_completion(ready.instance, ref, root=ready.market.root)
    assert sorted(period for _, period in origin["items"]) == ready.affected[freq]
    # Pre-2014 is intentionally outside the existing Silver contract.
    expected = (
        ["2020-01-31", "2026-11-06"] if freq == "week" else ["2020-01", "2026-10"]
    )
    name = "weekly" if freq == "week" else "monthly"
    silver = ready.defs.resolve_job_def(
        f"silver_stock_{name}_update_job"
    ).execute_in_process(
        instance=ready.instance,
        partition_key=expected[-1],
        run_config={
            "ops": {
                f"silver_stock_{name}": {
                    "config": {"intent": "update", "source_completion": ref}
                }
            }
        },
    )
    assert silver.success
    mats = ready.instance.get_records_for_run(
        silver.run_id, of_type=dg.DagsterEventType.ASSET_MATERIALIZATION
    ).records
    assert sorted(r.asset_materialization.partition for r in mats) == expected
    for period in expected:
        assert price_rows(
            ready.market, silver_path(ready.market.root, freq, period)
        ) == {A: Decimal(4)}


def test_corrupt_hit_file_does_not_clear_or_publish_success(ready):
    path = raw_path(ready.market.root, "week", "2020-01-31")
    with connection(ready.market.tmp / "audit-corrupt") as con:
        # Wrong frequency on a physical hit exercises the original full-file validation.
        write_raw(
            con, path, [literal_row("920799.BJ", "20200131", "month", asof="20261110")]
        )
    result = run_cleanup(ready, "week", raise_on_error=False)
    assert not result.success
    assert completion(ready, result.run_id) is None
    assert latest_retirement_result(ready.instance, "week") == set()
