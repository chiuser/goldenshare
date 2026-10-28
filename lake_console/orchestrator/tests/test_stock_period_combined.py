"""Combined period/history candidates, exact old-range reuse and logical intent recovery."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap.stock_period_history import run_period
from orchestrator.defs.io.stock_period_raw import (
    PeriodCancelled,
    connection,
    file_version,
    read_json,
    target_path,
)
from orchestrator.defs.run_contracts.stock_period import (
    FIELDS,
    VERSION,
    StockPeriodPolicy,
    execution_id,
)

A, B = "000001.SZ", "000002.SZ"
POLICY = StockPeriodPolicy(
    duckdb_memory="256MiB", spill_bytes=128 * 1024**2, workspace_bytes=1024**3
)


def row(code, day, freq="week", value="1.0000"):
    return [code, day, "20261016", freq] + [value] * 17


def wire(rows):
    return json.dumps(
        {"code": 0, "data": {"fields": list(FIELDS), "items": rows}}
    ).encode()


def bootstrap(tmp_path):
    kw = {
        "root": tmp_path / "lake",
        "staging": tmp_path / "staging",
        "listed": {A, B},
        "aliases": {},
        "policy": POLICY,
    }

    def initial(params):
        dates = (
            ["20261002", "20261009", "20261016"]
            if params["freq"] == "week"
            else ["20260930", "20261031"]
        )
        return wire(
            [
                row(
                    params["ts_code"],
                    d,
                    params["freq"],
                    "1" if params["ts_code"] == A else "9",
                )
                for d in dates
            ]
        )

    run_period(
        **kw,
        intent={
            "version": VERSION,
            "mode": "bootstrap",
            "frequencies": ["week", "month"],
            "codes": [A, B],
            "request_id": "bootstrap",
        },
        transport=initial,
        events=lambda _, completion=None: None,
        completion_events=lambda _: 1,
    )
    baseline = kw["staging"] / "stock_period/baseline.json"
    facts = read_json(baseline)
    facts["status"] = (
        "ready"  # Synthetic downstream fixture, not bootstrap handoff evidence.
    )
    baseline.write_text(json.dumps(facts))
    return kw


def values(root, period, freq="week"):
    with connection(root / "readback", POLICY) as con:
        return con.execute(
            "SELECT ts_code,trade_date,close FROM read_parquet(?,hive_partitioning=false) ORDER BY 1,2",
            [str(target_path(root, freq, period))],
        ).fetchall()


def combined_intent(request_id="combined"):
    return {
        "version": VERSION,
        "mode": "upsert",
        "frequencies": ["week"],
        "codes": [A],
        "periods": {"week": ["2026-10-16"]},
        "request_id": request_id,
        "asof": "2026-10-16",
    }


def combined_source(params):
    return (
        wire([row(A, "20261009", value="2"), row(A, "20261016", value="3")])
        if "ts_code" in params
        else wire([row(A, "20261016", value="3"), row(B, "20261016", value="8")])
    )


def test_period_and_history_are_one_copy_and_exact_full_row_dedup(
    tmp_path, monkeypatch
):
    import orchestrator.defs.io.stock_period_raw as raw

    kw = bootstrap(tmp_path)
    month = target_path(kw["root"], "month", "2026-10")
    before = file_version(month)
    stages = []
    real = raw.execute

    def tracked(*args, **kwargs):
        stages.append(kwargs.get("stage"))
        return real(*args, **kwargs)

    monkeypatch.setattr(raw, "execute", tracked)
    result = run_period(**kw, intent=combined_intent(), transport=combined_source)
    assert len(result["files"]) == 3
    assert values(kw["root"], "2026-10-02") == [(B, "20261002", Decimal(9))]
    assert values(kw["root"], "2026-10-09") == [
        (A, "20261009", Decimal(2)),
        (B, "20261009", Decimal(9)),
    ]
    assert values(kw["root"], "2026-10-16") == [
        (A, "20261016", Decimal(3)),
        (B, "20261016", Decimal(8)),
    ]
    assert file_version(month) == before
    for stage in (
        "import_source",
        "partition_copy",
        "read_affected_once",
        "candidate_schemas",
        "candidate_facts",
    ):
        assert stages.count(stage) == 1, (stage, stages)
    assert "locate_old_keys" not in stages  # Bootstrap's exact ranges are valid.
    assert len({i["target"] for i in result["files"]}) == len(result["files"])


@pytest.mark.parametrize("difference", ["price", "null", "end_date", "removed_key"])
def test_conflicting_snapshots_refuse_before_any_file_changes(tmp_path, difference):
    kw = bootstrap(tmp_path)
    targets = list(kw["root"].glob("raw/tushare/*/*/*.parquet"))
    before = {str(p): file_version(p) for p in targets}

    def conflict(params):
        if "ts_code" in params:
            return combined_source(params)
        changed = row(A, "20261016", value="3")
        if difference == "price":
            changed[7] = "4"
        elif difference == "null":
            changed[9] = None
        elif difference == "end_date":
            changed[2] = "20261015"
        else:
            changed[1] = "20261002"
        return wire([changed, row(B, changed[1], value="8")])

    if difference == "removed_key":
        # This is a selected period key absent from the complete history snapshot.
        intent = combined_intent()
        intent["periods"] = {"week": ["2026-10-02"]}
    else:
        intent = combined_intent()
    with pytest.raises(ValueError, match="conflict"):
        run_period(**kw, intent=intent, transport=conflict)
    assert {str(p): file_version(p) for p in targets} == before
    assert list(kw["staging"].glob("stock_period/runs/*/build/week/conflict.json"))


@pytest.mark.parametrize("drift", ["index", "file"])
def test_range_record_drift_falls_back_once_and_is_not_reblessed(
    tmp_path, monkeypatch, drift
):
    import orchestrator.defs.io.stock_period_raw as raw

    kw = bootstrap(tmp_path)
    baseline = kw["staging"] / "stock_period/baseline.json"
    facts = read_json(baseline)
    if drift == "index":
        facts["stock_ranges"]["week"][A] = [["2026-10-16", "2026-10-16"]]
        baseline.write_text(json.dumps(facts))  # Hash no longer proves this index.
    else:
        import os

        old = target_path(kw["root"], "week", "2026-10-02")
        stamp = old.stat()
        os.utime(old, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
    stages = []
    real = raw.execute

    def tracked(*args, **kwargs):
        stages.append(kwargs.get("stage"))
        return real(*args, **kwargs)

    monkeypatch.setattr(raw, "execute", tracked)
    before = {
        str(path): file_version(path)
        for path in kw["root"].glob("raw/tushare/*/*/*.parquet")
    }
    if drift == "file":
        # The old test only covered range-cache fallback and incorrectly allowed
        # an unregistered file version to become a new publish preimage.
        # LLD 12.6 now requires independent ownership before candidate COPY.
        with pytest.raises(ValueError, match="period_target_unregistered_version"):
            run_period(**kw, intent=combined_intent(), transport=combined_source)
        assert before == {path: file_version(path) for path in before}
        assert "partition_copy" not in stages
        assert "locate_old_keys" not in stages
        assert "read_affected_once" not in stages
        assert read_json(baseline) == facts
        return
    with pytest.raises(ValueError, match="period_history_range_unverified"):
        run_period(**kw, intent=combined_intent(), transport=combined_source)
    assert not {"locate_old_keys", "read_affected_once", "partition_copy"} & set(stages)
    assert before == {path: file_version(path) for path in before}
    assert read_json(baseline) == facts


def test_candidate_missing_row_refuses_before_publication(tmp_path, monkeypatch):
    import orchestrator.defs.io.stock_period_raw as raw

    kw = bootstrap(tmp_path)
    before = {
        str(p): file_version(p) for p in kw["root"].glob("raw/tushare/*/*/*.parquet")
    }
    real = raw.execute

    def drop_one_row(con, sql, parameters=None, **kwargs):
        result = real(con, sql, parameters, **kwargs)
        if kwargs.get("stage") == "partition_copy":
            output = Path(parameters[-1]) / "period=2026-10-16/data_0.parquet"
            con.execute(
                "CREATE TEMP TABLE damaged AS SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE ts_code<>?",
                [str(output), B],
            )
            con.execute("COPY damaged TO ? (FORMAT PARQUET)", [str(output)])
        return result

    monkeypatch.setattr(raw, "execute", drop_one_row)
    with pytest.raises(ValueError, match="row_reconciliation_failed"):
        run_period(**kw, intent=combined_intent(), transport=combined_source)
    assert {str(p): file_version(p) for p in map(Path, before)} == before


def test_new_manual_refresh_really_downloads_and_reused_identity_cannot_change_scope(
    tmp_path,
):
    kw = bootstrap(tmp_path)
    calls = []
    intent = {
        "version": VERSION,
        "mode": "history",
        "frequencies": ["week"],
        "codes": [A],
        "request_id": "refresh-1",
    }

    def transport(params):
        calls.append(params)
        return wire([row(A, "20261016", value=str(len(calls) + 1))])

    first = run_period(**kw, intent=intent, transport=transport)
    resumed = run_period(
        **kw, intent=intent, transport=lambda _: pytest.fail("repeat request")
    )
    assert resumed["run_id"] == first["run_id"]
    with pytest.raises(ValueError, match="period_original_run_required"):
        run_period(**kw, intent={**intent, "request_id": "refresh-2"}, transport=transport)
    import dagster as dg

    from orchestrator.defs.bootstrap.stock_period_history import replay_events
    from orchestrator.defs.stock_period_update import confirm_period_delivery
    from tests.test_stock_period_delivery_confirmation import _emit

    isolated = tmp_path / "event-instance"
    isolated.mkdir()
    (isolated / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    with dg.DagsterInstance.local_temp(str(isolated)) as instance:
        _emit(instance, first)
        replay_events(
            Path(first["path"]), root=kw["root"], staging=kw["staging"],
            confirm_delivery=lambda run: confirm_period_delivery(
                instance, run, root=kw["root"], staging=kw["staging"]
            ),
        )
    second = run_period(
        **kw, intent={**intent, "request_id": "refresh-2"}, transport=transport
    )
    assert second["run_id"] != first["run_id"] and len(calls) == 2
    assert values(kw["root"], "2026-10-16") == [
        (A, "20261016", Decimal(3)),
        (B, "20261016", Decimal(9)),
    ]
    with pytest.raises(ValueError, match="manifest_changed"):
        run_period(
            **kw,
            intent={**intent, "codes": [B]},
            transport=lambda _: pytest.fail("changed identity requested"),
        )


def test_cross_day_resume_keeps_original_intent_and_completed_source(tmp_path):
    kw = bootstrap(tmp_path)
    calls = []
    cancelled = False
    intent = {
        "version": VERSION,
        "mode": "history",
        "frequencies": ["week", "month"],
        "codes": [A],
        "request_id": "history-cross-midnight",
        "asof": "2026-10-15",
    }

    def transport(params):
        calls.append(params["freq"])
        return wire(
            [
                row(
                    A,
                    "20261016" if params["freq"] == "week" else "20261031",
                    params["freq"],
                    "2",
                )
            ]
        )

    def progress(event):
        nonlocal cancelled
        if event["stage"] == "source_unit_complete":
            cancelled = True

    with pytest.raises(PeriodCancelled):
        run_period(
            **kw,
            intent=intent,
            transport=transport,
            cancel=lambda: cancelled,
            progress=progress,
        )
    # Resume may run on a later date: the immutable logical input is still the original one.
    result = run_period(**kw, intent=intent, transport=transport)
    assert calls == ["week", "month"]
    assert (
        read_json(Path(result["path"]) / "manifest.json")["identity"]["intent"]["asof"]
        == "2026-10-15"
    )
    with pytest.raises(ValueError, match="manifest_changed"):
        run_period(
            **kw,
            intent={**intent, "asof": "2026-10-16"},
            transport=lambda _: pytest.fail("mutated original requested"),
        )


def test_real_daily_execution_plans_period_and_factor_history_before_one_publication(
    tmp_path, monkeypatch
):
    import orchestrator.defs.bootstrap.stock_period_history as coordinator
    import orchestrator.defs.io.stock_period_raw as raw
    from orchestrator.defs.io.stock_period_raw import atomic_json
    from orchestrator.defs.paths import (
        silver_adj_factor_path,
        silver_trade_calendar_path,
    )
    from orchestrator.defs.stock_period_update import execute_daily

    kw = bootstrap(tmp_path)
    with connection(tmp_path / "fixtures", POLICY) as con:
        cal = silver_trade_calendar_path(kw["root"])
        cal.parent.mkdir(parents=True, exist_ok=True)
        # Matches SILVER_TRADE_CALENDAR_SCHEMA, not the Raw trade_cal response.
        con.sql(
            "SELECT 'SSE' exchange,unnest(['2026-10-12','2026-10-13','2026-10-14',"
            "'2026-10-15','2026-10-16'])::DATE trade_date,true is_open,NULL::DATE pretrade_date"
        ).write_parquet(str(cal))
        for day, factor in (("2026-10-15", 1), ("2026-10-16", 2)):
            p = silver_adj_factor_path(kw["root"], day)
            p.parent.mkdir(parents=True, exist_ok=True)
            con.sql(
                "SELECT '000001.SZ' ts_code,?::DOUBLE adj_factor UNION ALL SELECT '000002.SZ',1",
                params=[factor],
            ).write_parquet(str(p))
    atomic_json(
        kw["staging"] / "stock_period/daily.json",
        {
            "completed_through": {"week": "2026-10-09", "month": "2026-09"},
            "last_refresh": {},
            "factor_through": "2026-10-15",
        },
    )
    calls = []
    stages = []
    real = raw.execute
    units = []
    original = coordinator.run_period

    def run(**args):
        units.append(args["intent"])
        # Keep this integration test on its isolated, small compute policy.
        args["policy"] = POLICY
        return original(**args)

    monkeypatch.setattr(coordinator, "run_period", run)

    def tracked(*args, **kwargs):
        stages.append(kwargs.get("stage"))
        return real(*args, **kwargs)

    monkeypatch.setattr(raw, "execute", tracked)

    def transport(params):
        calls.append(params)
        if params["freq"] == "month":
            return wire(
                [row(A, "20260930", "month", "2"), row(A, "20261031", "month", "3")]
            )
        return combined_source(params)

    result = execute_daily(
        root=kw["root"],
        staging=kw["staging"],
        listed=kw["listed"],
        aliases={},
        today=date(2026, 10, 16),
        freq="week",
        transport=transport,
    )
    assert len(units) == 1 and units[0]["codes"] == [A]
    assert units[0]["periods"] == {"week": ["2026-10-16"]}
    assert (
        len(calls) == 3
        and stages.count("partition_copy") == 2
        and stages.count("import_source") == 2
    )
    targets = [i["target"] for r in result for i in r["files"]]
    assert len(targets) == len(set(targets))
    assert values(kw["root"], "2026-10-02") == [(B, "20261002", Decimal(9))]
    assert values(kw["root"], "2026-10-16") == [
        (A, "20261016", Decimal(3)),
        (B, "20261016", Decimal(8)),
    ]
    assert values(kw["root"], "2026-10", "month") == [
        (A, "20261031", Decimal(3)),
        (B, "20261031", Decimal(9)),
    ]


def test_cli_resume_completed_files_requires_events_without_new_source(
    tmp_path, monkeypatch
):
    from orchestrator.defs.bootstrap import stock_period_history_cli as cli

    kw = bootstrap(tmp_path)
    intent = {
        "version": VERSION,
        "mode": "history",
        "frequencies": ["week"],
        "codes": [A],
        "request_id": "cli-history",
    }
    result = run_period(
        **kw, intent=intent, transport=lambda _: wire([row(A, "20261016", value="2")])
    )
    before = {i["target"]: file_version(i["target"]) for i in result["files"]}
    # LLD 12.5: the pure file action cannot claim DG delivery is complete.
    # The real immutable identity/policy above remains the events input.
    monkeypatch.setattr(
        cli, "load_scope", lambda *a, **kw: pytest.fail("resume refreshed frozen scope")
    )
    monkeypatch.setattr(
        cli, "run_period", lambda **kw: pytest.fail("completed file stage rerun")
    )
    with pytest.raises(ValueError, match="period_delivery_events_required"):
        cli.main(
            [
                "resume",
                "--lake-root",
                str(kw["root"]),
                "--staging-root",
                str(kw["staging"]),
                "--run-id",
                result["run_id"],
            ]
        )
    assert {p: file_version(p) for p in before} == before


def test_second_frequency_conflict_keeps_first_frequency_unpublished(tmp_path):
    kw = bootstrap(tmp_path)
    targets = list(kw["root"].glob("raw/tushare/*/*/*.parquet"))
    before = {str(p): file_version(p) for p in targets}
    intent = combined_intent()
    intent["frequencies"] = ["week", "month"]
    intent["periods"]["month"] = ["2026-10"]

    def source(params):
        if params["freq"] == "week":
            return combined_source(params)
        return wire([row(A, "20261031", "month", "2" if "ts_code" in params else "3")])

    with pytest.raises(ValueError, match="source_conflicting_key"):
        run_period(**kw, intent=intent, transport=source)
    assert {str(p): file_version(p) for p in targets} == before
    assert not (
        kw["staging"]
        / "stock_period/runs"
        / execution_id(intent["request_id"])
        / "committed"
    ).exists()


def test_event_reader_checks_same_v2_identity_without_real_events(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from orchestrator.defs.ops import stock_weekly_bootstrap_checks as consumer
    from orchestrator.defs.run_contracts.configs import (
        StockWeeklyBootstrapEventChecksConfig,
    )

    kw = bootstrap(tmp_path)
    run_id = execution_id("bootstrap")
    # Force the new notification boundary instead of inheriting the bootstrap
    # fixture's mocked completion receipts. This op must never notify month.
    for freq in ("week", "month"):
        (
            kw["staging"]
            / "stock_period/runs"
            / run_id
            / "events/completion"
            / (freq + ".json")
        ).unlink()
    monkeypatch.setattr(consumer, "DEFAULT_LAKE_STAGING_ROOT", str(kw["staging"]))
    reported = []
    notifications = []
    monkeypatch.setattr(
        consumer,
        "report_completion_events",
        lambda instance, notice: notifications.append(notice) or 1,
    )
    monkeypatch.setattr(
        consumer,
        "report_file_events",
        lambda instance, item, **kw: reported.append(item),
    )

    def unregistered_delivery(instance, run, **kwargs):
        # This wiring unit test substitutes the event store, not the file
        # producer. It must not claim that the fake observations/checks exist.
        assert kwargs["allowed_frequencies"] == {"week"}
        saved = read_json(run / "manifest.json")
        complete = read_json(run / "complete.json")
        return {
            "run_id": run.name,
            "identity_hash": saved["identity_hash"],
            "file_receipt_hash": saved["file_receipt_hash"],
            "files": complete["files"],
            "events_complete": False,
            "allowed_events_complete": False,
            "historical_only": False,
            "current_files": [item for item in complete["files"] if item["freq"] == "week"],
            "file_evidence": {},
            "completion_evidence": {},
            "allowed_frequencies": ["week"],
            "reason": "missing_events",
        }

    monkeypatch.setattr(consumer, "confirm_period_delivery", unregistered_delivery)
    entry = consumer.report_stock_weekly_bootstrap_checks.compute_fn.decorated_fn
    context = SimpleNamespace(instance=object())
    config = StockWeeklyBootstrapEventChecksConfig(run_id=run_id)
    assert entry(context, config) == {"reported_files": 3}
    assert [n["freq"] for n in notifications] == ["week"]
    assert not (
        kw["staging"] / "stock_period/runs" / run_id / "events/completion/month.json"
    ).exists()
    manifest = kw["staging"] / "stock_period/runs" / run_id / "manifest.json"
    damaged = read_json(manifest)
    damaged["identity"]["listed"] = [B]
    manifest.write_text(json.dumps(damaged))
    with pytest.raises(ValueError, match="manifest_changed"):
        entry(context, config)
    assert len(reported) == 3
