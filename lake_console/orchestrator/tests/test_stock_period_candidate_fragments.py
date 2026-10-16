"""Literal doc365/schema gold cases; fragment injection is explicitly unit-level.

The separate parallel COPY test runs the real assemble producer with two threads.
No test accesses Tushare, the formal instance, Lake or external staging.
"""

import json
import os
import threading
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap.stock_period_history import writer
from orchestrator.defs.io import stock_period_raw as raw
from tests.test_stock_period_raw import POLICY

# Independent field order/types: doc365 and stock_weekly.weekly_column_specs.
NAMES = (
    "ts_code",
    "trade_date",
    "end_date",
    "freq",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "open_qfq",
    "high_qfq",
    "low_qfq",
    "close_qfq",
    "open_hfq",
    "high_hfq",
    "low_hfq",
    "close_hfq",
    "vol",
    "amount",
    "change",
    "pct_chg",
)
SCHEMA = ",".join(
    f'"{name}" {"VARCHAR" if i < 4 else "DECIMAL(20,4)" if name in ("vol", "amount") else "DECIMAL(10,4)" if name == "pct_chg" else "DECIMAL(18,4)"}'
    for i, name in enumerate(NAMES)
)


def literal(code, freq="week", day=None):
    day = day or ("19901221" if freq == "week" else "20200229")
    numbers = [Decimal("1.2500")] * 17
    numbers[1], numbers[5], numbers[-1] = None, Decimal("0.5000"), Decimal("-0.1250")
    return (code, day, "20261015", freq, *numbers)


def write_fragment(con, path, rows, *, projection="*"):
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute("DROP TABLE IF EXISTS fragment")
    con.execute(f"CREATE TEMP TABLE fragment ({SCHEMA})")
    for row in rows:  # At most four literal rows; never a bulk data writer.
        con.execute("INSERT INTO fragment VALUES (" + ",".join(["?"] * 21) + ")", row)
    con.execute(
        f"COPY (SELECT {projection} FROM fragment) TO ? (FORMAT PARQUET)", [str(path)]
    )


def fixture(con, tmp_path, freq="week", *, single=False):
    work, root = tmp_path / "build", tmp_path / "lake"
    period = "1990-12-21" if freq == "week" else "2020-02"
    rows = [
        literal(c, freq) for c in ("600601.SH", "600602.SH", "600651.SH", "600654.SH")
    ]
    directory = work / "outputs" / f"period={period}"
    write_fragment(con, directory / "data_0.parquet", rows if single else rows[:1])
    if not single:
        write_fragment(con, directory / "data_1.parquet", rows[1:])
    raw.atomic_json(
        work / "copy.json",
        {"expected_rows": {period: 4}, "target_preimages": {period: None}},
    )
    return work, root, period, rows


def receipts(con, work, root, period, freq="week", **kw):
    return raw._candidate_receipts(
        con,
        [period],
        work,
        root,
        freq,
        kw.pop("cancel", lambda: False),
        kw.pop("progress", lambda _: None),
        kw.pop("policy", POLICY),
    )


def read_rows(con, path):
    return con.execute(
        "SELECT * FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code,trade_date",
        [str(path)],
    ).fetchall()


@pytest.mark.parametrize("freq", ["week", "month"])
def test_all_fragment_rows_become_one_formal_file(tmp_path, freq):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, rows = fixture(con, tmp_path, freq)
        originals = {
            str(p): raw.file_version(p) for p in work.glob("outputs/*/*.parquet")
        }
        item = receipts(con, work, root, period, freq)[0]
        assert item["rows"] == 4
        assert read_rows(con, item["candidate"]) == rows
        raw.publish(item, checkpoint=tmp_path / "committed.json")
        target = Path(item["target"])
        assert read_rows(con, target) == rows
        assert list(target.parent.glob("*.parquet")) == [target]
        assert {p: raw.file_version(p) for p in originals} == originals


def test_row_mismatch_cannot_leave_success_checkpoint(tmp_path):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, _ = fixture(con, tmp_path, single=True)
        copied = raw.read_json(work / "copy.json")
        copied["expected_rows"][period] = 5
        raw.atomic_json(work / "copy.json", copied)
        with pytest.raises(ValueError, match="row_reconciliation"):
            receipts(con, work, root, period)
        cp = work / "validated" / f"{period}.json"
        assert not cp.exists() or "item" not in raw.read_json(cp)


def test_real_parallel_partition_copy_is_accepted(tmp_path, monkeypatch):
    # Match the formal producer's approved 3GiB/two-thread configuration.
    policy = replace(POLICY, duckdb_memory="3GiB", duckdb_threads=2)
    source = tmp_path / "source.csv"
    real_connection = raw.connection

    @contextmanager
    def flushing_connection(work, settings):
        with real_connection(work, settings) as con:
            # Fixture-only stress: trigger real DuckDB buffered partition flushes
            # with 30k rows instead of repeatedly building millions of rows.
            # Production keeps flush=524288/open-files=100, 3GiB and threads=2.
            con.execute("SET partitioned_write_flush_threshold=2048")
            con.execute("SET partitioned_write_max_open_files=1")
            yield con

    monkeypatch.setattr(raw, "connection", flushing_connection)
    execute = raw.execute
    calls, rss = Counter(), []

    def observe(*args, **kw):
        calls[kw.get("stage", "sql")] += 1
        result = execute(*args, **kw)
        rss.append(raw.current_rss_bytes())
        return result

    monkeypatch.setattr(raw, "execute", observe)
    with raw.connection(tmp_path / "source-db", policy) as con:
        expressions = [
            "lpad(i::VARCHAR,6,'0')||'.SH'",
            "strftime(date '1990-12-21'+((i%2)*7)::INTEGER,'%Y%m%d')",
            "'20261015'",
            "'week'",
        ] + ["1.25"] * 17
        con.execute(
            "COPY (SELECT "
            + ",".join(f'{v} AS "{n}"' for n, v in zip(NAMES, expressions, strict=True))
            + " FROM range(30000) t(i)) TO ? (HEADER)",
            [str(source)],
        )
    work = tmp_path / "build"
    started = time.monotonic()
    items = raw.assemble(
        [source],
        work=work,
        root=tmp_path / "lake",
        mode="bootstrap",
        freq="week",
        policy=policy,
    )
    elapsed = time.monotonic() - started
    fragments = list(work.glob("outputs/period=1990-12-21/*.parquet"))
    assert len(fragments) > 1  # Actual producer fact, not an assumption about threads.
    assert len(items) == 2 and [i["rows"] for i in items] == [15000, 15000]
    first_calls = dict(calls)
    versions = {i["candidate"]: raw.file_version(i["candidate"]) for i in items}
    calls.clear()
    started = time.monotonic()
    assert (
        raw.assemble(
            [source],
            work=work,
            root=tmp_path / "lake",
            mode="bootstrap",
            freq="week",
            policy=policy,
        )
        == items
    )
    resumed = time.monotonic() - started
    assert not calls
    assert {p: raw.file_version(p) for p in versions} == versions
    with raw.connection(tmp_path / "read", policy) as con:
        for item in items:
            assert con.execute(
                "SELECT count(*),count(DISTINCT ts_code) FROM read_parquet(?)",
                [item["candidate"]],
            ).fetchone() == (15000, 15000)
    all_fragments = list(work.glob("outputs/*/*.parquet"))
    (tmp_path / "performance.json").write_text(
        json.dumps(
            {
                "rows": 30000,
                "periods": 2,
                "fragments": len(all_fragments),
                "fragment_bytes": sum(p.stat().st_size for p in all_fragments),
                "candidate_bytes": sum(Path(p).stat().st_size for p in versions),
                "source_bytes": source.stat().st_size,
                "assembly_seconds": elapsed,
                "resume_seconds": resumed,
                "sql_counts": first_calls,
                "observed_rss_bytes": max(rss),
                "resume_sql_counts": dict(calls),
                "fixture_flush_threshold": 2048,
                "fixture_open_files": 1,
            },
            indent=2,
        )
    )


@pytest.mark.parametrize("single", [True, False])
def test_complete_candidates_reuse_without_queries_or_hashing(
    tmp_path, monkeypatch, single
):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, _ = fixture(con, tmp_path, single=single)
        first = receipts(con, work, root, period)
        version = raw.file_version(first[0]["candidate"])
        monkeypatch.setattr(
            raw,
            "execute",
            lambda *a, **k: pytest.fail("completed candidate queried again"),
        )
        monkeypatch.setattr(
            raw,
            "file_digest",
            lambda *a: pytest.fail("completed candidate hashed again"),
        )
        assert receipts(con, work, root, period) == first
        assert raw.file_version(first[0]["candidate"]) == version
        assert first[0]["candidate"].endswith("data_0.parquet") == single


@pytest.mark.parametrize(
    "projection",
    [
        "* EXCLUDE(high)",
        "*,1 AS unexpected",
        "* REPLACE (CAST(open AS DOUBLE) AS open)",
    ],
)
def test_input_schema_cannot_be_hidden_by_merge(tmp_path, projection):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, rows = fixture(con, tmp_path)
        write_fragment(
            con,
            work / "outputs" / f"period={period}" / "data_0.parquet",
            rows[:1],
            projection=projection,
        )
        with pytest.raises((ValueError, duckdb.Error)):
            receipts(con, work, root, period)
        assert "item" not in raw.read_json(work / "validated" / f"{period}.json")
        assert not raw.target_path(root, "week", period).exists()


@pytest.mark.parametrize(
    "kind",
    ["same-key", "different-value", "freq", "date", "period", "missing-fragment"],
)
def test_real_bad_fragment_facts_are_rejected(tmp_path, kind):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, rows = fixture(con, tmp_path)
        path = work / "outputs" / f"period={period}" / "data_1.parquet"
        bad = list(rows[1:])
        if kind in ("same-key", "different-value"):
            bad[0] = (
                rows[0]
                if kind == "same-key"
                else (*rows[0][:4], Decimal(99), *rows[0][5:])
            )
        elif kind in ("freq", "date", "period"):
            changed = list(bad[0])
            changed[{"freq": 3, "date": 1, "period": 1}[kind]] = {
                "freq": "month",
                "date": "19901321",
                "period": "19901228",
            }[kind]
            bad[0] = tuple(changed)
        if kind == "missing-fragment":
            path.unlink()  # Intentional isolated corruption, never a formal target.
        else:
            write_fragment(con, path, bad)
        with pytest.raises((ValueError, duckdb.Error)):
            receipts(con, work, root, period)
        cp = work / "validated" / f"{period}.json"
        assert not cp.exists() or "item" not in raw.read_json(cp)


def test_month_preserves_two_dates_for_same_stock(tmp_path):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, rows = fixture(con, tmp_path, "month")
        rows[1] = literal("600601.SH", "month", "20200228")
        write_fragment(
            con, work / "outputs" / f"period={period}" / "data_1.parquet", rows[1:]
        )
        item = receipts(con, work, root, period, "month")[0]
        assert read_rows(con, item["candidate"]) == sorted(
            rows, key=lambda r: (r[0], r[1])
        )


@pytest.mark.parametrize("kind", ["add", "remove", "touch", "candidate", "checkpoint"])
def test_completed_proof_detects_drift(tmp_path, kind):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, _ = fixture(con, tmp_path)
        item = receipts(con, work, root, period)[0]
        directory = work / "outputs" / f"period={period}"
        if kind == "add":
            write_fragment(con, directory / "extra.parquet", [])
        elif kind == "remove":
            (directory / "data_1.parquet").unlink()
        elif kind in ("touch", "candidate"):
            path = (
                directory / "data_1.parquet"
                if kind == "touch"
                else Path(item["candidate"])
            )
            stamp = path.stat()
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
        else:
            cp = work / "validated" / f"{period}.json"
            cp.write_text(cp.read_text().replace('"validated"', '"bogus"'))
        with pytest.raises(ValueError, match="fragments_changed|candidate_changed"):
            receipts(con, work, root, period)
        assert not Path(item["target"]).exists()


@pytest.mark.parametrize("stage", ["before", "candidate_merged"])
def test_cancel_boundaries_release_lock_and_reuse_completed_work(
    tmp_path, monkeypatch, stage
):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, _ = fixture(con, tmp_path)
        cancelled = stage == "before"

        def progress(event):
            nonlocal cancelled
            if event["stage"] == stage:
                cancelled = True

        with pytest.raises(raw.PeriodCancelled), writer(tmp_path / "staging"):
            receipts(
                con, work, root, period, cancel=lambda: cancelled, progress=progress
            )
        copied = (work / "copy.json").read_bytes()
        calls = Counter()
        execute = raw.execute

        def observed(*a, **kw):
            calls[kw.get("stage")] += 1
            return execute(*a, **kw)

        monkeypatch.setattr(raw, "execute", observed)
        with writer(tmp_path / "staging"):
            item = receipts(con, work, root, period)[0]
        assert item["rows"] == 4
        assert calls["candidate_merge"] == (1 if stage == "before" else 0)
        assert calls["candidate_schemas"] == 1
        assert (work / "copy.json").read_bytes() == copied


def test_cancel_after_partial_validation_checks_only_remaining_file(
    tmp_path, monkeypatch
):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, _ = fixture(con, tmp_path)
        next_period = "1990-12-28"
        write_fragment(
            con,
            work / "outputs" / f"period={next_period}" / "data_0.parquet",
            [literal("600601.SH", day="19901228")],
        )
        copied = raw.read_json(work / "copy.json")
        copied["expected_rows"][next_period] = 1
        copied["target_preimages"][next_period] = None
        raw.atomic_json(work / "copy.json", copied)
        cancelled = False

        def progress(event):
            nonlocal cancelled
            if event["stage"] == "candidate_validated":
                cancelled = True

        with pytest.raises(raw.PeriodCancelled), writer(tmp_path / "staging"):
            raw._candidate_receipts(
                con,
                [period, next_period],
                work,
                root,
                "week",
                lambda: cancelled,
                progress,
                POLICY,
            )
        checked = raw.read_json(work / "validated" / f"{period}.json")["item"]
        assert not (work / "validated" / f"{next_period}.json").exists()
        calls = []
        execute = raw.execute

        def observe(*args, **kw):
            calls.append((kw.get("stage"), args[2] if len(args) > 2 else None))
            return execute(*args, **kw)

        monkeypatch.setattr(raw, "execute", observe)
        with writer(tmp_path / "staging"):
            items = raw._candidate_receipts(
                con,
                [period, next_period],
                work,
                root,
                "week",
                lambda: False,
                lambda _: None,
                POLICY,
            )
        assert items[0] == checked
        assert [stage for stage, _ in calls] == ["candidate_schemas", "candidate_facts"]
        assert all(checked["candidate"] not in str(params) for _, params in calls)


@pytest.mark.parametrize("corrupt", [False, True])
def test_rename_record_gap_reconciles_only_that_partition(
    tmp_path, monkeypatch, corrupt
):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, rows = fixture(con, tmp_path)
        save = raw._save_fragment_proof

        def fail_record(path, proof):
            if proof["phase"] == "merged":
                raise OSError("isolated_record_failure")
            return save(path, proof)

        monkeypatch.setattr(raw, "_save_fragment_proof", fail_record)
        with pytest.raises(OSError, match="isolated_record_failure"):
            receipts(con, work, root, period)
        candidate = work / "merged" / f"{period}.parquet"
        assert candidate.exists()
        version = raw.file_version(candidate)
        monkeypatch.setattr(raw, "_save_fragment_proof", save)
        if corrupt:
            write_fragment(con, candidate, rows[:1])
            with pytest.raises(ValueError, match="unowned_merged"):
                receipts(con, work, root, period)
        else:
            calls = []
            execute = raw.execute

            def observe(*a, **kw):
                calls.append(kw.get("stage"))
                return execute(*a, **kw)

            monkeypatch.setattr(raw, "execute", observe)
            assert receipts(con, work, root, period)[0]["rows"] == 4
            assert calls.count("candidate_merge_recovery") == 1
            assert "candidate_merge" not in calls
            assert raw.file_version(candidate) == version


def test_unknown_merged_output_is_not_overwritten(tmp_path):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, rows = fixture(con, tmp_path)
        out = work / "merged" / f"{period}.parquet"
        write_fragment(con, out, rows)
        version = raw.file_version(out)
        with pytest.raises(ValueError, match="unowned_merged"):
            receipts(con, work, root, period)
        assert raw.file_version(out) == version


def test_real_sql_cancel_waits_for_writer_thread(tmp_path):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, _ = fixture(con, tmp_path)
        started = threading.Event()
        threads = []

        class SlowCopy:
            def execute(self, sql, parameters):
                if sql.startswith("COPY "):
                    threads.append(threading.current_thread())
                    # Stress only this isolated COPY; real DuckDB interrupt below.
                    sql = sql.replace(
                        "FROM read_parquet",
                        "FROM range(1000000000) stress CROSS JOIN read_parquet",
                    )
                    started.set()
                return con.execute(sql, parameters)

            def interrupt(self):
                con.interrupt()

        with pytest.raises(raw.PeriodCancelled), writer(tmp_path / "staging"):
            receipts(SlowCopy(), work, root, period, cancel=started.is_set)
        assert threads and all(not t.is_alive() for t in threads)
        assert not (work / "merged" / f"{period}.parquet").exists()
        with writer(tmp_path / "staging"):
            assert receipts(con, work, root, period)[0]["rows"] == 4


@pytest.mark.parametrize("kind", ["workspace", "free", "rss", "symlink"])
def test_merge_retains_resource_and_path_guards(tmp_path, monkeypatch, kind):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, _ = fixture(con, tmp_path)
        policy = POLICY
        if kind == "workspace":
            policy = replace(POLICY, workspace_bytes=POLICY.spill_bytes + 18000)
        budget = raw.StorageBudget(work, policy)
        if kind == "free":
            monkeypatch.setattr(
                raw.shutil, "disk_usage", lambda _: type("Usage", (), {"free": 0})()
            )
        elif kind == "rss":
            monkeypatch.setattr(raw, "current_rss_bytes", lambda: 5 * 1024**3)
        elif kind == "symlink":
            (work / "merged").symlink_to(tmp_path / "outside", target_is_directory=True)
        token = raw._BUDGET.set(budget)
        try:
            with raw.process_memory_budget(
                policy, 6 * 1024**3 if kind == "rss" else None
            ):
                if kind == "rss":
                    monkeypatch.setattr(raw, "current_rss_bytes", lambda: 7 * 1024**3)
                with pytest.raises(
                    ValueError,
                    match={
                        "rss": "memory_exceeded",
                        "workspace": "workspace_budget",
                        "free": "free_space",
                        "symlink": "symlink_forbidden",
                    }[kind],
                ):
                    receipts(con, work, root, period, policy=policy)
        finally:
            raw._BUDGET.reset(token)
        assert not raw.target_path(root, "week", period).exists()


@pytest.mark.parametrize("files_present", [True, False])
def test_expected_empty_candidate_requires_actual_file(tmp_path, files_present):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, _ = fixture(con, tmp_path)
        directory = work / "outputs" / f"period={period}"
        for path in directory.glob("*.parquet"):
            if files_present:
                write_fragment(con, path, [])
            else:
                path.unlink()  # Deliberately missing isolated producer output.
        copied = raw.read_json(work / "copy.json")
        copied["expected_rows"][period] = 0
        raw.atomic_json(work / "copy.json", copied)
        if files_present:
            item = receipts(con, work, root, period)[0]
            assert item["rows"] == 0 and read_rows(con, item["candidate"]) == []
        else:
            with pytest.raises(ValueError, match="file_count_invalid"):
                receipts(con, work, root, period)


@pytest.mark.parametrize("kind", ["input-changed", "unknown-output-appeared"])
def test_merge_boundary_drift_cannot_be_promoted(tmp_path, monkeypatch, kind):
    with raw.connection(tmp_path / "db", POLICY) as con:
        work, root, period, rows = fixture(con, tmp_path)
        execute = raw.execute
        out = work / "merged" / f"{period}.parquet"
        injected_version = None

        def drift(*args, **kw):
            nonlocal injected_version
            result = execute(*args, **kw)
            if kw.get("stage") == "candidate_merge":
                if kind == "input-changed":
                    path = work / "outputs" / f"period={period}" / "data_0.parquet"
                    stamp = path.stat()
                    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
                else:
                    write_fragment(con, out, rows[:1])
                    injected_version = raw.file_version(out)
            return result

        monkeypatch.setattr(raw, "execute", drift)
        with pytest.raises(ValueError, match="fragments_changed|unowned_merged"):
            receipts(con, work, root, period)
        assert "item" not in raw.read_json(work / "validated" / f"{period}.json")
        if injected_version is not None:
            assert raw.file_version(out) == injected_version
