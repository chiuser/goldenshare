"""Real repair jobs/files/SQL with only HTTP and upstream acceptance replaced.

Factor columns follow duckdb_sql.adj_factor_normalized_select (DATE/VARCHAR/DOUBLE).
The reused market fixture projects real lifecycle/final-suspension producers.
Prices and selected codes below are independent literals, not production output.
"""

import json
from decimal import Decimal
from types import SimpleNamespace as NS

import dagster as dg
import pytest
from dagster._core.events import DagsterEventType

from orchestrator.defs import paths, stock_period_source
from orchestrator.defs import stock_period_history_repair as repair
from orchestrator.defs.asset_guards.stock_period_delivery import read_completions
from orchestrator.defs.io.stock_period_raw import connection, execute, file_digest
from orchestrator.defs.io.stock_period_raw import target_path as raw_path
from orchestrator.defs.jobs.raw_stock_period_history_repair import (
    raw_stock_period_history_repair_job,
)
from orchestrator.defs.run_contracts.stock_period import FIELDS
from orchestrator.defs.run_contracts.stock_period_delivery import (
    COMPLETION_KEY,
    WORK_KEY,
)
from orchestrator.defs.run_contracts.stock_period_history_repair import (
    FREQUENCIES,
    StockPeriodHistoryRepairConfig,
    build_history_repair_run_config,
)
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash,
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
from tests.test_stock_period_silver_contracts import literal_row, write_raw


def factor_files(market, *, changed=True):
    (market.tmp / "instance" / "dagster.yaml").write_text(
        "telemetry:\n  enabled: false\n"
    )
    with connection(market.tmp / "factor_fixture") as con:
        execute(
            con,
            "COPY (SELECT 'SSE' exchange,d::DATE trade_date,true is_open,NULL::DATE pretrade_date "
            "FROM (VALUES ('2026-11-06'),('2026-11-09'),('2026-11-10')) v(d)) TO ? (FORMAT PARQUET)",
            [str(paths.silver_trade_calendar_path(market.root))],
        )
        for day, values in [
            ("2026-11-09", [(A, 1.0), (I, 2.0)]),
            (D, [(A, 1.1 if changed else 1.0), (I, 2.0), (N, 1.0)]),
        ]:
            p = paths.silver_adj_factor_path(market.root, day)
            p.parent.mkdir(parents=True, exist_ok=True)
            con.execute(
                "CREATE OR REPLACE TEMP TABLE factors(ts_code VARCHAR,trade_date DATE,adj_factor DOUBLE)"
            )
            con.executemany(
                "INSERT INTO factors VALUES (?,?,?)", [(c, day, v) for c, v in values]
            )
            execute(con, "COPY factors TO ? (FORMAT PARQUET)", [str(p)])


@pytest.fixture
def ready(market):
    factor_files(market)
    with dg.DagsterInstance.local_temp(str(market.tmp / "instance")) as instance:
        week = raw_job(market, instance, "week")
        month = raw_job(market, instance, "month")
        assert week.success and month.success
        refs = [reference_for(instance, r.run_id) for r in (week, month)]
        cfg = StockPeriodHistoryRepairConfig(
            business_date=D,
            stock_codes=[A],
            codes_hash=gold_stock_daily_qfq_factor_repair_codes_hash([A]),
            frequencies=FREQUENCIES,
            upstream_completions=refs,
        )
        old = raw_path(market.root, "week", "2026-11-06")
        with connection(market.tmp / "prior") as con:
            write_raw(
                con,
                old,
                [
                    literal_row(A, "20261106", "week", asof="20261109", qfq="9.0000"),
                    literal_row(I, "20261106", "week", asof="20261109", qfq="8.0000"),
                    literal_row(A, "20261105", "week", asof="20261109", qfq="7.0000"),
                ],
            )
        instance.add_dynamic_partitions("cn_a_stock_week_ends", ["2026-11-06"])
        defs = dg.Definitions.merge(
            market.defs, dg.Definitions(jobs=[raw_stock_period_history_repair_job])
        )
        yield NS(
            market=market,
            instance=instance,
            refs=refs,
            cfg=cfg,
            defs=defs,
            week=week,
            month=month,
            old=old,
        )


def install_history_wire(ready, monkeypatch):
    calls, clients = [], []

    class Wire:
        def __init__(self, **kwargs):
            clients.append(self)

        def __call__(self, params):
            assert set(params) == {"ts_code", "freq", "limit", "offset"}
            assert params["ts_code"] == A and params["offset"] == 0
            calls.append(dict(params))
            freq = params["freq"]
            labels = ["20261106", "20261113"] if freq == "week" else ["20261130"]
            rows = [
                literal_row(A, label, freq, asof="20261110", qfq="5.0000")
                for label in labels
            ]
            return json.dumps(
                {"code": 0, "data": {"fields": list(FIELDS), "items": rows}}
            ).encode()

    monkeypatch.setattr(stock_period_source, "HttpPage", Wire)
    return calls, clients


def run_repair(ready, config=None, **kwargs):
    return ready.defs.resolve_job_def(
        "raw_stock_period_history_repair_job"
    ).execute_in_process(
        instance=ready.instance,
        run_config=build_history_repair_run_config(config or ready.cfg),
        **kwargs,
    )


def completions(ready, run_id):
    refs = []
    for r in ready.instance.get_records_for_run(
        run_id, of_type=DagsterEventType.ASSET_OBSERVATION
    ).records:
        v = r.asset_observation.metadata.get(COMPLETION_KEY)
        if v is not None:
            refs.append(
                {
                    k: v.value[k]
                    for k in ("producer_run_id", "freq", "upstream_batch_id")
                }
            )
    return sorted(refs, key=lambda r: FREQUENCIES.index(r["freq"]))


def test_real_factor_change_uses_prior_open_day_and_excludes_new_ipo(market):
    factor_files(market)
    assert repair.load_factor_changed_codes(market.root, D) == [A]
    factor_files(market, changed=False)
    assert repair.load_factor_changed_codes(market.root, D) == []


def test_same_day_pair_two_callback_orders_have_same_run_key(ready):
    def call(result):
        return evaluate(
            NS(
                instance=ready.instance,
                dagster_run=ready.instance.get_run_by_id(result.run_id),
                resources=NS(lake_root=ready.market.resource),
            )
        )

    week, month = call(ready.week), call(ready.month)
    assert isinstance(week, dg.RunRequest) and isinstance(month, dg.RunRequest)
    assert week.run_key == month.run_key and week.run_config == month.run_config
    config = week.run_config["ops"]["raw_stock_period_history_repair_op"]["config"]
    assert config["stock_codes"] == [A] and N not in config["stock_codes"]
    assert [ref["freq"] for ref in config["upstream_completions"]] == ["week", "month"]


def test_only_one_frequency_waits_before_factor_read(market, monkeypatch):
    factor_files(market)
    with dg.DagsterInstance.local_temp(str(market.tmp / "instance")) as instance:
        run = raw_job(market, instance, "week")
        monkeypatch.setattr(
            repair, "load_factor_changed_codes", lambda *a: pytest.fail("too early")
        )
        decision = evaluate(
            NS(
                instance=instance,
                dagster_run=instance.get_run_by_id(run.run_id),
                resources=NS(lake_root=market.resource),
            )
        )
        assert isinstance(decision, dg.SkipReason)


@pytest.mark.parametrize(
    "intent", ["closed_period", "factor_repair", "retirement_cleanup"]
)
def test_non_daily_cannot_recursively_trigger(ready, intent):
    run = ready.instance.get_run_by_id(ready.week.run_id)
    cfg = {
        "ops": {
            "raw_tushare_stk_period_bar_adj_week": {
                "config": {"intent": intent, "automatic_intent_date": D}
            }
        }
    }
    decision = evaluate(
        NS(
            instance=ready.instance,
            dagster_run=NS(job_name=run.job_name, run_config=cfg),
            resources=NS(lake_root=ready.market.resource),
        )
    )
    assert isinstance(decision, dg.SkipReason)


def test_native_history_full_delivery_and_both_silver_jobs(ready, monkeypatch):
    calls, clients = install_history_wire(ready, monkeypatch)
    result = run_repair(ready)
    assert result.success and len(calls) == 2 and len(clients) == 1
    refs = completions(ready, result.run_id)
    delivered = read_completions(ready.instance, refs, root=ready.market.root)
    assert [len(delivered[ref["upstream_batch_id"]]["items"]) for ref in refs] == [2, 1]
    with connection(ready.market.tmp / "verify") as con:
        rows = con.execute(
            "SELECT trade_date,close_qfq FROM read_parquet(?) WHERE ts_code=? ORDER BY trade_date",
            [str(ready.old), A],
        ).fetchall()
    assert rows == [("20261105", Decimal(7)), ("20261106", Decimal(5))]
    assert price_rows(ready.market, ready.old)[I] == Decimal(8)
    from orchestrator.defs.run_contracts.stock_period_silver import target_path

    for ref in refs:
        freq = ref["freq"]
        anchor = "2026-11-13" if freq == "week" else "2026-11"
        name = "weekly" if freq == "week" else "monthly"
        output = ready.defs.resolve_job_def(
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
        assert output.success
        assert price_rows(ready.market, target_path(ready.market.root, freq, anchor))[
            A
        ] == Decimal(5)
    events = ready.instance.get_records_for_run(
        result.run_id, of_type=DagsterEventType.ASSET_CHECK_EVALUATION
    ).records
    assert len(events) == 11
    assert all(
        e.event_log_entry.dagster_event.event_specific_data.passed for e in events
    )
    work = ready.market.staging / "stock_period/runs" / result.run_id
    assert not list(work.rglob("complete.json")) and not list(work.rglob("copy.json"))


def test_zero_changes_records_results_without_http_or_file_delivery(ready, monkeypatch):
    factor_files(ready.market, changed=False)
    config = ready.cfg.model_copy(
        update={
            "stock_codes": [],
            "codes_hash": gold_stock_daily_qfq_factor_repair_codes_hash([]),
        }
    )
    monkeypatch.setattr(
        stock_period_source, "HttpPage", lambda **kw: pytest.fail("zero source")
    )
    before = file_digest(ready.old)
    result = run_repair(ready, config)
    assert (
        result.success
        and completions(ready, result.run_id) == []
        and file_digest(ready.old) == before
    )
    checks = ready.instance.get_records_for_run(
        result.run_id, of_type=DagsterEventType.ASSET_CHECK_EVALUATION
    ).records
    assert len(checks) == 2
    for check in checks:
        metadata = check.event_log_entry.dagster_event.event_specific_data.metadata
        assert metadata["stock_codes"].value == [] and metadata["file_count"].value == 0


def test_changed_scope_refuses_before_source_or_file_write(ready, monkeypatch):
    factor_files(ready.market, changed=False)
    monkeypatch.setattr(
        stock_period_source,
        "HttpPage",
        lambda **kw: pytest.fail("scope mismatch source"),
    )
    before = file_digest(ready.old)
    result = run_repair(ready, raise_on_error=False)
    assert not result.success and file_digest(ready.old) == before


def test_missing_market_file_refuses_before_any_candidate_or_replacement(
    ready, monkeypatch
):
    install_history_wire(ready, monkeypatch)
    ready.old.unlink()
    month = raw_path(ready.market.root, "month", "2026-11")
    before = file_digest(month)
    monkeypatch.setattr(
        repair, "publish_period", lambda *a, **k: pytest.fail("missing target wrote")
    )
    result = run_repair(ready, raise_on_error=False)
    assert (
        not result.success and not ready.old.exists() and file_digest(month) == before
    )
    assert not list(
        (ready.market.staging / "stock_period/runs" / result.run_id).rglob(
            "candidate.parquet"
        )
    )


@pytest.mark.parametrize("failure_after_replace", [False, True])
def test_partial_write_then_full_new_run_repeats_all_sources_and_files(
    ready, monkeypatch, failure_after_replace
):
    calls, _ = install_history_wire(ready, monkeypatch)
    publish = repair.publish_period
    count = []

    def fault(item, **kwargs):
        count.append((item["freq"], item["period"]))
        if failure_after_replace:
            value = publish(item, **kwargs)
            if len(count) == 1:
                raise RuntimeError("after atomic replace before event")
            return value
        if len(count) == 2:
            raise RuntimeError("second file failure")
        return publish(item, **kwargs)

    monkeypatch.setattr(repair, "publish_period", fault)
    failed = run_repair(ready, raise_on_error=False)
    assert not failed.success and completions(ready, failed.run_id) == []
    monkeypatch.setattr(repair, "publish_period", publish)
    success = run_repair(ready)
    assert success.success and success.run_id != failed.run_id and len(calls) == 4
    refs = completions(ready, success.run_id)
    assert (
        sum(
            len(v["items"])
            for v in read_completions(
                ready.instance, refs, root=ready.market.root
            ).values()
        )
        == 3
    )


@pytest.mark.parametrize(
    "change",
    [
        {"frequencies": ["month", "week"]},
        {"codes_hash": "bad"},
        {"stock_codes": [N]},
        {"business_date": "20261110"},
    ],
)
def test_configuration_rejects_wrong_scope(ready, change):
    with pytest.raises(ValueError):
        ready.cfg.model_copy(update=change).validate_intent()


def test_config_rejects_private_resume_parameters(ready):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StockPeriodHistoryRepairConfig(**ready.cfg.model_dump(), execution_id="a" * 64)


def test_definitions_are_scoped_and_default_stopped():
    from orchestrator.defs.sensors.raw_stock_period_history_repair_job_sensor import (
        raw_stock_period_history_repair_job_sensor as sensor,
    )

    assert sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert sensor.tags["goldenshare/sensor_domain"] == "quote_data"
    assert sensor.tags["goldenshare/sensor_target_layer"] == "raw"
    assert sensor.tags["goldenshare/sensor_role"] == "asset_update"


def evaluate(context):
    return repair.evaluate_history_repair_sensor(context, context.resources.lake_root)


from tests.test_stock_period_native_daily import (
    market as market,  # noqa: PLC0414 -- pytest fixture re-export
)


def test_thirteen_factor_changes_and_new_ipo_are_separate(market):
    # Independent synthetic scope: 13 changed existing stocks, one new stock.
    factor_files(market)
    expected = [f"{i:06d}.SZ" for i in range(101, 114)]
    with connection(market.tmp / "thirteen") as con:
        con.execute(
            "CREATE TEMP TABLE life(ts_code VARCHAR,list_status VARCHAR,list_date DATE,delist_date DATE,is_cny_stock BOOLEAN)"
        )
        con.executemany(
            "INSERT INTO life VALUES (?,'L',?,NULL,true)",
            [(c, "2000-01-01") for c in expected] + [(N, D)],
        )
        execute(
            con,
            "COPY life TO ? (FORMAT PARQUET)",
            [str(paths.silver_stock_lifecycle_path(market.root))],
        )
        for day in ("2026-11-09", D):
            con.execute(
                "CREATE OR REPLACE TEMP TABLE factors(ts_code VARCHAR,trade_date DATE,adj_factor DOUBLE)"
            )
            rows = [(c, day, 1.0 if day != D else 1.1) for c in expected]
            if day == D:
                rows.append((N, day, 1.0))
            con.executemany("INSERT INTO factors VALUES (?,?,?)", rows)
            execute(
                con,
                "COPY factors TO ? (FORMAT PARQUET)",
                [str(paths.silver_adj_factor_path(market.root, day))],
            )
    assert repair.load_factor_changed_codes(market.root, D) == expected


def test_preserves_same_key_with_newer_source_date(ready, monkeypatch):
    install_history_wire(ready, monkeypatch)
    current = raw_path(ready.market.root, "week", "2026-11-13")
    with connection(ready.market.tmp / "newer") as con:
        write_raw(
            con,
            current,
            [
                literal_row(A, "20261113", "week", asof="20261111", qfq="19.0000"),
                literal_row(I, "20261113", "week", asof="20261110", qfq="13.0000"),
            ],
        )
    result = run_repair(ready)
    assert result.success and price_rows(ready.market, current)[A] == Decimal(19)
    refs = completions(ready, result.run_id)
    delivered = read_completions(ready.instance, refs, root=ready.market.root)
    week = delivered[refs[0]["upstream_batch_id"]]
    assert (
        week["asof"] == D
        and week["items"][("week", "2026-11-13")]["source_asof"] == "2026-11-11"
    )
    assert week["items"][("week", "2026-11-06")]["source_asof"] == D


def test_source_future_date_rejected_before_any_market_write(ready, monkeypatch):
    before = file_digest(ready.old)

    class Wire:
        def __init__(self, **kwargs):
            pass

        def __call__(self, params):
            label = "20261113" if params["freq"] == "week" else "20261130"
            row = literal_row(A, label, params["freq"], asof="20990101", qfq="5.0000")
            return json.dumps(
                {"code": 0, "data": {"fields": list(FIELDS), "items": [row]}}
            ).encode()

    monkeypatch.setattr(stock_period_source, "HttpPage", Wire)
    result = run_repair(ready, raise_on_error=False)
    assert not result.success and file_digest(ready.old) == before
    assert completions(ready, result.run_id) == []


def test_history_download_full_pages_restart_and_repeat_page_rejection(tmp_path):
    from dataclasses import replace

    from orchestrator.defs.run_contracts.stock_period import DEFAULT_POLICY

    policy = replace(DEFAULT_POLICY, page_limit=1)
    calls = []

    def wire(params):
        calls.append(params)
        rows = (
            []
            if params["offset"] == 2
            else [
                literal_row(
                    A,
                    "20261106" if params["offset"] == 0 else "20261113",
                    "week",
                    asof="20261110",
                )
            ]
        )
        return json.dumps(
            {"code": 0, "data": {"fields": list(FIELDS), "items": rows}}
        ).encode()

    for run in ("a", "b"):
        paths_ = stock_period_source.capture_stock_history(
            work=tmp_path / run,
            freq="week",
            code=A,
            listed={A},
            aliases={},
            transport=wire,
            policy=policy,
        )
        assert len(paths_) == 3
    assert [p["offset"] for p in calls] == [0, 1, 2, 0, 1, 2]
    assert all(set(p) == {"ts_code", "freq", "limit", "offset"} for p in calls)
    duplicate = lambda params: json.dumps(
        {
            "code": 0,
            "data": {
                "fields": list(FIELDS),
                "items": [literal_row(A, "20261113", "week", asof="20261110")],
            },
        }
    ).encode()
    with pytest.raises(ValueError, match="repeated_page"):
        stock_period_source.capture_stock_history(
            work=tmp_path / "duplicate",
            freq="week",
            code=A,
            listed={A},
            aliases={},
            transport=duplicate,
            policy=policy,
        )


def test_real_sensor_resource_injection(ready):
    from orchestrator.defs.sensors.raw_stock_period_history_repair_job_sensor import (
        raw_stock_period_history_repair_job_sensor as sensor,
    )

    assert sensor.required_resource_keys == {"lake_root"}
    with dg.build_run_status_sensor_context(
        sensor_name=sensor.name,
        dagster_instance=ready.instance,
        dagster_run=ready.instance.get_run_by_id(ready.month.run_id),
        dagster_event=ready.month.get_run_success_event(),
        resources={"lake_root": ready.market.resource},
    ) as ctx:
        result = sensor(ctx)
    assert isinstance(result, dg.RunRequest)
    assert result.run_config["ops"]["raw_stock_period_history_repair_op"]["config"][
        "stock_codes"
    ] == [A]


def test_sensor_bounded_native_queries_and_no_history_download(ready, monkeypatch):
    from orchestrator.defs.asset_guards import stock_period_delivery as guard

    calls = []
    events = []
    get_runs = ready.instance.get_runs
    read_events = guard.native_run_records

    def runs(*args, **kwargs):
        calls.append(kwargs.get("limit"))
        return get_runs(*args, **kwargs)

    def records(instance, run_ids, event_types):
        events.append(list(run_ids))
        return read_events(instance, run_ids, event_types)

    monkeypatch.setattr(ready.instance, "get_runs", runs)
    monkeypatch.setattr(guard, "native_run_records", records)
    monkeypatch.setattr(
        stock_period_source,
        "HttpPage",
        lambda **kw: pytest.fail("sensor history source"),
    )
    result = evaluate(
        NS(
            instance=ready.instance,
            dagster_run=ready.instance.get_run_by_id(ready.month.run_id),
            resources=NS(lake_root=ready.market.resource),
        )
    )
    assert isinstance(result, dg.RunRequest) and calls == [1, 2]
    assert len(events) == 1 and set(events[0]) == {
        ready.week.run_id,
        ready.month.run_id,
    }


def test_legacy_progress_not_read_and_write_scopes_persist_before_candidates(
    ready, monkeypatch
):
    from orchestrator.defs.io import stock_period_raw as io

    install_history_wire(ready, monkeypatch)
    old = ready.market.staging / "stock_period"
    for name in ("baseline.json", "daily.json"):
        (old / name).write_text("invalid legacy control")
    monkeypatch.setattr(
        stock_period_source,
        "capture_unit",
        lambda **kw: pytest.fail("old source resume"),
    )
    monkeypatch.setattr(io, "read_json", lambda *a: pytest.fail("private JSON read"))
    monkeypatch.setattr(
        io, "assemble", lambda *a, **kw: pytest.fail("old history assembler")
    )
    assemble = repair.assemble_history_period
    seen = []

    def checked(*args, **kwargs):
        run = ready.instance.get_runs(
            filters=dg.RunsFilter(statuses=[dg.DagsterRunStatus.STARTED]), limit=1
        )[0]
        plans = [
            r.asset_observation
            for r in ready.instance.get_records_for_run(
                run.run_id, of_type=DagsterEventType.ASSET_OBSERVATION
            ).records
            if WORK_KEY in r.asset_observation.metadata
        ]
        assert {p.asset_key.to_user_string() for p in plans} == {
            "raw_tushare_stk_period_bar_adj_week",
            "raw_tushare_stk_period_bar_adj_month",
        }
        seen.append((kwargs["freq"], kwargs["period"]))
        return assemble(*args, **kwargs)

    monkeypatch.setattr(repair, "assemble_history_period", checked)
    assert run_repair(ready).success and len(seen) == 3


def test_calendar_skips_non_trading_day_for_factor_comparison(market):
    factor_files(market)
    with connection(market.tmp / "holiday") as con:
        execute(
            con,
            "COPY (SELECT 'SSE' exchange,d::DATE trade_date,opened is_open,NULL::DATE pretrade_date "
            "FROM (VALUES ('2026-11-06',true),('2026-11-09',false),('2026-11-10',true)) v(d,opened)) TO ? (FORMAT PARQUET)",
            [str(paths.silver_trade_calendar_path(market.root))],
        )
        prior = paths.silver_adj_factor_path(market.root, "2026-11-06")
        prior.parent.mkdir(parents=True, exist_ok=True)
        execute(
            con,
            "COPY (SELECT code ts_code,DATE '2026-11-06' trade_date,value::DOUBLE adj_factor "
            "FROM (VALUES ('000001.SZ',1.0),('000003.SZ',2.0)) v(code,value)) TO ? (FORMAT PARQUET)",
            [str(prior)],
        )
    paths.silver_adj_factor_path(market.root, "2026-11-09").unlink()
    assert repair.load_factor_changed_codes(market.root, D) == [A]


def test_failure_does_not_block_next_trading_day_current_raw(ready, monkeypatch):
    install_history_wire(ready, monkeypatch)
    monkeypatch.setattr(
        repair,
        "publish_period",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("repair interrupted")),
    )
    assert not run_repair(ready, raise_on_error=False).success
    next_day = "2026-11-11"
    suspension = paths.silver_stock_suspend_daily_path(ready.market.root, next_day)
    suspension.parent.mkdir(parents=True, exist_ok=True)
    with connection(ready.market.tmp / "next_day") as con:
        execute(
            con,
            "COPY (SELECT NULL::VARCHAR ts_code,NULL::DATE trade_date,NULL::VARCHAR suspend_type,NULL::VARCHAR suspend_timing WHERE false) TO ? (FORMAT PARQUET)",
            [str(suspension)],
        )
        execute(
            con,
            "COPY (SELECT 'SSE' exchange,DATE '2026-11-11' trade_date,true is_open,NULL::DATE pretrade_date) TO ? (FORMAT PARQUET)",
            [str(paths.silver_trade_calendar_path(ready.market.root))],
        )

    class Wire:
        def __init__(self, **kwargs):
            pass

        def __call__(self, params):
            rows = [
                literal_row(
                    c,
                    params["trade_date"],
                    params["freq"],
                    asof="20261111",
                    qfq="15.0000",
                )
                for c in [A, I, N, "000002.SZ", "000005.SZ"]
            ]
            return json.dumps(
                {"code": 0, "data": {"fields": list(FIELDS), "items": rows}}
            ).encode()

    monkeypatch.setattr(stock_period_source, "HttpPage", Wire)
    for freq in FREQUENCIES:
        result = ready.defs.resolve_job_def(
            f"raw_stk_period_bar_adj_{freq}_update_job"
        ).execute_in_process(
            instance=ready.instance,
            partition_key="2026-11-13" if freq == "week" else "2026-11",
            run_config={
                "ops": {
                    f"raw_tushare_stk_period_bar_adj_{freq}": {
                        "config": {"automatic_intent_date": next_day}
                    }
                }
            },
        )
        assert result.success


def test_original_day_repair_accepts_later_verified_raw_coverage(ready, monkeypatch):
    next_day = "2026-11-11"
    suspension = paths.silver_stock_suspend_daily_path(ready.market.root, next_day)
    suspension.parent.mkdir(parents=True, exist_ok=True)
    with connection(ready.market.tmp / "later_delivery") as con:
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

    class Wire:
        def __init__(self, **kwargs):
            pass

        def __call__(self, params):
            rows = [
                literal_row(
                    c,
                    params["trade_date"],
                    params["freq"],
                    asof="20261111",
                    qfq="15.0000",
                )
                for c in [A, I, N, "000002.SZ", "000005.SZ"]
            ]
            return json.dumps(
                {"code": 0, "data": {"fields": list(FIELDS), "items": rows}}
            ).encode()

    monkeypatch.setattr(stock_period_source, "HttpPage", Wire)
    refs = []
    for freq in FREQUENCIES:
        result = ready.defs.resolve_job_def(
            f"raw_stk_period_bar_adj_{freq}_update_job"
        ).execute_in_process(
            instance=ready.instance,
            partition_key="2026-11-13" if freq == "week" else "2026-11",
            run_config={
                "ops": {
                    f"raw_tushare_stk_period_bar_adj_{freq}": {
                        "config": {"automatic_intent_date": next_day}
                    }
                }
            },
        )
        assert result.success
        refs.append(reference_for(ready.instance, result.run_id))
    install_history_wire(ready, monkeypatch)
    config = ready.cfg.model_copy(update={"upstream_completions": refs})
    result = run_repair(ready, config)
    assert result.success
    delivery = read_completions(
        ready.instance, completions(ready, result.run_id), root=ready.market.root
    )
    assert all(value["asof"] == D for value in delivery.values())
    assert price_rows(ready.market, ready.old)[A] == Decimal(5)
    assert price_rows(ready.market, raw_path(ready.market.root, "week", "2026-11-13"))[
        A
    ] == Decimal(15)


def test_silver_failure_after_repair_rebuilds_full_original_range(ready, monkeypatch):
    from orchestrator.defs import stock_period_silver

    install_history_wire(ready, monkeypatch)
    produced = run_repair(ready)
    assert produced.success
    ref = completions(ready, produced.run_id)[0]
    job = ready.defs.resolve_job_def("silver_stock_weekly_update_job")
    config = {
        "ops": {
            "silver_stock_weekly": {
                "config": {"intent": "update", "source_completion": ref}
            }
        }
    }
    original = stock_period_silver.select_period
    seen = []

    def fault(*args, **kwargs):
        seen.append(args[3])
        if len(seen) == 2:
            raise RuntimeError("second Silver file")
        return original(*args, **kwargs)

    monkeypatch.setattr(stock_period_silver, "select_period", fault)
    failed = job.execute_in_process(
        instance=ready.instance,
        partition_key="2026-11-13",
        run_config=config,
        raise_on_error=False,
    )
    assert not failed.success
    seen.clear()

    def tracked(*args, **kwargs):
        seen.append(args[3])
        return original(*args, **kwargs)

    monkeypatch.setattr(stock_period_silver, "select_period", tracked)
    success = job.execute_in_process(
        instance=ready.instance, partition_key="2026-11-13", run_config=config
    )
    assert success.success and seen == ["2026-11-06", "2026-11-13"]
