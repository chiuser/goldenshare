"""Manual jobs on owned Parquet/SQLite; only HTTP is replaced.

21 columns use the independent doc365 literals. Stock-basic curr_type/list_status
are the real Silver producer schema; identity is the confirmed producer schema.
Literal prices and exact key lists below define expectations independently.
"""

import json
from decimal import Decimal
from types import SimpleNamespace as NS

import dagster as dg
import pytest
from dagster._core.events import DagsterEventType

from orchestrator.defs import paths, stock_period_silver, stock_period_source
from orchestrator.defs import stock_period_history_repair as repair
from orchestrator.defs.asset_guards.stock_period_delivery import read_completions
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.jobs.raw_stock_period_history_repair import (
    raw_stock_period_history_repair_job,
)
from orchestrator.defs.run_contracts.stock_period import FIELDS
from orchestrator.defs.run_contracts.stock_period_delivery import (
    COMPLETION_KEY,
    WORK_KEY,
)
from orchestrator.defs.run_contracts.stock_period_history_repair import (
    StockPeriodHistoryRepairConfig,
    build_history_repair_run_config,
    normalize_remove_keys,
)
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash as code_hash,
)
from tests.test_stock_period_native_daily import A, D, I
from tests.test_stock_period_native_daily import (
    market as market,  # noqa: PLC0414 -- pytest fixture re-export
)
from tests.test_stock_period_silver_contracts import literal_row, write_raw


def config(*, intent="specified_history", codes=None, frequencies=None, keys=()):
    codes = [A] if codes is None else codes
    return StockPeriodHistoryRepairConfig(
        intent=intent,
        business_date=D,
        stock_codes=codes,
        codes_hash=code_hash(codes),
        frequencies=frequencies or ["week"],
        remove_keys=normalize_remove_keys(keys),
    )


def key(code=A, day="20261106", freq="week"):
    return {"ts_code": code, "trade_date": day, "freq": freq}


@pytest.fixture
def manual(market, monkeypatch):
    basic = paths.silver_stock_basic_path(market.root)
    basic.parent.mkdir(parents=True, exist_ok=True)
    with raw.connection(market.tmp / "basic") as con:
        con.execute(
            "COPY (SELECT * FROM (VALUES ('000001.SZ','CNY','L'),('000003.SZ','CNY','L'),('920001.BJ','CNY','L')) v(ts_code,curr_type,list_status)) TO ? (FORMAT PARQUET)",
            [str(basic)],
        )
    calls, rows = [], {}

    class Wire:
        def __init__(self, **kwargs):
            pass

        def __call__(self, params):
            assert set(params) == {"ts_code", "freq", "limit", "offset"}
            calls.append(dict(params))
            return json.dumps(
                {
                    "code": 0,
                    "data": {
                        "fields": list(FIELDS),
                        "items": rows[(params["ts_code"], params["freq"])],
                    },
                }
            ).encode()

    monkeypatch.setattr(stock_period_source, "HttpPage", Wire)
    monkeypatch.setattr(
        repair,
        "load_factor_changed_codes",
        lambda *a: pytest.fail("manual scanned adjustment factors"),
    )
    monkeypatch.setattr(
        repair,
        "_validate_upstreams",
        lambda *a: pytest.fail("manual required daily completions"),
    )
    defs = dg.Definitions.merge(
        market.defs, dg.Definitions(jobs=[raw_stock_period_history_repair_job])
    )
    with dg.DagsterInstance.local_temp(
        str(market.tmp / "instance"), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        yield NS(
            market=market,
            instance=instance,
            defs=defs,
            calls=calls,
            rows=rows,
            cursors={},
        )


def seed(m, freq, period, rows):
    with raw.connection(m.market.tmp / "seed") as con:
        write_raw(con, raw.target_path(m.market.root, freq, period), rows)
    m.instance.add_dynamic_partitions(
        "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months", [period]
    )


def run(m, cfg, **kwargs):
    return m.defs.resolve_job_def(
        raw_stock_period_history_repair_job.name
    ).execute_in_process(
        instance=m.instance, run_config=build_history_repair_run_config(cfg), **kwargs
    )


def values(m, freq, period):
    with raw.connection(m.market.tmp / "read") as con:
        return con.execute(
            "SELECT ts_code,trade_date,close_qfq FROM read_parquet(?,hive_partitioning=false) ORDER BY 1,2",
            [str(raw.target_path(m.market.root, freq, period))],
        ).fetchall()


def origins(m, result):
    observations = m.instance.get_records_for_run(
        result.run_id, of_type=DagsterEventType.ASSET_OBSERVATION
    ).records
    refs = [
        {
            k: r.asset_observation.metadata[COMPLETION_KEY].value[k]
            for k in ("producer_run_id", "freq", "upstream_batch_id")
        }
        for r in observations
        if COMPLETION_KEY in r.asset_observation.metadata
    ]
    return read_completions(m.instance, refs, root=m.market.root)


def consume_silver(m, freq):
    # The production sensor deliberately reads two observations per tick.
    for _ in range(
        len(
            m.instance.get_records_for_run(
                m.instance.get_runs(limit=1)[0].run_id
            ).records
        )
        + 1
    ):
        with dg.build_sensor_context(
            instance=m.instance,
            resources={"lake_root": m.market.resource},
            cursor=m.cursors.get(freq),
        ) as ctx:
            response = stock_period_silver.evaluate_update_sensor(ctx, freq=freq)
            m.cursors[freq] = ctx.cursor
        if response.run_requests:
            break
    assert len(response.run_requests) == 1
    request = response.run_requests[0]
    result = m.defs.resolve_job_def(request.job_name).execute_in_process(
        instance=m.instance,
        partition_key=request.partition_key,
        run_config=request.run_config,
    )
    assert result.success
    return result


@pytest.mark.parametrize(
    "freq,label,period",
    [("week", "20261106", "2026-11-06"), ("month", "20261031", "2026-10")],
)
def test_only_delete_empty_and_already_absent_deliver_silver(
    manual, monkeypatch, freq, label, period
):
    m = manual
    seed(m, freq, period, [literal_row(A, label, freq)])
    cfg = config(
        intent="identity_maintenance",
        codes=[],
        frequencies=[freq],
        keys=[key(A, label, freq)],
    )
    monkeypatch.setattr(
        stock_period_source,
        "HttpPage",
        lambda **k: pytest.fail("delete requested source"),
    )
    for _ in range(2):
        result = run(m, cfg)
        assert result.success and values(m, freq, period) == [] and m.calls == []
        origin = next(iter(origins(m, result).values()))
        assert origin["completion"]["kind"] == "history_maintenance"
        records = m.instance.get_records_for_run(
            result.run_id, of_type=DagsterEventType.ASSET_OBSERVATION
        ).records
        work = next(
            r.asset_observation.metadata[WORK_KEY].value
            for r in records
            if WORK_KEY in r.asset_observation.metadata
        )
        assert work["remove_keys"] == cfg.remove_keys
        assert work["remove_keys_hash"] == cfg.remove_keys_hash
        consume_silver(m, freq)


def test_mixed_scope_updates_source_only_period_and_removes_exact_key(
    manual, monkeypatch
):
    m = manual
    seed(
        m,
        "week",
        "2026-11-06",
        [
            literal_row(A, "20261106", "week", qfq="1"),
            literal_row(A, "20261105", "week", qfq="2"),
            literal_row(I, "20261106", "week", qfq="3"),
        ],
    )
    seed(
        m,
        "week",
        "2026-10-30",
        [literal_row(A, "20261030", "week", asof="20261110", qfq="4")],
    )
    seed(m, "week", "2026-10-23", [literal_row(A, "20261023", "week", qfq="5")])
    m.rows[(A, "week")] = [
        literal_row(A, "20261106", "week", asof="20261110", qfq="10"),
        literal_row(A, "20261030", "week", asof="20261109", qfq="9"),
    ]
    cfg = config(intent="identity_maintenance", keys=[key(), key(A, "20261023")])
    built = []
    original = repair.assemble_history_maintenance_period

    def assembly(*a, **kw):
        built.append(kw["period"])
        return original(*a, **kw)

    monkeypatch.setattr(repair, "assemble_history_maintenance_period", assembly)
    result = run(m, cfg)
    assert result.success and len(m.calls) == 1
    assert built == ["2026-10-23", "2026-10-30", "2026-11-06"]
    assert values(m, "week", "2026-11-06") == [
        (A, "20261105", Decimal(2)),
        (I, "20261106", Decimal(3)),
    ]
    assert values(m, "week", "2026-10-30") == [(A, "20261030", Decimal(4))]
    assert values(m, "week", "2026-10-23") == []
    assert len(next(iter(origins(m, result).values()))["items"]) == 3
    consume_silver(m, "week")


def test_specified_history_can_refresh_non_factor_stock_single_frequency(manual):
    m = manual
    seed(
        m,
        "month",
        "2020-02",
        [
            literal_row(I, "20200228", "month", asof="20261015", qfq="2"),
            literal_row(I, "20200229", "month", qfq="3"),
            literal_row(A, "20200229", "month", qfq="4"),
        ],
    )
    m.rows[(I, "month")] = [literal_row(I, "20200229", "month", qfq="6")]
    result = run(m, config(codes=[I], frequencies=["month"]))
    assert result.success and len(m.calls) == 1
    assert values(m, "month", "2020-02") == [
        (A, "20200229", Decimal(4)),
        (I, "20200228", Decimal(2)),
        (I, "20200229", Decimal(6)),
    ]
    consume_silver(m, "month")


def test_missing_removal_target_refuses_before_any_candidate(manual, monkeypatch):
    m = manual
    cfg = config(intent="identity_maintenance", codes=[], keys=[key()])
    monkeypatch.setattr(
        repair,
        "assemble_history_maintenance_period",
        lambda *a, **k: pytest.fail("candidate before full scope"),
    )
    with pytest.raises(Exception, match="market_files_missing"):
        run(m, cfg)
    assert m.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"stock_codes": [], "codes_hash": code_hash([])},
        {"upstream_completions": [{}]},
        {"frequencies": ["month", "week"]},
        {"remove_keys": [key()]},
        {"unexpected": 1},
    ],
)
def test_configuration_rejects_mode_mix(change):
    payload = config().model_dump()
    payload.update(change)
    with pytest.raises(ValueError):
        StockPeriodHistoryRepairConfig(**payload).validate_intent()


def test_identity_validation_and_source_admission(manual):
    m = manual
    with pytest.raises(ValueError, match="identity_unconfirmed"):
        repair.load_history_maintenance_scope(
            m.market.root,
            config(intent="identity_maintenance", codes=[], keys=[key("000999.SZ")]),
        )
    with pytest.raises(ValueError, match="not_admitted"):
        repair.load_history_maintenance_scope(
            m.market.root, config(codes=["000002.SZ"])
        )
    # Confirmed old code can be withdrawn but never silently becomes a source request.
    path = paths.silver_stock_identity_map_path(m.market.root)
    with raw.connection(m.market.tmp / "identity") as con:
        con.execute(
            "COPY (SELECT * FROM (VALUES ('832000.BJ','920001.BJ','confirmed')) v(source_ts_code,latest_ts_code,confidence)) TO ? (FORMAT PARQUET)",
            [str(path)],
        )
    aliases = repair.load_history_maintenance_scope(
        m.market.root,
        config(
            intent="identity_maintenance", codes=["920001.BJ"], keys=[key("832000.BJ")]
        ),
    )
    assert aliases == {"832000.BJ": "920001.BJ", "920001.BJ": "920001.BJ"}


@pytest.mark.parametrize("failure", ["after_publish", "before_publish"])
def test_failed_three_file_run_restarts_all_source_and_targets(
    manual, monkeypatch, failure
):
    m = manual
    for freq, period, label in [
        ("week", "2026-11-06", "20261106"),
        ("week", "2026-10-30", "20261030"),
        ("month", "2026-10", "20261031"),
    ]:
        seed(m, freq, period, [literal_row(A, label, freq)])
    cfg = config(
        intent="identity_maintenance",
        frequencies=["week", "month"],
        keys=[key(), key(A, "20261030"), key(A, "20261031", "month")],
    )
    m.rows[(A, "week")] = [literal_row(A, "20261106", "week", qfq="8")]
    m.rows[(A, "month")] = [literal_row(A, "20261031", "month", qfq="9")]
    original = repair.publish_period
    calls = []

    def fail(item, **kw):
        calls.append((item["freq"], item["period"]))
        if failure == "after_publish":
            original(item, **kw)
            raise OSError("after replacement before event")
        if len(calls) == 2:
            raise OSError("second target failed")
        return original(item, **kw)

    monkeypatch.setattr(repair, "publish_period", fail)
    first = run(m, cfg, raise_on_error=False)
    assert not first.success and len(m.calls) == 2
    monkeypatch.setattr(repair, "publish_period", original)
    second = run(m, cfg)
    assert second.success and first.run_id != second.run_id and len(m.calls) == 4
    assert sum(len(o["items"]) for o in origins(m, second).values()) == 3
    consume_silver(m, "week")
    consume_silver(m, "month")


def test_selected_frequency_without_targets_only_has_zero_result(manual):
    m=manual
    seed(m,"week","2026-11-06",[literal_row(A,"20261106","week")])
    cfg=config(intent="identity_maintenance",codes=[],frequencies=["week","month"],keys=[key()])
    result=run(m,cfg)
    assert result.success and m.calls==[]
    observed=origins(m,result)
    assert len(observed)==1 and next(iter(observed.values()))["completion"]["freq"]=="week"
    checks=result.get_asset_check_evaluations()
    results=[c for c in checks if c.check_name.endswith("history_repair_result_check")]
    assert len(results)==2
    month=next(c for c in results if c.asset_key.to_user_string().endswith("month"))
    assert month.metadata["file_count"].value==0
    assert month.metadata["remove_keys"].value==cfg.remove_keys


def test_candidate_and_final_residual_use_only_explicit_keys(manual,monkeypatch):
    m=manual
    seed(m,"week","2026-11-06",[literal_row(A,"20261106","week"),literal_row(I,"20261106","week")])
    seen=[];execute=raw.execute
    def record(*a,**kw):
        if kw.get("stage")=="maintenance_residual":
            seen.append(a[2] if len(a)>2 else kw["parameters"])
        return execute(*a,**kw)
    monkeypatch.setattr(raw,"execute",record)
    result=run(m,config(intent="identity_maintenance",codes=[],keys=[key()]))
    assert result.success and len(seen)==1
    assert seen[0][0]==[str(raw.target_path(m.market.root,"week","2026-11-06"))]
    assert seen[0][1:]==[[A],["20261106"],["week"]]
    assert values(m,"week","2026-11-06")==[(I,"20261106",Decimal("11.14"))]
