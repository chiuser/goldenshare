import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter

import pytest

from orchestrator.defs.checks import stk_factor_pro as check_module
from orchestrator.defs.checks.stk_factor_pro import (
    audit_stk_factor_pro_file,
    factor_file_sha,
)
from orchestrator.defs.io import stk_factor_pro_publication as publication
from orchestrator.defs.io.stk_factor_pro_candidates import (
    release_stk_factor_pro_day_source,
)
from orchestrator.defs.io.stk_factor_pro_download import download_stk_factor_pro_day
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
)
from tests.stk_factor_pro_test_support import (
    DAY,
    Downloader,
    connection,
    contract,
    identity,
    result,
    row,
)


def roots(tmp_path):
    lake, staging = tmp_path / "lake", tmp_path / "staging"
    lake.mkdir(exist_ok=True)
    staging.mkdir(exist_ok=True)
    return lake, staging


def run_day(conn, lake, staging, rows, run="run-a", check=lambda: None):
    downloader = Downloader(result(rows))
    source = download_stk_factor_pro_day(
        conn,
        identity=identity(run),
        contract=contract(),
        downloader=downloader,
        check_cancel=lambda: None,
    )
    try:
        outputs = list(
            publication.publish_stk_factor_pro_day(
                conn,
                source=source,
                lake_root=lake,
                staging_root=staging,
                check_cancel=check,
            )
        )
        return outputs, downloader
    finally:
        release_stk_factor_pro_day_source(conn)


def test_raw_merge_silver_from_full_raw_and_nullable_negative_values(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        first, _ = run_day(
            conn, lake, staging, (row(), row("600000.SH", close=Decimal(20)))
        )
        assert [r.layer for r, _ in first] == ["raw", "silver"]
        updated, loader = run_day(
            conn,
            lake,
            staging,
            (row(close=Decimal(12)), row("000002.SZ", close=Decimal(30))),
            run="run-b",
        )
        assert len(loader.calls) == 1
        raw, silver = (
            raw_stk_factor_pro_path(lake, DAY.isoformat()),
            silver_stock_factor_pro_path(lake, DAY.isoformat()),
        )
        for path in (raw, silver):
            assert conn.execute(
                "SELECT ts_code,close,macd_bfq,pe FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                [str(path)],
            ).fetchall() == [
                ("000001.SZ", 12.0, -1.25, None),
                ("000002.SZ", 30.0, -1.25, None),
                ("600000.SH", 20.0, -1.25, None),
            ]
        assert tuple(
            (r[0], r[1])
            for r in conn.execute(
                "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                [str(silver)],
            ).fetchall()
        )[:2] == (("ts_code", "VARCHAR"), ("trade_date", "DATE"))
        assert all(audit.row_count == 3 and audit.passed for _, audit in updated)
        assert conn.execute("SHOW TABLES").fetchall() == []
    assert not any("source" in p.relative_to(staging).parts for p in staging.rglob("*"))


def test_empty_initial_no_files_and_empty_later_preserves_old(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        empty, loader = run_day(conn, lake, staging, (), run="empty")
        assert empty == [] and loader.closed
        assert list(lake.rglob("*.parquet")) == [] and list(staging.rglob("*")) == []
        run_day(conn, lake, staging, (row(),), run="has-data")
        old = raw_stk_factor_pro_path(lake, DAY.isoformat())
        sha = factor_file_sha(old)
        outputs, _ = run_day(conn, lake, staging, (), run="empty-with-old")
        assert factor_file_sha(old) == sha and all(a.row_count == 1 for _, a in outputs)
        assert all(
            publication.read_stk_factor_pro_publication_record(
                staging
                / "stk_factor_pro"
                / f"trade_date={DAY}"
                / "run_id=empty-with-old"
                / r.checkpoint_ref.relative_path
            ).mode
            == "reuse"
            for r, _ in outputs
        )


def test_two_rounds_do_not_retain_delivered_unit_references(tmp_path):
    lake, staging = roots(tmp_path)
    value = result((row(),))
    loader = Downloader(value)
    baseline = sys.getrefcount(value)
    with connection(tmp_path) as conn:
        for run in ("first-round", "second-round"):
            source = download_stk_factor_pro_day(
                conn,
                identity=identity(run),
                contract=contract(),
                downloader=loader,
                check_cancel=lambda: None,
            )
            try:
                outputs = list(
                    publication.publish_stk_factor_pro_day(
                        conn,
                        source=source,
                        lake_root=lake,
                        staging_root=staging,
                        check_cancel=lambda: None,
                    )
                )
                assert len(outputs) == 2
            finally:
                release_stk_factor_pro_day_source(conn)
                del source
            assert sys.getrefcount(value) == baseline
            assert conn.execute("SHOW TABLES").fetchall() == []


def test_prior_plan_directory_allowed_but_day_candidates_cannot_resume(tmp_path):
    lake, staging = roots(tmp_path)
    directory = staging / "stk_factor_pro" / f"trade_date={DAY}" / "run_id=run-a"
    directory.mkdir(parents=True)
    plan = directory / "history-plan.json"
    plan.write_text('{"test":"owned by earlier job step"}')
    with connection(tmp_path) as conn:
        outputs, _ = run_day(conn, lake, staging, (row(),))
        assert (
            len(outputs) == 2
            and plan.read_text() == '{"test":"owned by earlier job step"}'
        )
        with pytest.raises(ValueError, match="已有日候选"):
            run_day(conn, lake, staging, (row(close=Decimal(12)),))


def test_modified_current_u_rejected_before_candidate_or_target(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        source = download_stk_factor_pro_day(
            conn,
            identity=identity(),
            contract=contract(),
            downloader=Downloader(result((row(),))),
            check_cancel=lambda: None,
        )
        conn.execute("UPDATE stk_factor_pro_day_source SET close=999")
        with pytest.raises(ValueError, match="内存U已改变"):
            list(
                publication.publish_stk_factor_pro_day(
                    conn,
                    source=source,
                    lake_root=lake,
                    staging_root=staging,
                    check_cancel=lambda: None,
                )
            )
        release_stk_factor_pro_day_source(conn)
        assert list(lake.rglob("*")) == list(staging.rglob("*")) == []


def test_cancel_after_raw_complete_stops_silver_without_rollback(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        source = download_stk_factor_pro_day(
            conn,
            identity=identity(),
            contract=contract(),
            downloader=Downloader(result((row(),))),
            check_cancel=lambda: None,
        )
        cancel = [False]

        def check():
            if cancel[0]:
                raise RuntimeError("cancelled after Raw")

        iterator = publication.publish_stk_factor_pro_day(
            conn,
            source=source,
            lake_root=lake,
            staging_root=staging,
            check_cancel=check,
        )
        next(iterator)
        cancel[0] = True
        with pytest.raises(RuntimeError):
            next(iterator)
        assert raw_stk_factor_pro_path(lake, DAY.isoformat()).is_file()
        assert not silver_stock_factor_pro_path(lake, DAY.isoformat()).exists()
        assert len(list(staging.rglob("raw/complete.json"))) == 1
        release_stk_factor_pro_day_source(conn)


def test_symlink_roots_and_relative_roots_rejected(tmp_path):
    lake, staging = roots(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(lake, target_is_directory=True)
    with connection(tmp_path) as conn:
        source = download_stk_factor_pro_day(
            conn,
            identity=identity(),
            contract=contract(),
            downloader=Downloader(result((row(),))),
            check_cancel=lambda: None,
        )
        for root in (alias, Path("relative")):
            with pytest.raises(ValueError):
                list(
                    publication.publish_stk_factor_pro_day(
                        conn,
                        source=source,
                        lake_root=root,
                        staging_root=staging,
                        check_cancel=lambda: None,
                    )
                )
        release_stk_factor_pro_day_source(conn)


@pytest.mark.parametrize("dangling", [False, True])
def test_candidate_directory_symlink_rejected_before_any_write(tmp_path, dangling):
    # LLD 15.9: this is the independently reproduced bad directory layout,
    # not a simulated COPY failure. An ordinary run root may already exist.
    lake, staging = roots(tmp_path)
    outside = tmp_path / "outside"
    if not dangling:
        outside.mkdir()
    run_root = staging / "stk_factor_pro" / f"trade_date={DAY}" / "run_id=run-a"
    run_root.mkdir(parents=True)
    (run_root / "candidates").symlink_to(outside, target_is_directory=True)
    with connection(tmp_path) as conn, pytest.raises(ValueError, match="路径|候选"):
        run_day(conn, lake, staging, (row(),))
    assert list(outside.rglob("*")) == []
    assert outside.exists() is (not dangling)
    assert list(lake.rglob("*")) == []
    assert not (run_root / "publication").exists()


@pytest.mark.parametrize("dangling", [False, True])
def test_silver_symlink_after_raw_yield_rejected_before_write(tmp_path, dangling):
    lake, staging = roots(tmp_path)
    outside = tmp_path / "outside"
    if not dangling:
        outside.mkdir()
    with connection(tmp_path) as conn:
        source = download_stk_factor_pro_day(
            conn,
            identity=identity(),
            contract=contract(),
            downloader=Downloader(result((row(),))),
            check_cancel=lambda: None,
        )
        iterator = publication.publish_stk_factor_pro_day(
            conn,
            source=source,
            lake_root=lake,
            staging_root=staging,
            check_cancel=lambda: None,
        )
        try:
            target, _ = next(iterator)
            assert target.layer == "raw"
            raw = raw_stk_factor_pro_path(lake, DAY.isoformat())
            raw_bytes = raw.read_bytes()
            run_root = staging / "stk_factor_pro" / f"trade_date={DAY}" / "run_id=run-a"
            complete = (
                run_root / "publication" / "day" / str(DAY) / "raw" / "complete.json"
            )
            complete_bytes = complete.read_bytes()
            (run_root / "candidates" / "day" / "silver").symlink_to(
                outside, target_is_directory=True
            )
            with pytest.raises(ValueError, match="路径|候选"):
                next(iterator)
            assert raw.read_bytes() == raw_bytes
            assert complete.read_bytes() == complete_bytes
            assert not silver_stock_factor_pro_path(lake, DAY.isoformat()).exists()
            assert not (complete.parent.parent / "silver").exists()
        finally:
            iterator.close()
            release_stk_factor_pro_day_source(conn)
    assert list(outside.rglob("*")) == []
    assert outside.exists() is (not dangling)


def test_unmounted_formal_volume_rejected_without_accessing_formal_files(monkeypatch):
    # Only exercise the mount branch; every filesystem probe is a stub. This is
    # not a real Lake readiness or permissions acceptance test.
    monkeypatch.setattr(publication, "_safe", lambda _: None)
    monkeypatch.setattr(Path, "is_dir", lambda _: True)
    monkeypatch.setattr(Path, "is_mount", lambda _: False)
    with pytest.raises(ValueError, match="未挂载"):
        publication._roots(
            Path("/Volumes/datasource/data_lake"),
            Path("/Volumes/datasource/data_lake_staging"),
        )


def test_equivalent_new_download_does_not_replace_targets(tmp_path, monkeypatch):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        run_day(conn, lake, staging, (row(),))
        calls = []
        original = publication.os.replace

        def replace_file(a, b):
            calls.append(Path(b))
            return original(a, b)

        monkeypatch.setattr(publication.os, "replace", replace_file)
        outputs, loader = run_day(conn, lake, staging, (row(),), run="equivalent")
        assert len(loader.calls) == 1 and len(outputs) == 2
        assert not any(path.is_relative_to(lake) for path in calls)


def test_raw_yield_precedes_silver_and_failure_preserves_actual_raw(
    tmp_path, monkeypatch
):
    lake, staging = roots(tmp_path)

    def fail_silver(*args, **kwargs):
        raise OSError("synthetic Silver failure")

    monkeypatch.setattr(
        publication, "build_stk_factor_pro_silver_candidate", fail_silver
    )
    with connection(tmp_path) as conn:
        source = download_stk_factor_pro_day(
            conn,
            identity=identity(),
            contract=contract(),
            downloader=Downloader(result((row(),))),
            check_cancel=lambda: None,
        )
        iterator = publication.publish_stk_factor_pro_day(
            conn,
            source=source,
            lake_root=lake,
            staging_root=staging,
            check_cancel=lambda: None,
        )
        target, audit = next(iterator)
        assert target.layer == "raw" and audit.passed
        assert raw_stk_factor_pro_path(lake, DAY.isoformat()).is_file()
        assert not silver_stock_factor_pro_path(lake, DAY.isoformat()).exists()
        with pytest.raises(OSError):
            next(iterator)
        assert raw_stk_factor_pro_path(lake, DAY.isoformat()).is_file()
        release_stk_factor_pro_day_source(conn)


@pytest.mark.parametrize(
    "change", ["target", "candidate", "cancel", "space", "device", "raw_for_silver"]
)
def test_publication_rechecks_before_replace_and_preserves_committed_files(
    tmp_path, monkeypatch, change
):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        run_day(conn, lake, staging, (row(),), run="baseline")
        raw = raw_stk_factor_pro_path(lake, DAY.isoformat())
        silver = silver_stock_factor_pro_path(lake, DAY.isoformat())
        old_silver = factor_file_sha(silver)
        calls = [0]

        def check():
            calls[0] += 1
            # initial check, then Raw just before replace, then before Silver.
            if calls[0] == 2:
                if change == "target":
                    raw.write_bytes(b"external change")
                if change == "candidate":
                    next(
                        staging.rglob("run_id=changed/candidates/day/raw/data.parquet")
                    ).write_bytes(b"changed")
                if change == "cancel":
                    raise RuntimeError("synthetic cancellation")
                if change == "space":
                    monkeypatch.setattr(
                        publication.shutil,
                        "disk_usage",
                        lambda _: type("Usage", (), {"free": 0})(),
                    )
                if change == "device":
                    original_stat = Path.stat

                    def changed_stat(path, *args, **kwargs):
                        value = original_stat(path, *args, **kwargs)
                        if (
                            path.name == "data.parquet"
                            and "run_id=changed" in path.parts
                        ):
                            return os.stat_result(
                                (
                                    value.st_mode,
                                    value.st_ino,
                                    value.st_dev + 1,
                                    *value[3:],
                                )
                            )
                        return value

                    monkeypatch.setattr(Path, "stat", changed_stat)
            if calls[0] == 3 and change == "raw_for_silver":
                raw.write_bytes(b"external newer Raw")

        with pytest.raises((ValueError, RuntimeError)):
            run_day(
                conn,
                lake,
                staging,
                (row(close=Decimal(12)),),
                run="changed",
                check=check,
            )
        assert factor_file_sha(silver) == old_silver


def test_full_field_comparison_null_mismatch_and_equal_count_different_keys(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        run_day(conn, lake, staging, (row(),))
        raw = raw_stk_factor_pro_path(lake, DAY.isoformat())
        conn.execute(
            "CREATE TEMP TABLE expected AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(raw)],
        )
        conn.execute("UPDATE expected SET pe=1")
        audit = audit_stk_factor_pro_file(
            conn,
            path=raw,
            expected_relation="expected",
            target_trade_date=DAY,
            layer="raw",
            diagnostics_path=staging / "diagnostics.json",
        )
        assert not audit.passed and audit.comparison.changed_row_count == 1
        assert dict(audit.comparison.changed_field_counts)["pe"] == 1
        conn.execute("UPDATE expected SET ts_code='600000.SH',pe=NULL")
        audit = audit_stk_factor_pro_file(
            conn,
            path=raw,
            expected_relation="expected",
            target_trade_date=DAY,
            layer="raw",
        )
        assert (
            audit.comparison.missing_key_count
            == audit.comparison.unexpected_key_count
            == 1
        )


def test_records_reject_unknown_history_or_noncanonical_inputs(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        run_day(conn, lake, staging, (row(),))
    complete = next(staging.rglob("raw/complete.json"))
    record = publication.read_stk_factor_pro_publication_record(complete)
    assert (
        record.actual_rows == 1
        and record.verified_at.utcoffset().total_seconds() == 28800
    )
    value = json.loads(complete.read_text())
    for key, bad in (
        ("unknown", 1),
        ("phase", "history"),
        ("history_input_digest", "a" * 64),
        ("candidate_rows", True),
        ("trade_date", "20261016"),
        ("identity", None),
        ("contract", []),
        ("candidate_relative_path", "source/day/download.parquet"),
        ("target_path", "/tmp/other-data.parquet"),
        ("verified_at", "2026-10-16T19:00:00.000000+00:00"),
        ("stage", "intent"),
    ):
        path = tmp_path / f"bad-{key}.json"
        path.write_text(json.dumps({**value, key: bad}))
        with pytest.raises((ValueError, TypeError)):
            publication.read_stk_factor_pro_publication_record(path)
    forged = tmp_path / "valid-but-wrong-run.json"
    forged.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="物理路径"):
        publication.read_stk_factor_pro_publication_record(forged)


def test_failed_run_and_old_candidate_not_used_on_new_download(tmp_path, monkeypatch):
    lake, staging = roots(tmp_path)
    original = publication.build_stk_factor_pro_silver_candidate
    with connection(tmp_path) as conn:
        monkeypatch.setattr(
            publication,
            "build_stk_factor_pro_silver_candidate",
            lambda *a, **k: (_ for _ in ()).throw(OSError("synthetic")),
        )
        with pytest.raises(OSError):
            run_day(conn, lake, staging, (row(close=Decimal(10)),), run="failed")
        monkeypatch.setattr(
            publication, "build_stk_factor_pro_silver_candidate", original
        )
        run_day(conn, lake, staging, (row(close=Decimal(11)),), run="newer")
        old_hash = publication.factor_file_sha

        def refuse_old(path):
            assert "run_id=failed" not in path.parts
            return old_hash(path)

        monkeypatch.setattr(publication, "factor_file_sha", refuse_old)
        _, loader = run_day(
            conn, lake, staging, (row(close=Decimal(12)),), run="retry-new-run"
        )
        assert len(loader.calls) == 1
        assert (
            conn.execute(
                "SELECT close FROM read_parquet(?,hive_partitioning=false)",
                [str(raw_stk_factor_pro_path(lake, DAY.isoformat()))],
            ).fetchone()[0]
            == 12.0
        )


def test_real_process_exit_after_raw_then_new_process_redownloads(tmp_path):
    lake, staging = roots(tmp_path)
    code = """
import sys
from pathlib import Path
from decimal import Decimal
from orchestrator.defs.io.stk_factor_pro_download import download_stk_factor_pro_day
from orchestrator.defs.io.stk_factor_pro_publication import publish_stk_factor_pro_day
from orchestrator.defs.io.stk_factor_pro_candidates import release_stk_factor_pro_day_source
from tests.stk_factor_pro_test_support import *
root,lake,staging,mode=map(Path,sys.argv[1:])
with connection(root) as conn:
    loader=Downloader(result((row(close=Decimal('10' if str(mode)=='exit' else '12')),)))
    source=download_stk_factor_pro_day(conn,identity=identity('failed' if str(mode)=='exit' else 'fresh'),contract=contract(),downloader=loader,check_cancel=lambda:None)
    iterator=publish_stk_factor_pro_day(conn,source=source,lake_root=lake,staging_root=staging,check_cancel=lambda:None)
    next(iterator)
    if str(mode)=='exit':
        import os
        os._exit(17)
    list(iterator)
    assert len(loader.calls)==1
    release_stk_factor_pro_day_source(conn)
"""
    for mode, expected in (("exit", 17), ("fresh", 0)):
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                code,
                str(tmp_path),
                str(lake),
                str(staging),
                mode,
            ],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert completed.returncode == expected, completed.stderr
    with connection(tmp_path) as conn:
        assert (
            conn.execute(
                "SELECT close FROM read_parquet(?,hive_partitioning=false)",
                [str(silver_stock_factor_pro_path(lake, DAY.isoformat()))],
            ).fetchone()[0]
            == 12.0
        )


def test_saved_real_response_full_field_roundtrip_and_bounded_timing(
    tmp_path, record_property, monkeypatch
):
    evidence = (
        Path(__file__).resolve().parents[2]
        / "reports/stock_factor_pro_batch1_20261026/source/component-rows.canonical.json"
    )

    def decode(value):
        if value[0] == 0:
            return None
        if value[0] == 1:
            return value[1]
        if value[0] == 2:
            return int(value[1])
        assert value[0] == 3
        return Decimal((value[1], tuple(value[2]), value[3]))

    rows = [tuple(decode(v) for v in row) for row in json.loads(evidence.read_text())]
    assert len(rows) == 5 and all(len(row) == 261 for row in rows)
    actual_day = tuple(row for row in rows if row[1] == "20261016")
    assert len(actual_day) == 1
    expected = tuple(
        value if index < 2 or value is None else float(value)
        for index, value in enumerate(actual_day[0])
    )
    lake, staging = roots(tmp_path)
    hash_reads, moves = [], []
    original_hash, original_replace = (
        publication.factor_file_sha,
        publication.os.replace,
    )

    def count_hash(path):
        hash_reads.append(path.stat().st_size)
        return original_hash(path)

    def count_move(source, target):
        moves.append((Path(source), Path(target), Path(source).stat().st_size))
        return original_replace(source, target)

    monkeypatch.setattr(publication, "factor_file_sha", count_hash)
    monkeypatch.setattr(check_module, "factor_file_sha", count_hash)
    monkeypatch.setattr(publication.os, "replace", count_move)

    class CountSQL:
        def __init__(self, connection):
            self.connection, self.sql_count, self.parquet_reads = connection, 0, 0

        def execute(self, sql, *args, **kwargs):
            self.sql_count += 1
            self.parquet_reads += int("read_parquet(" in sql.lower())
            return self.connection.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    with connection(tmp_path) as conn:
        elapsed, measurements = [], []
        probe = CountSQL(conn)
        for run in ("normal", "same-day"):
            hash_reads.clear()
            moves.clear()
            probe.sql_count = probe.parquet_reads = 0
            begin = perf_counter()
            outputs, _ = run_day(probe, lake, staging, actual_day, run=run)
            elapsed.append(round(perf_counter() - begin, 4))
            assert len(outputs) == 2
            current_root = (
                staging / "stk_factor_pro" / f"trade_date={DAY}" / f"run_id={run}"
            )
            candidates = {
                source: size
                for source, _, size in moves
                if "candidates" in source.parts
            }
            candidates.update(
                {
                    p: p.stat().st_size
                    for p in (current_root / "candidates").rglob("*.parquet")
                }
            )
            assert len(candidates) == 2
            measurements.append(
                {
                    "run": run,
                    "sql_statements": probe.sql_count,
                    "parquet_read_statements": probe.parquet_reads,
                    "hash_file_reads": len(hash_reads),
                    "hash_read_bytes": sum(hash_reads),
                    "atomic_file_operations": len(moves),
                    "atomic_file_bytes": sum(size for _, _, size in moves),
                    "target_file_replaces": sum(
                        target.is_relative_to(lake) for _, target, _ in moves
                    ),
                    "candidate_parquet_files": len(candidates),
                    "candidate_bytes": sum(candidates.values()),
                    "completed_records": len(
                        list((current_root / "publication").rglob("complete.json"))
                    ),
                }
            )
        raw = raw_stk_factor_pro_path(lake, DAY.isoformat())
        assert (
            conn.execute(
                "SELECT * FROM read_parquet(?,hive_partitioning=false)", [str(raw)]
            ).fetchone()
            == expected
        )
        silver_expected = (expected[0], date(2026, 10, 16), *expected[2:])
        assert (
            conn.execute(
                "SELECT * FROM read_parquet(?,hive_partitioning=false)",
                [str(silver_stock_factor_pro_path(lake, DAY.isoformat()))],
            ).fetchone()
            == silver_expected
        )
        record_property(
            "bounded_roundtrip",
            json.dumps(
                {
                    "rows": 1,
                    "fields": 261,
                    "source_requests": 0,
                    "date": str(DAY),
                    "elapsed_seconds": elapsed,
                    "measurements": measurements,
                    "published_bytes": sum(
                        p.stat().st_size for p in lake.rglob("*.parquet")
                    ),
                    "source_cache_files": 0,
                }
            ),
        )
