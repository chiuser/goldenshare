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
        events=lambda _: None,
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
    run_period(**kw, intent=combined_intent(), transport=combined_source)
    assert stages.count("locate_old_keys") == 1
    assert values(kw["root"], "2026-10-02") == [(B, "20261002", Decimal(9))]
    assert "range_index_version" not in read_json(baseline)


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
        con.sql(
            "SELECT unnest(['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16'])::DATE cal_date,'SSE' exchange,1 is_open"
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


def test_cli_resume_uses_frozen_identity_and_policy_without_new_source(
    tmp_path, monkeypatch, capsys
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
    monkeypatch.setattr(
        cli, "load_scope", lambda *a, **kw: pytest.fail("resume refreshed frozen scope")
    )
    original = cli.run_period

    def checked(**args):
        assert args["intent"] == intent and args["policy"] == POLICY
        return original(
            **args, transport=lambda _: pytest.fail("CLI resumed source again")
        )

    monkeypatch.setattr(cli, "run_period", checked)
    assert (
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
        == 0
    )
    assert (
        json.loads(capsys.readouterr().out.splitlines()[-1])["run_id"]
        == result["run_id"]
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
    monkeypatch.setattr(consumer, "DEFAULT_LAKE_STAGING_ROOT", str(kw["staging"]))
    reported = []
    monkeypatch.setattr(
        consumer,
        "report_file_events",
        lambda instance, item, **kw: reported.append(item),
    )
    entry = consumer.report_stock_weekly_bootstrap_checks.compute_fn.decorated_fn
    context = SimpleNamespace(instance=object())
    config = StockWeeklyBootstrapEventChecksConfig(run_id=run_id)
    assert entry(context, config) == {"reported_files": 3}
    manifest = kw["staging"] / "stock_period/runs" / run_id / "manifest.json"
    damaged = read_json(manifest)
    damaged["identity"]["listed"] = [B]
    manifest.write_text(json.dumps(damaged))
    with pytest.raises(ValueError, match="manifest_changed"):
        entry(context, config)
    assert len(reported) == 3
