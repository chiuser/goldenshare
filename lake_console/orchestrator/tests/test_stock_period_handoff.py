"""Bounded bootstrap handoff on actual capture dates; no historical asof minimum."""

from datetime import date, datetime
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts.stock_period import VERSION
from orchestrator.defs.stock_period_update import handoff_bootstrap
from tests.test_stock_period_combined import POLICY, A, B, row, wire
from tests.test_stock_period_recovery import daily_fixture, daily_source


def captured(tmp_path, monkeypatch):
    kw = daily_fixture(tmp_path)
    # The independent fixture supplies only upstream calendar/factors. The new
    # baseline below is built by the real delete/capture/file/event phases.
    monkeypatch.setattr(history, "execution_time", lambda: "2026-10-15T10:00:00+08:00")
    request = {
        "version": VERSION,
        "mode": "bootstrap",
        "frequencies": ["week", "month"],
        "codes": [A, B],
        "request_id": "capture-for-handoff",
    }
    calls = []

    def source(params):
        calls.append(params)
        value = row(
            params["ts_code"],
            "20261016" if params["freq"] == "week" else "20261031",
            params["freq"],
            "1",
        )
        if params["ts_code"] == B:
            value[2] = (
                "20100104"  # An unchanged/suspended source must not create years of debt.
            )
        else:
            value[2] = "20261014"
        return wire([value])

    run = history.run_period(
        root=kw["root"],
        staging=kw["staging"],
        listed={A, B},
        aliases={},
        intent=request,
        transport=source,
        policy=POLICY,
        events=lambda _, completion=None: True,
        completion_events=lambda _: 1,
    )
    assert (
        raw.read_json(kw["staging"] / "stock_period/baseline.json")["status"]
        == "files_ready"
    )
    return kw, Path(run["path"]), calls


def options(kw, run):
    return {
        "root": kw["root"],
        "staging": kw["staging"],
        "run": run,
        "listed": {A, B},
        "aliases": {},
        "through": date(2026, 10, 16),
        "now": datetime.fromisoformat("2026-10-16T20:00:00+08:00"),
    }


def test_handoff_requests_only_elapsed_periods_and_changed_stock(tmp_path, monkeypatch):
    kw, run, initial = captured(tmp_path, monkeypatch)
    calls = []

    def source(params):
        calls.append(params)
        if params["freq"] == "month":
            return (
                wire(
                    [row(A, "20261031", "month", "3"), row(B, "20261031", "month", "9")]
                )
                if "ts_code" not in params
                else wire([row(A, "20261031", "month", "3")])
            )
        return daily_source(params)

    state = handoff_bootstrap(
        **options(kw, run),
        transport=source,
        events=lambda _, completion=None: True,
        completion_events=lambda _: 1,
    )
    assert len(initial) == 4 and len(calls) == 4
    assert len([p for p in calls if p.get("ts_code") == A]) == 2
    assert not any(p.get("ts_code") == B for p in calls)
    assert {
        p.get("trade_date") for p in calls if p["freq"] == "week" and "ts_code" not in p
    } == {"20261016"}
    assert {
        p.get("start_date")
        for p in calls
        if p["freq"] == "month" and "ts_code" not in p
    } == {"20261001"}
    assert state["factor_through"] == "2026-10-16" and state["completed_through"] == {
        "week": "2026-10-16",
        "month": "2026-09",
    }
    assert (
        raw.read_json(kw["staging"] / "stock_period/baseline.json")["status"] == "ready"
    )
    before = raw.read_json(kw["staging"] / "stock_period/daily.json")
    before["last_refresh"]["week"] = "2026-10-19"
    raw.atomic_json(kw["staging"] / "stock_period/daily.json", before)
    again = handoff_bootstrap(
        **options(kw, run),
        transport=lambda _: pytest.fail("successful handoff repeated"),
        events=lambda _, completion=None: pytest.fail("events repeated"),
        completion_events=lambda _: 1,
    )
    assert again["last_refresh"]["week"] == "2026-10-19"


def test_handoff_stale_input_or_event_failure_keeps_not_ready(tmp_path, monkeypatch):
    kw, run, _ = captured(tmp_path, monkeypatch)
    calls = []
    fresh = False

    def source(params):
        calls.append(params)
        if params["freq"] == "month":
            rows = [row(A, "20261031", "month", "3")]
        else:
            rows = [row(A, "20261016", value="3")]
        if not fresh and "ts_code" not in params:
            rows[0][2] = "20261015"
        return wire(rows)

    with pytest.raises(ValueError, match="not_published"):
        handoff_bootstrap(
            **options(kw, run),
            transport=source,
            events=lambda _, completion=None: True,
            completion_events=lambda _: 1,
        )
    assert (
        raw.read_json(kw["staging"] / "stock_period/baseline.json")["status"]
        == "files_ready"
    )
    fresh = True

    def failure(_, *, completion=None):
        raise OSError("event_unavailable")

    with pytest.raises(OSError, match="event_unavailable"):
        handoff_bootstrap(
            **options(kw, run),
            transport=source,
            events=failure,
            completion_events=lambda _: 1,
        )
    assert (
        raw.read_json(kw["staging"] / "stock_period/baseline.json")["status"]
        == "files_ready"
    )
    count = len(calls)
    monkeypatch.setattr(
        raw, "execute", lambda *a, **k: pytest.fail("event retry recomputed")
    )
    result = handoff_bootstrap(
        **options(kw, run),
        transport=lambda _: pytest.fail("source repeated"),
        events=lambda _, completion=None: True,
        completion_events=lambda _: 1,
    )
    assert result["handoff_cutoff"] == "2026-10-16" and len(calls) == count


def test_handoff_freezes_scope_and_cutoff_after_first_plan(tmp_path, monkeypatch):
    kw, run, _ = captured(tmp_path, monkeypatch)

    def failed(_):
        raise TimeoutError("source unavailable")

    with pytest.raises(TimeoutError):
        handoff_bootstrap(
            **options(kw, run),
            transport=failed,
            events=lambda _, completion=None: True,
            completion_events=lambda _: 1,
        )
    original = raw.read_json(run / "manifest.json")["handoff"]
    changed = options(kw, run)
    changed.update(
        listed={A},
        aliases={"old.BJ": "920000.BJ"},
        now=datetime.fromisoformat("2026-10-19T20:00:00+08:00"),
        through=date(2026, 10, 19),
    )
    with pytest.raises(TimeoutError):
        handoff_bootstrap(
            **changed,
            transport=failed,
            events=lambda _, completion=None: True,
            completion_events=lambda _: 1,
        )
    assert raw.read_json(run / "manifest.json")["handoff"] == original


def test_unconfirmed_scope_difference_or_unreleased_cutoff_refuses(
    tmp_path, monkeypatch
):
    kw, run, _ = captured(tmp_path, monkeypatch)
    selected = options(kw, run)
    selected["through"] = date(2026, 10, 19)
    with pytest.raises(ValueError, match="cutoff_not_released"):
        handoff_bootstrap(
            **selected,
            transport=lambda _: pytest.fail("unexpected request"),
            events=lambda _, completion=None: True,
            completion_events=lambda _: 1,
        )
    monkeypatch.setattr(
        "orchestrator.defs.stock_period_update.confirmed_retirements",
        lambda *a, **k: [],
    )
    selected = options(kw, run)
    selected["listed"] = {A}
    with pytest.raises(ValueError, match="difference_unconfirmed"):
        handoff_bootstrap(
            **selected,
            transport=lambda _: pytest.fail("unexpected request"),
            events=lambda _, completion=None: True,
            completion_events=lambda _: 1,
        )
    assert (
        raw.read_json(kw["staging"] / "stock_period/baseline.json")["status"]
        == "files_ready"
    )


def test_handoff_one_scope_difference_adds_new_stock_and_prunes_confirmed_delisting(
    tmp_path, monkeypatch
):
    from orchestrator.defs.paths import raw_stock_basic_path

    kw, run, _ = captured(tmp_path, monkeypatch)
    newcomer = "000003.SZ"
    with raw.connection(tmp_path / "retirement-fixture", POLICY) as con:
        basic = raw_stock_basic_path(kw["root"])
        basic.parent.mkdir(parents=True, exist_ok=True)
        con.sql("SELECT '000002.SZ' ts_code,'D' list_status").write_parquet(str(basic))
    calls = []

    def source(params):
        calls.append(params)
        frequency = params["freq"]
        day = "20261016" if frequency == "week" else "20261031"
        if "ts_code" in params:
            code = params["ts_code"]
            return wire([row(code, day, frequency, "3" if code == A else "7")])
        # A delisted row in a market response is excluded, never a planned stock request.
        return wire(
            [
                row(A, day, frequency, "3"),
                row(newcomer, day, frequency, "7"),
                row(B, day, frequency, "9"),
            ]
        )

    selected = options(kw, run)
    selected["listed"] = {A, newcomer}
    state = handoff_bootstrap(
        **selected,
        transport=source,
        events=lambda _, completion=None: True,
        completion_events=lambda _: 1,
    )
    assert state["handoff_cutoff"] == "2026-10-16"
    assert len(calls) == 6 and not any(p.get("ts_code") == B for p in calls)
    with raw.connection(tmp_path / "readback", POLICY) as con:
        rows = con.execute(
            "SELECT DISTINCT ts_code FROM read_parquet(?,hive_partitioning=false)",
            [
                [
                    str(p)
                    for p in kw["root"].glob(
                        "raw/tushare/stk_period_bar_adj_*/*/*.parquet"
                    )
                ]
            ],
        ).fetchall()
    assert {r[0] for r in rows} == {A, newcomer}
    assert raw.read_json(kw["staging"] / "stock_period/baseline.json")[
        "listed"
    ] == sorted([A, newcomer])


def test_handoff_cancel_preserves_capture_and_resume_never_deletes(
    tmp_path, monkeypatch
):
    kw, run, _ = captured(tmp_path, monkeypatch)
    calls = []
    interrupted = False

    def source(params):
        calls.append(params)
        if params["freq"] == "month":
            return wire([row(A, "20261031", "month", "3")])
        return daily_source(params)

    def progress(event):
        nonlocal interrupted
        if event["stage"] == "source_unit_complete":
            interrupted = True

    monkeypatch.setattr(
        history, "remove_dataset", lambda *a: pytest.fail("handoff deleted root")
    )
    before = {
        str(p): raw.file_version(p)
        for p in kw["root"].glob("raw/tushare/stk_period_bar_adj_*/*/*.parquet")
    }
    with pytest.raises(raw.PeriodCancelled):
        handoff_bootstrap(
            **options(kw, run),
            transport=source,
            events=lambda _, completion=None: True,
            completion_events=lambda _: 1,
            cancel=lambda: interrupted,
            progress=progress,
        )
    assert before == {p: raw.file_version(p) for p in before}
    assert (
        raw.read_json(kw["staging"] / "stock_period/baseline.json")["status"]
        == "files_ready"
    )
    state = handoff_bootstrap(
        **options(kw, run),
        transport=source,
        events=lambda _, completion=None: True,
        completion_events=lambda _: 1,
    )
    assert state["handoff_cutoff"] == "2026-10-16"
    assert len(calls) == 4  # The completed first unit is reused after cancellation.
