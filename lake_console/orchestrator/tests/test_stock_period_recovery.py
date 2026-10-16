"""Frozen daily work, published-source gates and independent event recovery."""

import json
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from orchestrator.defs.bootstrap.stock_period_history import replay_events, run_period
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts.stock_period import (
    StockPeriodPolicy,
    digest,
)
from orchestrator.defs.stock_period_update import execute_daily, report_file_events
from tests.test_stock_period_combined import (
    POLICY,
    A,
    bootstrap,
    combined_source,
    row,
    wire,
)
from tests.test_stock_period_history import args


def daily_fixture(tmp_path):
    from orchestrator.defs.paths import (
        silver_adj_factor_path,
        silver_trade_calendar_path,
    )

    kw = bootstrap(tmp_path)
    with raw.connection(tmp_path / "fixtures", POLICY) as con:
        calendar = silver_trade_calendar_path(kw["root"])
        calendar.parent.mkdir(parents=True, exist_ok=True)
        con.sql(
            "SELECT DATE '2026-10-01'+i::INTEGER cal_date,'SSE' exchange,CASE WHEN i>=11 AND isodow(DATE '2026-10-01'+i::INTEGER)<=5 THEN 1 ELSE 0 END is_open FROM range(61) t(i)"
        ).write_parquet(str(calendar))
        for day, factor in (
            ("2026-10-14", 1),
            ("2026-10-15", 1),
            ("2026-10-16", 2),
            ("2026-10-19", 2),
        ):
            path = silver_adj_factor_path(kw["root"], day)
            path.parent.mkdir(parents=True, exist_ok=True)
            con.sql(
                "SELECT '000001.SZ' ts_code,?::DOUBLE adj_factor UNION ALL SELECT '000002.SZ',1",
                params=[factor],
            ).write_parquet(str(path))
    raw.atomic_json(
        kw["staging"] / "stock_period/daily.json",
        {
            "completed_through": {"week": "2026-10-09", "month": "2026-09"},
            "last_refresh": {},
            "factor_through": "2026-10-15",
        },
    )
    kw.update(today=date(2026, 10, 16), freq="week")
    return kw


def daily_source(params):
    if params["freq"] == "month":
        return wire(
            [row(A, "20260930", "month", "2"), row(A, "20261031", "month", "3")]
        )
    return combined_source(params)


def test_file_success_consumes_factor_even_when_events_fail(tmp_path, monkeypatch):
    import orchestrator.defs.stock_period_update as update

    kw = daily_fixture(tmp_path)
    calls = []

    def source(params):
        calls.append(params)
        return daily_source(params)

    def fail(item):
        if item["freq"] == "month":
            raise OSError("event_down")
        return True

    with pytest.raises(OSError, match="event_down"):
        execute_daily(**kw, transport=source, events=fail)
    state = raw.read_json(kw["staging"] / "stock_period/daily.json")
    assert (
        state["factor_through"] == "2026-10-16"
        and state["last_refresh"]["week"] == "2026-10-16"
    )
    assert next(iter(state["pending_work"].values()))["consumed"] is True
    versions = {
        str(p): raw.file_version(p)
        for p in kw["root"].glob("raw/tushare/*/*/*.parquet")
    }
    monkeypatch.setattr(
        update,
        "factor_changes",
        lambda *a, **k: pytest.fail("consumed factors rescanned"),
    )
    execute_daily(
        **kw,
        transport=lambda _: pytest.fail("completed source redownloaded"),
        events=lambda _: True,
    )
    assert (
        len(calls) == 3
        and not raw.read_json(kw["staging"] / "stock_period/daily.json")["pending_work"]
    )
    assert {p: raw.file_version(p) for p in versions} == versions


def test_stale_period_is_refetched_without_redownloading_successful_history(tmp_path):
    kw = daily_fixture(tmp_path)
    calls = []
    stale = True

    def source(params):
        calls.append((params["freq"], params.get("ts_code")))
        body = daily_source(params)
        if stale and params["freq"] == "week" and "ts_code" not in params:
            data = json.loads(body)
            for r in data["data"]["items"]:
                r[2] = "20261015"
            return json.dumps(data).encode()
        return body

    before = {
        str(p): raw.file_version(p)
        for p in kw["root"].glob("raw/tushare/*/*/*.parquet")
    }
    with pytest.raises(ValueError, match="not_published"):
        execute_daily(**kw, transport=source)
    state = raw.read_json(kw["staging"] / "stock_period/daily.json")
    assert not state["last_refresh"] and state["factor_through"] == "2026-10-15"
    assert before == {p: raw.file_version(p) for p in before}
    stale = False
    execute_daily(**kw, transport=source)
    assert calls.count(("week", A)) == 1 and calls.count(("week", None)) == 2
    assert calls.count(("month", A)) == 1
    assert (
        raw.read_json(kw["staging"] / "stock_period/daily.json")["last_refresh"]["week"]
        == "2026-10-16"
    )
    assert (
        len(list(kw["staging"].glob("stock_period/runs/*/source/*/complete.json"))) >= 4
    )


def test_state_failure_after_files_recovers_without_source_or_rewrite(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    import orchestrator.defs.stock_period_update as update

    kw = daily_fixture(tmp_path)
    write = update.atomic_json
    failed = False

    def failure(path, payload):
        nonlocal failed
        if (
            Path(path).name == "daily.json"
            and not failed
            and any(v.get("consumed") for v in payload.get("pending_work", {}).values())
        ):
            failed = True
            raise OSError("state_down")
        return write(path, payload)

    monkeypatch.setattr(update, "atomic_json", failure)
    with pytest.raises(OSError, match="state_down"):
        execute_daily(**kw, transport=daily_source)
    versions = {
        str(p): raw.file_version(p)
        for p in kw["root"].glob("raw/tushare/*/*/*.parquet")
    }
    monkeypatch.setattr(update, "atomic_json", write)
    observed_policy = []
    calendar = update.calendar_days

    def read_calendar(root, work, policy):
        observed_policy.append(policy)
        return calendar(root, work, policy)

    monkeypatch.setattr(update, "calendar_days", read_calendar)
    execute_daily(
        **{**kw, "policy": replace(POLICY, duckdb_threads=1)},
        transport=lambda _: pytest.fail("source re-requested"),
        events=lambda _: True,
    )
    assert versions == {p: raw.file_version(p) for p in versions}
    assert observed_policy == [POLICY]
    assert (
        raw.read_json(kw["staging"] / "stock_period/daily.json")["factor_through"]
        == "2026-10-16"
    )


def test_event_only_retry_does_no_sql_and_none_callback_cannot_mark_success(
    tmp_path, monkeypatch
):
    kw = args(tmp_path)
    result = run_period(**kw, events=lambda _: None)
    run = Path(result["path"])
    assert raw.read_json(run / "manifest.json")["phase"] == "files_complete"
    assert not list((run / "events").glob("*/*.json"))
    monkeypatch.setattr(
        raw, "execute", lambda *a, **k: pytest.fail("event reader recalculated Parquet")
    )
    assert replay_events(
        run, root=kw["root"], staging=kw["staging"], events=lambda _: True
    )["events_complete"]
    assert (
        raw.read_json(kw["staging"] / "stock_period/baseline.json")["status"]
        == "files_ready"
    )
    complete = raw.read_json(run / "complete.json")
    complete["files"][0]["rows"] += 1
    (run / "complete.json").write_text(json.dumps(complete))
    with pytest.raises(ValueError, match="complete_receipt"):
        replay_events(
            run, root=kw["root"], staging=kw["staging"], events=lambda _: True
        )


def test_real_event_reader_matches_partition_and_target_materialization(tmp_path):
    import dagster as dg

    kw = args(tmp_path)

    def source(params):
        return (
            wire([row(A, "20261009"), row(A, "20261016")])
            if params["freq"] == "week"
            else wire([row(A, "20261031", "month")])
        )

    result = run_period(**{**kw, "transport": source})
    items = [i for i in result["files"] if i["freq"] == "week"]
    (tmp_path / "instance").mkdir()
    (tmp_path / "instance/dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    with dg.DagsterInstance.local_temp(str(tmp_path / "instance")) as instance:
        from orchestrator.defs.bootstrap.stock_period_history_cli import _run_reporting

        def report(context):
            return [
                report_file_events(instance, item, context=context) for item in items
            ]

        assert _run_reporting(instance, report) == [True, True]
        assert report_file_events(instance, items[0], write=False) is True
        asset = dg.AssetKey("raw_tushare_stk_period_bar_adj_week")
        old = instance.fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=asset, asset_partitions=[items[0]["period"]]
            ),
            limit=1,
        ).records[0]
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=asset,
                partition=items[0]["period"],
                metadata=old.asset_materialization.metadata,
            )
        )
        assert report_file_events(instance, items[0], write=False) is False
        assert _run_reporting(instance, report) == [True, True]
        assert report_file_events(instance, items[0], write=False) is True
        from dagster._core.event_api import PartitionKeyFilter

        from orchestrator.defs.run_contracts.stock_weekly import (
            StockWeeklySource,
            weekly_check_names,
        )

        name = weekly_check_names(StockWeeklySource.PRIMARY_ADJUSTED)[0]
        history = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(asset, name),
            limit=10,
            partition_filter=PartitionKeyFilter(key=items[0]["period"]),
        )
        assert len(history) == 2
        assert len({h.run_id for h in history}) == 2
        assert all(instance.get_run_by_id(h.run_id).is_success for h in history)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("planned_only", False),
        ("planned_over_success", True),
        ("latest_failed", False),
        ("wrong_binding", False),
        ("nonblocking", False),
    ],
)
def test_event_reader_ignores_plans_but_keeps_latest_completed_failure(
    tmp_path, case, expected
):
    import dagster as dg
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationPlanned,
        AssetCheckEvaluationTargetMaterializationData,
    )
    from dagster._core.events import DagsterEvent, DagsterEventType

    from orchestrator.defs.bootstrap.stock_period_history_cli import _run_reporting
    from orchestrator.defs.partitions import cn_a_stock_week_ends
    from orchestrator.defs.run_contracts.stock_weekly import (
        StockWeeklySource,
        weekly_check_names,
    )

    kw = args(tmp_path)
    result = run_period(**kw)
    item = next(i for i in result["files"] if i["freq"] == "week")
    asset = dg.AssetKey("raw_tushare_stk_period_bar_adj_week")
    name = weekly_check_names(StockWeeklySource.PRIMARY_ADJUSTED)[0]
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    (instance_dir / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    with dg.DagsterInstance.local_temp(str(instance_dir)) as instance:
        if case == "planned_only":
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=asset,
                    partition=item["period"],
                    metadata={
                        "goldenshare/period_file_version": dg.MetadataValue.json(
                            item["version"]
                        )
                    },
                )
            )
        else:
            assert (
                _run_reporting(
                    instance,
                    lambda ctx: report_file_events(instance, item, context=ctx),
                )
                is True
            )

        def emit(context, payload, kind):
            instance.report_dagster_event(
                DagsterEvent(
                    event_type_value=kind.value,
                    job_name=context.job_name,
                    step_key=context.get_step_execution_context().step.key,
                    event_specific_data=payload,
                ),
                run_id=context.run_id,
            )

        if case in {"latest_failed", "wrong_binding", "nonblocking"}:
            record = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=asset,
                    asset_partitions=[item["period"]],
                ),
                limit=1,
            ).records[0]
            evaluation = AssetCheckEvaluation(
                asset_key=asset,
                check_name=name,
                partition=item["period"],
                passed=case != "latest_failed",
                blocking=case != "nonblocking",
                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                    storage_id=record.storage_id + (case == "wrong_binding"),
                    run_id=record.event_log_entry.run_id,
                    timestamp=record.event_log_entry.timestamp,
                ),
            )
            _run_reporting(
                instance,
                lambda ctx: emit(
                    ctx, evaluation, DagsterEventType.ASSET_CHECK_EVALUATION
                ),
            )
        planned = AssetCheckEvaluationPlanned(
            asset_key=asset,
            check_name=name,
            partitions_subset=cn_a_stock_week_ends.subset_with_partition_keys(
                [item["period"]]
            ),
        )
        _run_reporting(
            instance,
            lambda ctx: emit(
                ctx, planned, DagsterEventType.ASSET_CHECK_EVALUATION_PLANNED
            ),
        )
        before = raw.file_version(item["target"])
        assert report_file_events(instance, item, write=False) is expected
        assert raw.file_version(item["target"]) == before


def test_unfinished_page_chain_crossing_date_restarts_only_that_unit(tmp_path):
    from orchestrator.defs.io.stock_period_raw import PeriodCancelled
    from orchestrator.defs.stock_period_source import capture_unit

    calls = []
    cancelled = False

    def source(params):
        calls.append(params["offset"])
        return wire([row(A, "20261016")]) if params["offset"] == 0 else wire([])

    def progress(_):
        nonlocal cancelled
        cancelled = True

    kw = {
        "work": tmp_path,
        "request_id": "partial",
        "freq": "week",
        "code": A,
        "listed": {A},
        "aliases": {},
        "policy": StockPeriodPolicy(page_limit=1),
        "transport": source,
    }
    with pytest.raises(PeriodCancelled):
        capture_unit(**kw, cancel=lambda: cancelled, progress=progress)
    receipt = next(tmp_path.glob("*/*.receipt.json"))
    page = raw.read_json(receipt)
    page["captured_at_ns"] = time.time_ns() - 2 * 86400 * 10**9
    page["receipt_hash"] = digest(
        {k: v for k, v in page.items() if k != "receipt_hash"}
    )
    raw.atomic_json(receipt, page)
    preserved = {
        str(p): p.read_bytes() for p in receipt.parent.glob("*") if p.is_file()
    }
    capture_unit(**kw)
    assert calls == [0, 0, 1]
    assert all(Path(p).read_bytes() == payload for p, payload in preserved.items())
    assert list(tmp_path.glob("*/chains/*/complete.json"))


def test_cancellation_observation_is_throttled_without_changing_local_checks(
    tmp_path, monkeypatch
):
    import orchestrator.defs.bootstrap.stock_period_history as history
    from orchestrator.defs.run_contracts.configs import StockPeriodRawConfig
    from orchestrator.defs.stock_period_update import deliver_asset

    observed = []
    monkeypatch.setattr(history, "load_scope", lambda *a, **k: ({A}, {}))

    def run(**kw):
        for _ in range(1000):
            assert not kw["cancel"]()
        return {
            "files": [
                {
                    "freq": "week",
                    "period": "2026-10-16",
                    "target": str(tmp_path / "fixture.parquet"),
                    "rows": 1,
                    "version": [1, 2, 3, 4, 5],
                }
            ]
        }

    monkeypatch.setattr(history, "run_period", run)
    context = NS(
        instance=NS(get_run_by_id=lambda rid: observed.append(rid) or None),
        run=NS(run_id="isolated-run"),
        partition_key="2026-10-16",
        log=NS(info=lambda _: None),
    )
    deliver_asset(
        context,
        StockPeriodRawConfig(intent="history", stock_codes=[A], request_id="cancel"),
        NS(root=lambda: tmp_path / "lake", ensure_available_for_run=lambda: None),
        "week",
    )
    assert len(observed) == 1
