"""Period workflow on owned SQLite/Parquet, following LLD 13.18.

Only HTTP, clock, paths and upstream acceptance are replaced. Reference schemas
come from the existing native fixture, adj_factor_normalized_select and the
stock_basic producers; wire literals follow doc365/SPECS. Security states are
synthetic. Expected rows/prices/counts are literal, independent of selectors.
This does not exercise upstream producers, a daemon, real HTTP or formal PG.
"""

import json
import resource
import sys
import time
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

import dagster as dg
import pytest

from orchestrator.defs import paths, stock_period_silver, stock_period_source
from orchestrator.defs import stock_period_history_repair as repair
from orchestrator.defs import stock_period_retirement_cleanup as cleanup
from orchestrator.defs.asset_guards.stock_period_delivery import (
    native_run_records,
    read_completions,
    silver_completion_consumed,
)
from orchestrator.defs.asset_guards.stock_period_retirement import (
    latest_retirement_result,
)
from orchestrator.defs.bootstrap import stock_period_history_cli as cli
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.jobs.raw_stock_period_history_repair import (
    raw_stock_period_history_repair_job,
)
from orchestrator.defs.jobs.raw_stock_period_retirement_cleanup import (
    raw_stock_period_retirement_cleanup_job,
)
from orchestrator.defs.run_contracts.configs import StockPeriodRawConfig
from orchestrator.defs.run_contracts.stock_period import (
    FIELDS,
    STOCK_PERIOD_READINESS_FIELDS,
)
from orchestrator.defs.run_contracts.stock_period_delivery import (
    COMPLETION_KEY,
    SILVER_SCOPE_KEY,
    WORK_KEY,
)
from orchestrator.defs.run_contracts.stock_period_silver import SPECS, target_path
from orchestrator.defs.sensors import (
    raw_stock_monthly_update_job_sensor as month_sensor,
)
from orchestrator.defs.sensors import (
    raw_stock_weekly_update_job_sensor as week_sensor,
)
from orchestrator.defs.sensors.raw_stock_period_history_repair_job_sensor import (
    raw_stock_period_history_repair_job_sensor as history_sensor,
)
from orchestrator.defs.sensors.raw_stock_period_retirement_cleanup_job_sensor import (
    raw_stock_period_retirement_cleanup_job_sensor as retirement_sensor,
)
from orchestrator.defs.sensors.silver_stock_monthly_update_job_sensor import (
    silver_stock_monthly_update_job_sensor as month_silver_sensor,
)
from orchestrator.defs.sensors.silver_stock_weekly_update_job_sensor import (
    silver_stock_weekly_update_job_sensor as week_silver_sensor,
)
from tests.test_stock_period_history_repair_native import factor_files
from tests.test_stock_period_native_daily import A, D, I, N, S
from tests.test_stock_period_native_daily import (
    market as market,  # noqa: PLC0414 -- pytest fixture re-export
)
from tests.test_stock_period_silver_contracts import literal_row, write_raw

RETIRED = "000004.SZ"
PERIODS = {"week": ["2026-11-06", "2026-11-13"], "month": ["2026-10", "2026-11"]}
LABELS = {"week": ["20261106", "20261113"], "month": ["20261031", "20261130"]}
BUSINESS_EVENTS = [
    "ASSET_OBSERVATION",
    "ASSET_MATERIALIZATION",
    "ASSET_CHECK_EVALUATION",
]


@pytest.fixture
def workflow(market, monkeypatch):
    prepare_started = time.monotonic()
    state = {
        "now": datetime.fromisoformat("2026-11-10T20:00:00+08:00"),
        "missing": None,
        "stage": "prepare",
        "fault": None,
        "calls": [],
        "writes": [],
        "sql": [],
        "rss_peak": {},
    }
    factor_files(market)
    basic, current = (
        paths.raw_stock_basic_path(market.root),
        paths.silver_stock_basic_path(market.root),
    )
    for path in (basic, current):
        path.parent.mkdir(parents=True, exist_ok=True)
    with raw.connection(market.tmp / "workflow_facts") as con:
        raw.execute(
            con,
            "COPY (SELECT ts_code,list_status FROM read_parquet(?)) TO ? (FORMAT PARQUET)",
            [str(paths.silver_stock_lifecycle_path(market.root)), str(basic)],
        )
        raw.execute(
            con,
            "COPY (SELECT ts_code,'CNY' curr_type,list_status FROM read_parquet(?) "
            "WHERE ts_code IN ('000001.SZ','000002.SZ','000003.SZ','301393.SZ')) TO ? (FORMAT PARQUET)",
            [str(basic), str(current)],
        )
        for day, codes, factors in [
            ("2026-11-09", [A, S, I, RETIRED], [1.0, 1.0, 2.0, 1.0]),
            (D, [A, S, I, N], [1.1, 1.0, 2.0, 1.0]),
        ]:
            raw.execute(
                con,
                "COPY (SELECT unnest(?)::VARCHAR ts_code,?::DATE trade_date,"
                "unnest(?)::DOUBLE adj_factor) TO ? (FORMAT PARQUET)",
                [
                    codes,
                    day,
                    factors,
                    str(paths.silver_adj_factor_path(market.root, day)),
                ],
            )
        for freq, periods in PERIODS.items():
            for index, period in enumerate(periods):
                label = LABELS[freq][index]
                rows = [
                    literal_row(
                        code,
                        label,
                        freq,
                        asof="20261106" if code == S else "20261109",
                        qfq=price,
                    )
                    for code, price in [
                        (A, "9" if index == 0 else "8"),
                        (I, "8" if index == 0 else "13"),
                        (S, "4"),
                        (RETIRED, "1"),
                    ]
                ]
                if freq == "week" and index == 0:
                    rows.append(
                        literal_row(A, "20261105", freq, asof="20261109", qfq="7")
                    )
                write_raw(con, raw.target_path(market.root, freq, period), rows)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"] if tz is None else state["now"].astimezone(tz)

    for module in (week_sensor, month_sensor, repair, stock_period_silver):
        monkeypatch.setattr(module, "datetime", Clock)

    class Wire:
        def __init__(self, *, fields=FIELDS, **kwargs):
            self.fields = tuple(fields)

        def __call__(self, params, *, deadline=None):
            assert params["limit"] == 6000 and params["offset"] == 0
            freq = params["freq"]
            if "ts_code" in params:
                assert set(params) == {"ts_code", "freq", "limit", "offset"}
                assert params["ts_code"] in (A, I)
                assert self.fields == FIELDS
                rows = [
                    literal_row(
                        params["ts_code"],
                        label,
                        freq,
                        asof="20261110",
                        qfq="5" if params["ts_code"] == A else "6",
                    )
                    for label in LABELS[freq]
                ]
            else:
                assert set(params) == {"trade_date", "freq", "limit", "offset"}
                assert params["trade_date"] == LABELS[freq][-1]
                assert self.fields in (FIELDS, STOCK_PERIOD_READINESS_FIELDS)
                assert (deadline is not None) == (
                    self.fields == STOCK_PERIOD_READINESS_FIELDS
                )
                rows = [
                    literal_row(
                        code, params["trade_date"], freq, asof="20261110", qfq=price
                    )
                    for code, price in [(A, "11"), (N, "12"), (I, "13")]
                    if code != state["missing"]
                ]
            state["calls"].append(
                {
                    "stage": state["stage"],
                    "params": dict(params),
                    "fields": self.fields,
                    "rows": len(rows),
                }
            )
            items = [
                [row[FIELDS.index(field)] for field in self.fields] for row in rows
            ]
            return json.dumps(
                {"code": 0, "data": {"fields": list(self.fields), "items": items}}
            ).encode()

    monkeypatch.setattr(stock_period_source, "HttpPage", Wire)
    original_publish, original_execute = raw.publish_period, raw.execute
    rss_reader = raw.current_rss_bytes

    def current_rss_bytes():
        resident = rss_reader()
        stage = state["stage"]
        state["rss_peak"][stage] = max(state["rss_peak"].get(stage, 0), resident)
        return resident

    monkeypatch.setattr(raw, "current_rss_bytes", current_rss_bytes)

    def publish(item, **kwargs):
        layer = (
            "silver"
            if Path(item["target"]).is_relative_to(market.root / "silver")
            else "raw"
        )
        before = (
            Path(item["target"]).stat().st_size if Path(item["target"]).exists() else 0
        )
        candidate_bytes = Path(item["candidate"]).stat().st_size
        result = original_publish(item, **kwargs)
        state["writes"].append(
            {
                "stage": state["stage"],
                "layer": layer,
                "freq": item["freq"],
                "period": item["period"],
                "rows": item["rows"],
                "prior_target_bytes": before,
                "source_file_bytes": Path(item["source"]).stat().st_size
                if "source" in item
                else None,
                "candidate_bytes": candidate_bytes,
                "output_bytes": Path(item["target"]).stat().st_size,
            }
        )
        if state["fault"] == layer:
            state["fault"] = None
            raise RuntimeError(
                "injected exit after real replace before materialization"
            )
        return result

    def execute(con, sql, *args, **kwargs):
        state["sql"].append(
            {
                "stage": state["stage"],
                "operation": kwargs.get("stage", "unlabelled"),
                "retirement_counts": "count(*) FILTER(WHERE list_contains(?,ts_code))"
                in sql,
            }
        )
        return original_execute(con, sql, *args, **kwargs)

    for module in (raw, repair, cleanup):
        monkeypatch.setattr(module, "publish_period", publish)
    monkeypatch.setattr(raw, "execute", execute)
    definitions = dg.Definitions.merge(
        market.defs,
        dg.Definitions(
            jobs=[
                raw_stock_period_history_repair_job,
                raw_stock_period_retirement_cleanup_job,
            ]
        ),
    )
    with dg.DagsterInstance.local_temp(
        str(market.tmp / "instance"), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        for freq, periods in PERIODS.items():
            instance.add_dynamic_partitions(
                "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months",
                periods,
            )
        flow = NS(
            market=market,
            state=state,
            instance=instance,
            defs=definitions,
            cursors={},
            steps=[
                {
                    "stage": "prepare_extension",
                    "seconds": time.monotonic() - prepare_started,
                    "reference_files": 8,
                    "seed_target_files": 4,
                    "fixture_bytes": sum(
                        p.stat().st_size for p in market.root.rglob("*.parquet")
                    ),
                }
            ],
            runs=[],
            raw_results={},
            retirement_requests={},
            history_request=None,
        )
        yield flow
        print(
            "STOCK_PERIOD_WORKFLOW "
            + json.dumps(
                {
                    "steps": flow.steps,
                    "source_calls": state["calls"],
                    "writes": state["writes"],
                    "helper_sql_count": len(state["sql"]),
                    "retirement_count_queries": sum(
                        q["retirement_counts"] for q in state["sql"]
                    ),
                    "process_peak_rss_bytes": resource.getrusage(
                        resource.RUSAGE_SELF
                    ).ru_maxrss
                    * (1 if sys.platform == "darwin" else 1024),
                    "observed_stage_rss_peak_bytes": state["rss_peak"],
                    "remaining_spill_bytes": sum(
                        p.stat().st_size
                        for p in market.staging.rglob("*")
                        if p.is_file() and "spill" in p.parts
                    ),
                },
                sort_keys=True,
            )
        )


def run_request(
    flow, request, stage, *, job_name=None, parent=None, automatic=True, success=True
):
    flow.state["stage"] = stage
    started = time.monotonic()
    call_count, write_count, sql_count = (
        len(flow.state[k]) for k in ("calls", "writes", "sql")
    )
    job = flow.defs.resolve_job_def(request.job_name or job_name)
    tags = dict(request.tags or {})
    if automatic and request.run_key:
        tags["dagster/run_key"] = request.run_key
    if parent is None:
        result = job.execute_in_process(
            instance=flow.instance,
            run_config=request.run_config,
            partition_key=request.partition_key,
            tags=tags,
            raise_on_error=False,
        )
    else:
        from dagster._core.definitions.job_base import InMemoryJob
        from dagster._core.execution.api import execute_run

        ancestor = flow.instance.get_run_by_id(parent)
        run = flow.instance.create_run_for_job(
            job_def=job,
            run_config=request.run_config,
            tags=tags,
            parent_run_id=parent,
            root_run_id=ancestor.root_run_id or parent,
        )
        result = execute_run(InMemoryJob(job), run, flow.instance, raise_on_error=False)
        assert flow.instance.get_run_by_id(result.run_id).parent_run_id == parent
    source_dir = (
        flow.market.staging / "stock_period" / "runs" / result.run_id / "source"
    )
    flow.steps.append(
        {
            "stage": stage,
            "seconds": time.monotonic() - started,
            "source_calls": len(flow.state["calls"]) - call_count,
            "writes": len(flow.state["writes"]) - write_count,
            "helper_sql": len(flow.state["sql"]) - sql_count,
            "source_persisted_bytes": sum(
                p.stat().st_size for p in source_dir.rglob("*") if p.is_file()
            ),
            "all_run_staging_bytes": sum(
                p.stat().st_size for p in flow.market.staging.rglob("*") if p.is_file()
            ),
            "success": result.success,
        }
    )
    flow.runs.append(result.run_id)
    assert result.success is success, result.run_id
    return result


def raw_sensor(flow, freq):
    started = time.monotonic()
    before = len(flow.state["calls"])
    module = week_sensor if freq == "week" else month_sensor
    sensor = getattr(
        module,
        f"raw_stock_{'weekly' if freq == 'week' else 'monthly'}_update_job_sensor",
    )
    with (
        dg.partition_loading_context(
            dynamic_partitions_store=flow.instance, effective_dt=flow.state["now"]
        ),
        dg.build_sensor_context(
            instance=flow.instance,
            resources={"lake_root": flow.market.resource},
            definitions=flow.defs,
        ) as ctx,
    ):
        response = sensor.evaluate_tick(ctx)
    for addition in response.dynamic_partitions_requests or []:
        flow.instance.add_dynamic_partitions(
            addition.partitions_def_name, addition.partition_keys
        )
    flow.steps.append(
        {
            "stage": "raw_sensor_" + freq,
            "seconds": time.monotonic() - started,
            "source_calls": len(flow.state["calls"]) - before,
            "requested": bool(response.run_requests),
        }
    )
    return response


def callback(flow, sensor, result):
    with dg.build_run_status_sensor_context(
        sensor_name=sensor.name,
        dagster_instance=flow.instance,
        dagster_run=result.dagster_run,
        dagster_event=result.get_run_success_event(),
        resources={"lake_root": flow.market.resource},
    ) as ctx:
        return sensor(ctx)


def records(flow, result):
    return native_run_records(flow.instance, [result.run_id], BUSINESS_EVENTS)


def origins(flow, result, expected):
    rows = records(flow, result)
    refs = [
        {
            k: r.asset_observation.metadata[COMPLETION_KEY].value[k]
            for k in ("producer_run_id", "freq", "upstream_batch_id")
        }
        for r in rows
        if r.asset_observation and COMPLETION_KEY in r.asset_observation.metadata
    ]
    deliveries = read_completions(flow.instance, refs, root=flow.market.root)
    assert len(deliveries) == len(expected)
    assert {key for item in deliveries.values() for key in item["items"]} == {
        (freq, period) for freq, periods in expected.items() for period in periods
    }
    assert all(item["asof"] == D for item in deliveries.values())
    return {
        item["reference"]["freq"]: item["reference"] for item in deliveries.values()
    }


def silver_request(flow, freq):
    sensor = week_silver_sensor if freq == "week" else month_silver_sensor
    with (
        dg.partition_loading_context(
            dynamic_partitions_store=flow.instance, effective_dt=flow.state["now"]
        ),
        dg.build_sensor_context(
            instance=flow.instance,
            resources={"lake_root": flow.market.resource},
            cursor=flow.cursors.get(freq),
            definitions=flow.defs,
        ) as ctx,
    ):
        response = sensor.evaluate_tick(ctx)
        flow.cursors[freq] = response.cursor
    return response


def consume(flow, freq, stage, periods):
    response = silver_request(flow, freq)
    assert len(response.run_requests) == 1, response.skip_message
    request = response.run_requests[0]
    result = run_request(flow, request, stage)
    reference = request.run_config["ops"][
        f"silver_stock_{'weekly' if freq == 'week' else 'monthly'}"
    ]["config"]["source_completion"]
    assert silver_completion_consumed(
        flow.instance, reference, periods, root=flow.market.root, business_date=D
    )
    assert len(records(flow, result)) == 4 * len(periods) + 2
    response = silver_request(flow, freq)
    assert (
        not response.run_requests and response.skip_message == "silver_batch_complete"
    )
    assert "pending" not in json.loads(flow.cursors[freq])
    return result


def read_rows(flow, layer, freq, period):
    path = (
        raw.target_path(flow.market.root, freq, period)
        if layer == "raw"
        else target_path(flow.market.root, freq, period)
    )
    with raw.connection(flow.market.tmp / "readback") as con:
        actual = tuple(
            (r[0], r[1])
            for r in con.execute(
                "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                [str(path)],
            ).fetchall()
        )
        assert actual == SPECS
        rows = con.execute(
            "SELECT ts_code,trade_date,freq,close_qfq,end_date FROM read_parquet(?,hive_partitioning=false) ORDER BY 1,2",
            [str(path)],
        ).fetchall()
    assert len({r[:3] for r in rows}) == len(rows)
    return rows


def row_count(flow):
    return sum(
        len(read_rows(flow, "raw", freq, period))
        for freq, periods in PERIODS.items()
        for period in periods
    )


def prepare_daily(flow, order=("week", "month")):
    assert row_count(flow) == 17
    flow.state["now"] = datetime.fromisoformat("2026-11-10T19:59:00+08:00")
    for freq in order:
        assert not raw_sensor(flow, freq).run_requests
    assert flow.state["calls"] == []
    flow.state["now"] = datetime.fromisoformat("2026-11-10T20:00:00+08:00")
    for index, freq in enumerate(order):
        flow.state.update(stage="probe_" + freq, missing=N)
        assert not raw_sensor(flow, freq).run_requests
        flow.state["missing"] = None
        response = raw_sensor(flow, freq)
        assert len(response.run_requests) == 1
        result = run_request(flow, response.run_requests[0], "daily_" + freq)
        flow.raw_results[freq] = result
        origins(flow, result, {freq: [PERIODS[freq][-1]]})
        assert len(records(flow, result)) == 6
        history = callback(flow, history_sensor, result)
        if index == 0:
            assert isinstance(history, dg.SkipReason)
            assert history.skip_message == "period_repair_waiting_other_frequency"
        else:
            assert isinstance(history, dg.RunRequest)
            flow.history_request = history
        retirement = callback(flow, retirement_sensor, result)
        assert isinstance(retirement, dg.RunRequest)
        cfg = retirement.run_config["ops"]["raw_stock_period_retirement_cleanup_op"][
            "config"
        ]
        assert cfg["freq"] == freq and cfg["stock_codes"] == [RETIRED]
        flow.retirement_requests[freq] = retirement
        consume(flow, freq, "daily_silver_" + freq, [PERIODS[freq][-1]])
    assert row_count(flow) == 19
    cfg = flow.history_request.run_config["ops"]["raw_stock_period_history_repair_op"][
        "config"
    ]
    assert cfg["stock_codes"] == [A] and cfg["frequencies"] == ["week", "month"]
    assert {r["freq"] for r in cfg["upstream_completions"]} == {"week", "month"}
    for freq in order:
        repeated = callback(flow, history_sensor, flow.raw_results[freq])
        assert repeated.run_key == flow.history_request.run_key
        assert repeated.run_config == flow.history_request.run_config
    calls = len(flow.state["calls"])
    for freq in order:
        assert not raw_sensor(flow, freq).run_requests
    assert len(flow.state["calls"]) == calls == 6


def run_factor(flow, stage="factor", *, success=True):
    result = run_request(
        flow,
        flow.history_request,
        stage,
        job_name=raw_stock_period_history_repair_job.name,
        automatic=stage == "factor",
        success=success,
    )
    if success:
        origins(flow, result, PERIODS)
        assert len(records(flow, result)) == 22
    return result


def manual_request(intent, *, code=None, remove=None):
    args = ["--intent", intent, "--business-date", D, "--frequency", "week"]
    if code:
        args.extend(["--stock-code", code])
    if remove:
        args.extend(["--remove-key", remove])
    request = cli.build_maintenance_request(cli.parse_maintenance_args(args))
    assert request["source_units"] == (1 if code else 0)
    return dg.RunRequest(job_name=request["job_name"], run_config=request["run_config"])


def assert_final(flow):
    started = time.monotonic()
    expected = {
        ("week", "2026-11-06"): {A: "5", I: "6", S: "4"},
        ("week", "2026-11-13"): {A: "5", I: "6", S: "4", N: "12"},
        ("month", "2026-10"): {A: "5", I: "8", S: "4"},
        ("month", "2026-11"): {A: "5", I: "13", S: "4", N: "12"},
    }
    byte_count = 0
    for layer in ("raw", "silver"):
        count = 0
        for (freq, period), prices in expected.items():
            rows = read_rows(flow, layer, freq, period)
            label = LABELS[freq][PERIODS[freq].index(period)]
            assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
                (code, label, freq, Decimal(price))
                for code, price in sorted(prices.items())
            ]
            dates = {r[0]: r[4] for r in rows}
            assert dates == {
                code: "20261106"
                if code == S
                else "20261109"
                if code == I and period == "2026-10"
                else "20261110"
                for code in prices
            }
            path = (
                raw.target_path(flow.market.root, freq, period)
                if layer == "raw"
                else target_path(flow.market.root, freq, period)
            )
            byte_count += path.stat().st_size
            count += len(rows)
        assert count == 14
    flow.steps.append(
        {
            "stage": "final_eight_file_audit",
            "seconds": time.monotonic() - started,
            "unique_files": 8,
            "bytes": byte_count,
        }
    )


@pytest.mark.parametrize("order", [("week", "month"), ("month", "week")])
def test_daily_history_retirement_manual_and_silver_complete_workflow(workflow, order):
    flow = workflow
    prepare_daily(flow, order)
    run_factor(flow)
    assert row_count(flow) == 19
    assert any(r[1] == "20261105" for r in read_rows(flow, "raw", "week", "2026-11-06"))
    for freq in ("week", "month"):
        consume(flow, freq, "factor_silver_" + freq, PERIODS[freq])
    for freq in ("week", "month"):
        other = "month" if freq == "week" else "week"
        versions = [
            raw.file_version(raw.target_path(flow.market.root, other, p))
            for p in PERIODS[other]
        ]
        result = run_request(
            flow,
            flow.retirement_requests[freq],
            "retirement_" + freq,
            job_name=raw_stock_period_retirement_cleanup_job.name,
        )
        origins(flow, result, {freq: PERIODS[freq]})
        assert len(records(flow, result)) == 11
        assert latest_retirement_result(flow.instance, freq) == {RETIRED}
        assert versions == [
            raw.file_version(raw.target_path(flow.market.root, other, p))
            for p in PERIODS[other]
        ]
        consume(flow, freq, "retirement_silver_" + freq, PERIODS[freq])
    assert row_count(flow) == 15
    result = run_request(
        flow, manual_request("specified_history", code=I), "manual_history"
    )
    origins(flow, result, {"week": PERIODS["week"]})
    assert len(records(flow, result)) == 11 and row_count(flow) == 15
    consume(flow, "week", "manual_silver", PERIODS["week"])
    result = run_request(
        flow,
        manual_request("identity_maintenance", remove=f"{A},20261105,week"),
        "manual_delete",
    )
    origins(flow, result, {"week": ["2026-11-06"]})
    assert len(records(flow, result)) == 7 and row_count(flow) == 14
    consume(flow, "week", "delete_silver", ["2026-11-06"])
    assert_final(flow)
    assert len(flow.state["calls"]) == 9
    assert sum(c["rows"] for c in flow.state["calls"] if c["fields"] == FIELDS) == 12
    assert (
        sum(
            c["rows"]
            for c in flow.state["calls"]
            if c["fields"] == STOCK_PERIOD_READINESS_FIELDS
        )
        == 10
    )
    assert Counter(w["layer"] for w in flow.state["writes"]) == {
        "raw": 13,
        "silver": 13,
    }
    assert sum(q["retirement_counts"] for q in flow.state["sql"]) == 4
    assert len(native_run_records(flow.instance, flow.runs, BUSINESS_EVENTS)) == 142
    assert not list(flow.market.staging.rglob("daily.json"))
    assert not list(flow.market.staging.rglob("baseline.json"))


def assert_failed_without_delivery(flow, result, *, work_count):
    rows = records(flow, result)
    observations = [r.asset_observation for r in rows if r.asset_observation]
    assert sum(WORK_KEY in r.metadata for r in observations) == work_count
    assert not any(COMPLETION_KEY in r.metadata for r in observations)
    assert not any(r.asset_materialization for r in rows)
    assert not any(
        r.event_log_entry.dagster_event.event_type_value == "ASSET_CHECK_EVALUATION"
        for r in rows
    )
    assert (
        flow.instance.get_run_by_id(result.run_id).status == dg.DagsterRunStatus.FAILURE
    )


def assert_repaired_files(flow, scopes, layers, *, weekly_cleaned=False):
    """Literal pre-manual expectations; no production selector builds expected."""
    started = time.monotonic()
    expected = {
        ("week", "2026-11-06"): [
            (A, "5", "20261110"),
            (I, "8", "20261109"),
            (S, "4", "20261106"),
        ],
        ("week", "2026-11-13"): [
            (A, "5", "20261110"),
            (I, "13", "20261110"),
            (S, "4", "20261106"),
            (N, "12", "20261110"),
        ],
        ("month", "2026-10"): [
            (A, "5", "20261110"),
            (I, "8", "20261109"),
            (S, "4", "20261106"),
        ],
        ("month", "2026-11"): [
            (A, "5", "20261110"),
            (I, "13", "20261110"),
            (S, "4", "20261106"),
            (N, "12", "20261110"),
        ],
    }
    files, byte_count, row_counts = 0, 0, {}
    for layer in layers:
        for freq, periods in scopes.items():
            for period in periods:
                label = LABELS[freq][PERIODS[freq].index(period)]
                wanted = [
                    (code, label, freq, Decimal(price), asof)
                    for code, price, asof in expected[(freq, period)]
                ]
                if layer == "raw":
                    if not (freq == "week" and weekly_cleaned):
                        wanted.append((RETIRED, label, freq, Decimal(1), "20261109"))
                    if freq == "week" and period == "2026-11-06":
                        wanted.append((A, "20261105", freq, Decimal(7), "20261109"))
                assert read_rows(flow, layer, freq, period) == sorted(wanted)
                path = (
                    raw.target_path(flow.market.root, freq, period)
                    if layer == "raw"
                    else target_path(flow.market.root, freq, period)
                )
                files += 1
                byte_count += path.stat().st_size
                row_counts[layer] = row_counts.get(layer, 0) + len(wanted)
    flow.steps.append(
        {
            "stage": "failure_final_file_audit",
            "seconds": time.monotonic() - started,
            "unique_files": files,
            "bytes": byte_count,
            "rows_by_layer": row_counts,
        }
    )


def test_failed_factor_restarts_both_frequencies_and_silver_uses_success(workflow):
    flow = workflow
    prepare_daily(flow)
    calls, writes = len(flow.state["calls"]), len(flow.state["writes"])
    flow.state["fault"] = "raw"
    failed = run_factor(flow, "factor_failed", success=False)
    assert_failed_without_delivery(flow, failed, work_count=2)
    for freq in ("week", "month"):
        assert not silver_request(flow, freq).run_requests
    result = run_factor(flow, "factor_rerun")
    refs = origins(flow, result, PERIODS)
    assert all(r["producer_run_id"] == result.run_id for r in refs.values())
    for freq in ("week", "month"):
        consume(flow, freq, "factor_rerun_silver_" + freq, PERIODS[freq])
    assert len(flow.state["calls"]) - calls == 4
    assert sum(c["rows"] for c in flow.state["calls"][calls:]) == 8
    assert Counter(w["layer"] for w in flow.state["writes"][writes:]) == {
        "raw": 5,
        "silver": 4,
    }
    assert_repaired_files(flow, PERIODS, ("raw", "silver"))


def test_failed_retirement_reruns_native_complete_scope_and_silver(workflow):
    flow = workflow
    prepare_daily(flow)
    run_factor(flow)
    for freq in ("week", "month"):
        consume(flow, freq, "factor_silver_" + freq, PERIODS[freq])
    calls, writes = len(flow.state["calls"]), len(flow.state["writes"])
    queries = sum(q["retirement_counts"] for q in flow.state["sql"])
    flow.state["fault"] = "raw"
    request = flow.retirement_requests["week"]
    failed = run_request(
        flow,
        request,
        "retirement_failed",
        job_name=raw_stock_period_retirement_cleanup_job.name,
        success=False,
    )
    assert_failed_without_delivery(flow, failed, work_count=1)
    # A failed producer leaves work, not completion. Advance the real cursor
    # over that observation before asking it to consume the successful rerun.
    assert not silver_request(flow, "week").run_requests
    assert latest_retirement_result(flow.instance, "week") == set()
    first = raw.target_path(flow.market.root, "week", "2026-11-06")
    version = raw.file_version(first)
    result = run_request(
        flow,
        request,
        "retirement_rerun",
        job_name=raw_stock_period_retirement_cleanup_job.name,
        parent=failed.run_id,
        automatic=False,
    )
    origins(flow, result, {"week": PERIODS["week"]})
    assert raw.file_version(first) == version
    consume(flow, "week", "retirement_rerun_silver", PERIODS["week"])
    assert len(flow.state["calls"]) == calls
    assert Counter(w["layer"] for w in flow.state["writes"][writes:]) == {
        "raw": 2,
        "silver": 2,
    }
    assert sum(q["retirement_counts"] for q in flow.state["sql"]) - queries == 3
    assert_repaired_files(
        flow, {"week": PERIODS["week"]}, ("raw", "silver"), weekly_cleaned=True
    )


def test_failed_silver_restarts_complete_raw_reference_and_acknowledges(workflow):
    flow = workflow
    prepare_daily(flow)
    result = run_factor(flow)
    reference = origins(flow, result, PERIODS)["week"]
    response = silver_request(flow, "week")
    assert len(response.run_requests) == 1
    request = response.run_requests[0]
    calls, writes = len(flow.state["calls"]), len(flow.state["writes"])
    raw_versions = [
        raw.file_version(raw.target_path(flow.market.root, "week", p))
        for p in PERIODS["week"]
    ]
    flow.state["fault"] = "silver"
    failed = run_request(flow, request, "silver_failed", success=False)
    rows = records(flow, failed)
    assert not any(r.asset_materialization for r in rows)
    scopes = [
        r.asset_observation.metadata[SILVER_SCOPE_KEY].value
        for r in rows
        if r.asset_observation
    ]
    assert len(scopes) == 1 and scopes[0]["phase"] == "planned"
    assert not silver_completion_consumed(
        flow.instance,
        reference,
        PERIODS["week"],
        root=flow.market.root,
        business_date=D,
    )
    waiting = silver_request(flow, "week")
    assert not waiting.run_requests and waiting.skip_message.startswith(
        "silver_run_requires_review:"
    )
    success = run_request(flow, request, "silver_rerun", automatic=False)
    assert len(records(flow, success)) == 10
    assert silver_completion_consumed(
        flow.instance,
        reference,
        PERIODS["week"],
        root=flow.market.root,
        business_date=D,
    )
    assert silver_request(flow, "week").skip_message == "silver_batch_complete"
    assert "pending" not in json.loads(flow.cursors["week"])
    assert len(flow.state["calls"]) == calls
    assert Counter(w["layer"] for w in flow.state["writes"][writes:]) == {"silver": 3}
    assert raw_versions == [
        raw.file_version(raw.target_path(flow.market.root, "week", p))
        for p in PERIODS["week"]
    ]
    assert_repaired_files(flow, {"week": PERIODS["week"]}, ("silver",))


@pytest.mark.parametrize("freq", ["week", "month"])
@pytest.mark.parametrize("coverage", ["missing", "stale", "ready"])
def test_closed_period_union_and_last_required_date(
    market, monkeypatch, freq, coverage
):
    """A last-day suspension cannot erase an earlier required period member."""
    started = time.monotonic()
    business_date = "2026-10-30"
    period, label = (
        ("2026-10-30", "20261030") if freq == "week" else ("2026-10", "20261031")
    )
    with raw.connection(market.tmp / "closed_facts") as con:
        life = paths.silver_stock_lifecycle_path(market.root)
        identity = paths.silver_stock_identity_map_path(market.root)
        # The base fixture's November retirement is still listed in October.
        # Explicitly narrow this scenario's reference facts, retaining types.
        con.execute(
            "CREATE TEMP TABLE closed_life AS SELECT * FROM read_parquet(?) "
            "WHERE ts_code IN ('000001.SZ','000002.SZ','000003.SZ')",
            [str(life)],
        )
        con.execute(
            "CREATE TEMP TABLE closed_identity AS SELECT * FROM read_parquet(?) "
            "WHERE source_ts_code IN ('000001.SZ','000002.SZ','000003.SZ')",
            [str(identity)],
        )
        raw.execute(con, "COPY closed_life TO ? (FORMAT PARQUET)", [str(life)])
        raw.execute(con, "COPY closed_identity TO ? (FORMAT PARQUET)", [str(identity)])
        raw.execute(
            con,
            "COPY (SELECT 'SSE' exchange,d::DATE trade_date,true is_open,NULL::DATE pretrade_date "
            "FROM (VALUES ('2026-10-29'),('2026-10-30')) v(d)) TO ? (FORMAT PARQUET)",
            [str(paths.silver_trade_calendar_path(market.root))],
        )
        for day in ("2026-10-29", business_date):
            suspension = paths.silver_stock_suspend_daily_path(market.root, day)
            suspension.parent.mkdir(parents=True, exist_ok=True)
            if day == business_date:
                sql = (
                    "COPY (SELECT * FROM (VALUES ('000002.SZ',DATE '2026-10-30','S',NULL::VARCHAR),"
                    "('000003.SZ',DATE '2026-10-30','S','10:00-10:30')) "
                    "v(ts_code,trade_date,suspend_type,suspend_timing)) TO ? (FORMAT PARQUET)"
                )
            else:
                sql = (
                    "COPY (SELECT NULL::VARCHAR ts_code,DATE '2026-10-29' trade_date,"
                    "NULL::VARCHAR suspend_type,NULL::VARCHAR suspend_timing WHERE false) TO ? (FORMAT PARQUET)"
                )
            raw.execute(con, sql, [str(suspension)])
    calls = []

    class Wire:
        def __init__(self, **kwargs):
            pass

        def __call__(self, params):
            assert params == {
                "freq": freq,
                "trade_date": label,
                "limit": 6000,
                "offset": 0,
            }
            rows = [
                literal_row(A, label, freq, asof="20261110", qfq="5"),
                literal_row(I, label, freq, asof="20261030", qfq="8"),
            ]
            if coverage != "missing":
                rows.append(
                    literal_row(
                        S,
                        label,
                        freq,
                        asof="20261028" if coverage == "stale" else "20261029",
                        qfq="4",
                    )
                )
            calls.append(
                {"params": dict(params), "rows": len(rows), "fields": list(FIELDS)}
            )
            return json.dumps(
                {"code": 0, "data": {"fields": list(FIELDS), "items": rows}}
            ).encode()

    monkeypatch.setattr(stock_period_source, "HttpPage", Wire)
    stage_seconds = {"prepare_extension": time.monotonic() - started}
    with dg.DagsterInstance.local_temp(
        str(market.tmp / "instance"), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        instance.add_dynamic_partitions(
            "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months", [period]
        )
        flow = NS(
            market=market,
            instance=instance,
            defs=market.defs,
            cursors={},
            state={"now": datetime.fromisoformat("2026-11-10T20:00:00+08:00")},
        )
        asset = "raw_tushare_stk_period_bar_adj_" + freq
        config = StockPeriodRawConfig(
            intent="closed_period", automatic_intent_date=business_date
        )
        raw_started = time.monotonic()
        result = market.defs.resolve_job_def(
            "raw_stk_period_bar_adj_" + freq + "_update_job"
        ).execute_in_process(
            instance=instance,
            partition_key=period,
            run_config={"ops": {asset: {"config": config.model_dump()}}},
            raise_on_error=False,
        )
        stage_seconds["raw_job"] = time.monotonic() - raw_started
        audit_started = time.monotonic()
        rows_by_layer = {}
        assert len(calls) == 1 and calls[0]["rows"] == (
            2 if coverage == "missing" else 3
        )
        if coverage != "ready":
            assert_failed_without_delivery(flow, result, work_count=1)
            assert "period_source_incomplete" in str(
                result.get_step_failure_events()[0].event_specific_data.error
            )
            assert not raw.target_path(market.root, freq, period).exists()
            assert not target_path(market.root, freq, period).exists()
        else:
            assert result.success and len(result.get_asset_check_evaluations()) == 3
            completion = next(
                r.asset_observation.metadata[COMPLETION_KEY].value
                for r in records(flow, result)
                if r.asset_observation
                and COMPLETION_KEY in r.asset_observation.metadata
            )
            reference = {
                k: completion[k]
                for k in ("producer_run_id", "freq", "upstream_batch_id")
            }
            origin = read_completions(instance, [reference], root=market.root)[
                reference["upstream_batch_id"]
            ]
            assert origin["asof"] == business_date
            assert origin["items"][(freq, period)]["source_asof"] == D
            assert origin["items"][(freq, period)]["asof"] == D
            assert isinstance(callback(flow, history_sensor, result), dg.SkipReason)
            assert isinstance(callback(flow, retirement_sensor, result), dg.SkipReason)
            response = silver_request(flow, freq)
            assert len(response.run_requests) == 1
            request = response.run_requests[0]
            stage_seconds["raw_reference_and_silver_request"] = (
                time.monotonic() - audit_started
            )
            silver_started = time.monotonic()
            silver = market.defs.resolve_job_def(request.job_name).execute_in_process(
                instance=instance,
                partition_key=request.partition_key,
                run_config=request.run_config,
                tags={**request.tags, "dagster/run_key": request.run_key},
            )
            stage_seconds["silver_job"] = time.monotonic() - silver_started
            audit_started = time.monotonic()
            assert silver.success and len(silver.get_asset_check_evaluations()) == 3
            assert silver_completion_consumed(
                instance,
                reference,
                [period],
                root=market.root,
                business_date=business_date,
            )
            assert silver_request(flow, freq).skip_message == "silver_batch_complete"
            expected = [
                (A, label, freq, Decimal(5), "20261110"),
                (S, label, freq, Decimal(4), "20261029"),
                (I, label, freq, Decimal(8), "20261030"),
            ]
            for layer in ("raw", "silver"):
                rows = read_rows(flow, layer, freq, period)
                assert rows == sorted(expected)
                rows_by_layer[layer] = len(rows)
            assert len(calls) == 1
        stage_seconds["final_audit"] = time.monotonic() - audit_started
        targets = {
            "raw": raw.target_path(market.root, freq, period),
            "silver": target_path(market.root, freq, period),
        }
        source_dir = market.staging / "stock_period" / "runs" / result.run_id / "source"
        print(
            "STOCK_PERIOD_CLOSED "
            + json.dumps(
                {
                    "freq": freq,
                    "coverage": coverage,
                    "source_calls": calls,
                    "seconds": time.monotonic() - started,
                    "stage_seconds": stage_seconds,
                    "target_files": sum(p.is_file() for p in targets.values()),
                    "target_bytes": {
                        layer: p.stat().st_size if p.is_file() else 0
                        for layer, p in targets.items()
                    },
                    "source_persisted_bytes": sum(
                        p.stat().st_size for p in source_dir.rglob("*") if p.is_file()
                    ),
                    "final_rows_by_layer": rows_by_layer,
                    "process_peak_rss_bytes": resource.getrusage(
                        resource.RUSAGE_SELF
                    ).ru_maxrss
                    * (1 if sys.platform == "darwin" else 1024),
                    "spill_residual_bytes": sum(
                        p.stat().st_size
                        for p in market.staging.rglob("*")
                        if p.is_file() and "spill" in p.parts
                    ),
                }
            )
        )
