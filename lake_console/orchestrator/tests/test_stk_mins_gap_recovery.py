"""Isolated acceptance: no formal resources or network calls."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from orchestrator.defs.bootstrap import stk_mins_gap_recovery as core
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_cli import parser
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_raw import (
    build_candidate,
    compact_changed_raw,
    promote_candidate,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_source import (
    SourceCache,
    compact_source_index,
    day_facts,
    expected_clocks,
    write_page,
)
from orchestrator.defs.resources import TushareResource


@pytest.fixture
def root(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("Formal source prohibited")

    monkeypatch.setattr(TushareResource, "call", forbidden)
    with TemporaryDirectory(dir="/private/tmp", prefix="mins-gap-test-") as d:
        yield Path(d)


def bars(code="001872.SZ", day="2014-01-02"):
    return [
        {
            "ts_code": code,
            "freq": "30min",
            "trade_time": day + " " + t,
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "vol": 0,
            "amount": 0.0,
            "exchange": None,
            "vwap": 10.0,
        }
        for t in sorted(expected_clocks(30))
    ]


def plan(root, units=None, seeds=None, mutate=None):
    units = units or [
        ("001872.SZ", "2014-01-02", ["001872.SZ", "000022.SZ"]),
        ("600395.SH", "2014-01-03", ["600395.SH"]),
    ]
    a = root / "audit"
    (a / "reference").mkdir(parents=True)
    rows = [
        {
            "scope_id": f"s{i}",
            "latest_ts_code": code,
            "source_candidates": cs,
            "freq": 30,
            "trade_date": d,
            "evidence": "daily_trading_evidence",
            "unconfirmed": False,
            "gap_kind": "whole_day_missing",
            "expected_grid_count": 9,
            "missing_grid_count": 9,
            "present_grid": None,
        }
        for i, (code, d, cs) in enumerate(units)
    ]
    if mutate:
        mutate(rows)
    core.atomic_json(a / "draft.json", rows)
    core.atomic_json(
        a / "calendar.json",
        [
            {"trade_date": d}
            for d in ["2014-01-02", "2014-01-03", "2014-01-06", "2014-01-07"]
        ],
    )
    core.atomic_json(
        a / "inventory.json",
        [
            {"freq": 30, "trade_date": d, "size_bytes": 1024}
            for d in sorted({r["trade_date"] for r in rows})
        ],
    )
    with core.connection(root) as c:
        core.parquet(
            c,
            f"SELECT * REPLACE(CAST(trade_date AS DATE) AS trade_date,CAST(present_grid AS VARCHAR) AS present_grid) FROM read_json_auto({core.literal(a / 'draft.json')})",
            a / "draft.parquet",
        )
        core.parquet(
            c,
            f"SELECT CAST(trade_date AS DATE) trade_date FROM read_json_auto({core.literal(a / 'calendar.json')})",
            a / "reference/calendar.parquet",
        )
    si = []
    if seeds is not None:
        core.atomic_json(a / "seeds.json", seeds)
        si = [a / "seeds.json"]
    p = core.freeze_plan(
        draft=a / "draft.parquet",
        audit=a,
        output=root / "plan",
        run_root=root / "stage",
        lake_root=root / "lake",
        seed_inputs=si,
    )
    r = core.RecoveryRun(root / "plan/plan.json", p["plan_hash"])
    r.initialize()
    return r


def query(run, name, where=""):
    with run.db() as c:
        return core.records(
            c,
            f"SELECT * FROM read_parquet({core.literal(run.plan_dir / name)}) " + where,
        )


def windows(run):
    return query(run, "source-windows.parquet", "ORDER BY latest_ts_code,start_date")


def scopes(run, w):
    return query(
        run,
        "scope.parquet",
        f"WHERE window_id={core.literal(w['window_id'])} ORDER BY trade_date",
    )


def files(run):
    return query(run, "file-plan.parquet", "ORDER BY trade_date")


class Provider:
    def __init__(self, rows, after=lambda: None):
        self.rows, self.calls, self.after = rows, [], after

    def call(self, api, p, fields):
        assert api == "stk_mins" and tuple(fields) == core.COLUMNS
        self.calls.append(p.copy())
        self.after()
        rows = [
            r
            for r in self.rows
            if r["ts_code"] == p["ts_code"]
            and p["start_date"] <= r["trade_time"] <= p["end_date"]
        ]
        return SimpleNamespace(
            rows=rows[p["offset"] : p["offset"] + p["limit"]], columns=core.COLUMNS
        )


def source(run, p=None, **kw):
    clock = [0.0]

    def advance_clock(seconds):
        clock[0] += seconds

    return SourceCache(run, p, sleep=advance_clock, clock=lambda: clock[0], **kw)


def fill(run, rows):
    s = source(run, Provider(rows))
    for w in windows(run):
        s.resolve_window(w, scopes(run, w))
    compact_source_index(run)
    return s


def existing(run, file, rows=None):
    rows = bars("600000.SH", str(file["trade_date"])) if rows is None else rows
    for row in rows:
        row["freq"] = 30
    path = run.target(30, str(file["trade_date"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = run.root / "fixture.json"
    core.atomic_json(payload, rows)
    schema = (
        "{"
        + ",".join(
            f"{core.literal(k)}:{core.literal(v)}" for k, v in core.TYPES.items()
        )
        + "}"
    )
    with core.connection(run.root, directories=[run.lake]) as c:
        core.parquet(
            c,
            f"SELECT {','.join(core.COLUMNS)} FROM read_json({core.literal(payload)},columns={schema})",
            path,
        )
    return path


def test_freeze_and_hash(root):
    r = plan(root)
    assert r.plan["unit_count"] == 2 and r.plan["file_count"] == 2
    assert windows(r)[0]["candidates"] == ["001872.SZ", "000022.SZ"]
    with pytest.raises(ValueError, match="formal Lake"):
        r.require_operational_roots()
    with pytest.raises(ValueError, match="hash"):
        core.RecoveryRun(r.plan_path, "wrong")
    with (r.plan_dir / "scope.parquet").open("ab") as f:
        f.write(b"changed")
    with pytest.raises(ValueError, match="artifact changed"):
        core.RecoveryRun(r.plan_path, r.hash)


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r[0].update(trade_date="2013-12-31"),
        lambda r: r[0].update(trade_date="2026-09-10"),
        lambda r: r[0].update(freq=90),
        lambda r: r[0].update(missing_grid_count=0),
        lambda r: r[0].update(source_candidates=[]),
        lambda r: r[1].update(
            latest_ts_code=r[0]["latest_ts_code"], trade_date=r[0]["trade_date"]
        ),
        lambda r: r[1].update(
            source_candidates=["000022.SZ"], trade_date=r[0]["trade_date"]
        ),
    ],
)
def test_scope_rejects_invalid(root, change):
    with pytest.raises(ValueError):
        plan(root, mutate=change)


def test_alias_is_new_identity_and_resume_zero_calls(root):
    r = plan(root)
    s = fill(r, bars("000022.SZ") + bars("600395.SH", "2014-01-03"))
    assert [x["ts_code"] for x in s.provider.calls] == [
        "001872.SZ",
        "000022.SZ",
        "600395.SH",
    ]
    second = fill(r, [])
    assert second.provider.calls == []
    with r.db() as c:
        result = c.execute(
            "SELECT latest_ts_code,source_ts_code,status FROM read_parquet(?)",
            [str(r.root / "resolutions" / f"{windows(r)[0]['window_id']}.parquet")],
        ).fetchone()
    assert result == ("001872.SZ", "000022.SZ", "source-ready")


@pytest.mark.parametrize(
    "rows,status", [(bars()[:3], "source-partial"), ([], "source-empty")]
)
def test_partial_empty(root, rows, status):
    r = plan(root, units=[("001872.SZ", "2014-01-02", ["001872.SZ"])])
    fill(r, rows)
    w = windows(r)[0]
    with r.db() as c:
        assert (
            c.execute(
                "SELECT status FROM read_parquet(?)",
                [str(r.root / "resolutions" / f"{w['window_id']}.parquet")],
            ).fetchone()[0]
            == status
        )


def test_failed_request_does_not_fallback_or_infinite_retry(root):
    r = plan(root)

    class Failed:
        def __init__(self):
            self.calls = []

        def call(self, api, p, fields):
            self.calls.append(p["ts_code"])
            raise RuntimeError("SDK failure")

    s = source(r, Failed())
    w = windows(r)[0]
    for _ in range(2):
        with pytest.raises(RuntimeError, match="bounded attempts"):
            s.resolve_window(w, scopes(r, w))
    assert s.provider.calls == ["001872.SZ"] * 3


def test_pagination_cancel_resume(root):
    r = plan(root)
    r.budget = dict(r.budget, page_limit=3)
    flag = [False]
    p = Provider(bars(), after=lambda: flag.__setitem__(0, True))
    s = source(r, p, cancelled=lambda: flag[0])
    with pytest.raises(InterruptedError):
        s.request("001872.SZ", 30, "2014-01-02", "2014-01-02")
    p2 = Provider(bars())
    s = source(r, p2)
    paths = s.request("001872.SZ", 30, "2014-01-02", "2014-01-02")
    assert [x["offset"] for x in p2.calls] == [3, 6, 9]
    assert (
        day_facts(r, paths, "001872.SZ", 30, ["2014-01-02"])["2014-01-02"]["status"]
        == "source-ready"
    )
    s.request("001872.SZ", 30, "2014-01-02", "2014-01-02")
    assert len(p2.calls) == 3


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r[0].update(ts_code="600000.SH"),
        lambda r: r[0].update(freq="5min"),
        lambda r: r[0].update(trade_time="2014-01-03 10:00:00"),
        lambda r: r.append(r[0].copy()),
    ],
)
def test_invalid_page_retained(root, change):
    r = plan(root)
    rows = bars()
    change(rows)
    req = {
        "ts_code": "001872.SZ",
        "freq": "30min",
        "start_date": "2014-01-02 09:00:00",
        "end_date": "2014-01-02 19:00:00",
    }
    with pytest.raises((ValueError, RuntimeError)):
        write_page(r, "invalid", req, rows)
    assert (r.root / "responses/invalid/response.json").exists()


def test_cached_middle_day_splits_requests(root):
    rows = bars(day="2014-01-03")
    seeds = [
        {
            "request": {
                "ts_code": "001872.SZ",
                "freq": "30min",
                "start_date": "2014-01-03 09:00:00",
                "end_date": "2014-01-03 19:00:00",
            },
            "response": {
                "isError": False,
                "content": [{"type": "text", "text": json.dumps(rows)}],
            },
        }
    ]
    units = [
        ("001872.SZ", d, ["001872.SZ"])
        for d in ["2014-01-02", "2014-01-03", "2014-01-06"]
    ]
    r = plan(root, units, seeds)
    p = Provider(bars() + bars(day="2014-01-06"))
    s = source(r, p)
    s.import_seeds()
    w = windows(r)[0]
    s.resolve_window(w, scopes(r, w))
    assert [(x["start_date"][:10], x["end_date"][:10]) for x in p.calls] == [
        ("2014-01-02", "2014-01-02"),
        ("2014-01-06", "2014-01-06"),
    ]
    assert r.state("windows", w["window_id"])["ready"] == 3


def test_exact_pairs_promotion_crash_and_idempotency(root):
    r = plan(root)
    fill(r, bars("000022.SZ") + bars("600395.SH", "2014-01-03"))
    a, b = files(r)
    pa = existing(r, a, bars("600395.SH"))
    pb = existing(r, b, bars("001872.SZ", "2014-01-03"))
    before_a, before_b = pa.read_bytes(), pb.read_bytes()
    state = build_candidate(r, a)
    assert pa.read_bytes() == before_a and pb.read_bytes() == before_b
    assert state["repair_rows"] == 9 and state["validation"]["rows"] == 18
    replace = os.replace

    def crash(src, dst):
        replace(src, dst)
        if Path(dst) == pa:
            raise InterruptedError("process exit after replace")

    with (
        patch(
            "orchestrator.defs.bootstrap.stk_mins_gap_recovery_raw.os.replace",
            side_effect=crash,
        ),
        pytest.raises(InterruptedError),
    ):
        promote_candidate(r, a)
    assert r.state("files", "30_2014-01-02")["status"] == "promoting"
    assert promote_candidate(r, a)["status"] == "promoted"
    with patch(
        "orchestrator.defs.bootstrap.stk_mins_gap_recovery_raw.os.replace",
        side_effect=AssertionError("re-promoted"),
    ):
        promote_candidate(r, a)
    assert pb.read_bytes() == before_b
    compact_changed_raw(r)
    with r.db(files=[pa]) as c:
        assert c.execute(
            "SELECT ts_code,count(*) FROM read_parquet(?,hive_partitioning=false) GROUP BY ts_code ORDER BY ts_code",
            [str(pa)],
        ).fetchall() == [("000022.SZ", 9), ("600395.SH", 9)]
        assert c.execute(
            "SELECT DISTINCT latest_ts_code,source_ts_code FROM read_parquet(?)",
            [str(r.root / "actual-changed-raw.parquet")],
        ).fetchall() == [("001872.SZ", "000022.SZ")]


def test_all_file_members_required(root):
    r = plan(
        root,
        units=[
            ("001872.SZ", "2014-01-02", ["001872.SZ"]),
            ("600395.SH", "2014-01-02", ["600395.SH"]),
        ],
    )
    f = files(r)[0]
    existing(r, f)
    fill(r, bars())
    with pytest.raises(ValueError, match="All file members"):
        build_candidate(r, f)
    with pytest.raises(ValueError, match="No validated"):
        promote_candidate(r, f)


def test_paths_and_explicit_cli(root):
    with pytest.raises(ValueError):
        core.bounded_path(root / "../escape", root)
    (root / "link").symlink_to("/Volumes/datasource/data_lake")
    with pytest.raises(ValueError):
        core.bounded_path(root / "link/part.parquet", root)
    for argv in [
        ["fetch", "--plan", "p", "--plan-hash", "h", "--limit", "20"],
        ["silver", "--plan", "p"],
    ]:
        with pytest.raises(SystemExit):
            parser().parse_args(argv)


def test_cached_alias_conflict_blocks_and_import_resume_does_not_read_rows(root):
    seeds = []
    for code, price in [("001872.SZ", 10.0), ("000022.SZ", 20.0)]:
        rows = bars(code)
        for row in rows:
            row["close"] = price
        seeds.append(
            {
                "request": {
                    "ts_code": code,
                    "freq": "30min",
                    "start_date": "2014-01-02 09:00:00",
                    "end_date": "2014-01-02 19:00:00",
                },
                "response": {
                    "isError": False,
                    "content": [{"type": "text", "text": json.dumps(rows)}],
                },
            }
        )
    r = plan(root, seeds=seeds)
    s = source(r)
    s.import_seeds()
    with patch(
        "orchestrator.defs.bootstrap.stk_mins_gap_recovery_source.day_facts",
        side_effect=AssertionError("repeat seed audit"),
    ):
        s.import_seeds()
    w = windows(r)[0]
    with pytest.raises(ValueError, match="Conflicting cached"):
        s.resolve_window(w, scopes(r, w))


def test_ready_file_is_not_blocked_by_other_day_in_same_window(root):
    from orchestrator.defs.bootstrap.stk_mins_gap_recovery_raw import selected_files

    r = plan(
        root,
        units=[("001872.SZ", d, ["001872.SZ"]) for d in ["2014-01-02", "2014-01-03"]],
    )
    fill(r, bars())
    chosen = selected_files(r, 30, 10)
    assert [str(f["trade_date"]) for f in chosen] == ["2014-01-02"]
    assert selected_files(r, 30, 10, require_candidate=True) == []
    with pytest.raises(ValueError):
        selected_files(r, 30, 21)


@pytest.mark.parametrize("bad_field", ["amount", "vwap"])
def test_non_business_fields_do_not_expand_scope_but_formal_check_still_blocks(
    root, bad_field
):
    r = plan(root)
    fill(r, bars("000022.SZ") + bars("600395.SH", "2014-01-03"))
    f = files(r)[0]
    original = bars("600000.SH")
    original[0][bad_field] = None
    path = existing(r, f, original)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="contract failed"):
        build_candidate(r, f)
    assert path.read_bytes() == before


def test_cancel_before_promote_and_modified_candidate_cannot_promote(root):
    r = plan(root)
    fill(r, bars("000022.SZ") + bars("600395.SH", "2014-01-03"))
    f = files(r)[0]
    path = existing(r, f)
    before = path.read_bytes()
    state = build_candidate(r, f)
    with pytest.raises(InterruptedError):
        promote_candidate(r, f, cancelled=lambda: True)
    assert path.read_bytes() == before
    with Path(state["candidate"]).open("ab") as stream:
        stream.write(b"invalid")
    with pytest.raises(ValueError, match="changed after validation"):
        promote_candidate(r, f)
    assert path.read_bytes() == before


def test_unknown_unit_needs_real_source_before_it_can_be_ready(root):
    r = plan(
        root,
        units=[("001872.SZ", "2014-01-02", ["001872.SZ"])],
        mutate=lambda rows: rows[0].update(
            unconfirmed=True,
            evidence="lifecycle_only_unconfirmed",
            expected_grid_count=None,
            missing_grid_count=None,
        ),
    )
    assert r.plan["counts"][0]["unconfirmed"] == 1
    fill(r, [])
    f = files(r)[0]
    existing(r, f)
    with pytest.raises(ValueError, match="All file members"):
        build_candidate(r, f)


def test_existing_raw_contract_tests_with_all_duckdb_connections_isolated(
    root, monkeypatch
):
    import importlib.util
    import sys
    import unittest

    spec = importlib.util.spec_from_file_location(
        "minute_raw_baseline",
        Path(__file__).with_name("test_stk_mins_raw_m4_contracts.py"),
    )
    baseline = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, baseline)
    spec.loader.exec_module(baseline)

    from orchestrator.defs import resources
    from orchestrator.defs.assets import stk_mins
    from orchestrator.defs.checks import stk_mins_checks

    monkeypatch.setattr(
        baseline, "TemporaryDirectory", lambda: TemporaryDirectory(dir=root)
    )
    for module in (resources, stk_mins, stk_mins_checks):
        monkeypatch.setattr(
            module, "connect_configured_duckdb", lambda: core.connection(root)
        )
    names = [
        "test_tushare_fetch_normalizes_freq_string_and_paginates",
        "test_tushare_merge_repair_replaces_appends_and_preserves_other_rows",
        "test_tushare_merge_repair_rejects_empty_or_out_of_scope_source_rows",
    ]
    result = unittest.TestResult()
    unittest.TestSuite(baseline.StkMinsRawM4ContractTests(n) for n in names).run(result)
    assert result.testsRun == 3
    assert not result.errors and not result.failures, (result.errors, result.failures)


def test_incomplete_window_membership_and_unreviewed_budget_rejected(root):
    r = plan(root)
    w = windows(r)[0]
    with pytest.raises(ValueError, match="complete frozen scope"):
        source(r).resolve_window(w, [])
    changed = json.loads(r.plan_path.read_text())
    changed.pop("plan_hash")
    changed["budget"]["threads"] = 8
    changed["plan_hash"] = core.digest(changed)
    core.atomic_json(r.plan_path, changed)
    with pytest.raises(ValueError, match="Unreviewed budget"):
        core.RecoveryRun(r.plan_path, changed["plan_hash"])


def test_cli_rejects_oversized_batch_and_missing_token_before_execution(
    root, monkeypatch
):
    from orchestrator.defs.bootstrap import stk_mins_gap_recovery_cli as cli

    r = plan(root)
    monkeypatch.setattr(r, "require_operational_roots", lambda: None)
    monkeypatch.setattr(cli, "RecoveryRun", lambda *args: r)
    monkeypatch.setattr(
        r, "initialize", lambda: pytest.fail("Execution started before preflight")
    )
    common = ["--plan", str(r.plan_path), "--plan-hash", r.hash, "--apply"]
    with pytest.raises(ValueError, match="batch exceeds"):
        cli.main(["fetch", *common, "--limit", "201"])
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    with pytest.raises(ValueError, match="TUSHARE_TOKEN"):
        cli.main(["fetch", *common, "--limit", "20"])
