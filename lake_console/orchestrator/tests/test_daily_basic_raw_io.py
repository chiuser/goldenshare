"""Isolated daily-basic source and safe-write contracts."""

import fcntl
import subprocess
import sys
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import duckdb
import pytest

from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_FIELDS,
    DailyBasicValidationError,
)
from orchestrator.defs.daily_basic_raw_io import (
    audit_daily_basic_coverage,
    audit_daily_basic_file,
    file_sha256,
    write_daily_basic_partition,
)
from orchestrator.defs.paths import raw_daily_basic_path
from orchestrator.defs.source_readiness.daily_basic import fetch_daily_basic_pages

DAY = "2026-09-14"


def row(code="000001.SZ", **values):
    result = dict.fromkeys(DAILY_BASIC_FIELDS, "1.2345")
    result.update(ts_code=code, trade_date="20260914", pe=None, pb="-2.1000")
    result.update(values)
    return result


class Source:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def call(self, api, params, fields):
        self.calls.append((api, params, fields))
        rows = self.rows[params["offset"] : params["offset"] + params["limit"]]
        return SimpleNamespace(rows=rows, columns=tuple(fields))


class DB:
    @contextmanager
    def connect(self):
        with duckdb.connect() as connection:
            yield connection


def write(tmp_path, rows=None, **kwargs):
    options = {
        "lake_root": tmp_path / "lake",
        "staging_root": tmp_path / "stage",
        "trade_date": DAY,
        "run_id": "test",
        "duckdb_resource": DB(),
        "tushare": Source(rows if rows is not None else [row()]),
        "load_expected_codes": lambda: ["000001.SZ"],
    }
    options.update(kwargs)
    return write_daily_basic_partition(**options)


def test_round_trip_extra_null_negative_and_evidence(tmp_path):
    evidence = write(tmp_path, [row(), row("000002.SZ")])
    target = raw_daily_basic_path(tmp_path / "lake", DAY)
    with DB().connect() as connection:
        audit = audit_daily_basic_file(connection, target, DAY)
        assert not audit.failed_rules
        assert audit.row_count == 2
        assert connection.execute(
            "SELECT pe,pb,close FROM read_parquet(?,hive_partitioning=false) LIMIT 1",
            [str(target)],
        ).fetchone() == (None, Decimal("-2.1000"), Decimal("1.2345"))
    assert not audit_daily_basic_coverage(target, audit, ["000001.SZ"], evidence)
    assert audit_daily_basic_coverage(target, audit, ["000001.SZ"], {})


def test_idempotent_conflict_replace(tmp_path):
    write(tmp_path)
    target = raw_daily_basic_path(tmp_path / "lake", DAY)
    before = file_sha256(target)
    assert write(tmp_path)["result_status"] == "reused"
    with pytest.raises(DailyBasicValidationError, match="conflict"):
        write(tmp_path, [row(close="9")])
    assert file_sha256(target) == before
    assert (
        write(tmp_path, [row(close="9")], write_mode="replace")["result_status"]
        == "written"
    )
    assert file_sha256(target) != before


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [row("000002.SZ")],
        [row(), row()],
        [row(ts_code=None)],
        [row(trade_date="20260911")],
        [row(close="1.23456")],
        [row(close="999999999999999999999999")],
    ],
)
def test_invalid_source_preserves_target(tmp_path, rows):
    write(tmp_path)
    target = raw_daily_basic_path(tmp_path / "lake", DAY)
    before = file_sha256(target)
    with pytest.raises((DailyBasicValidationError, duckdb.Error)):
        write(tmp_path, rows, write_mode="replace")
    assert file_sha256(target) == before
    assert not list((tmp_path / "stage").rglob("*.parquet"))


def test_atomic_promote_failure_and_upstream_change(tmp_path):
    write(tmp_path)
    target = raw_daily_basic_path(tmp_path / "lake", DAY)
    before = file_sha256(target)
    with (
        patch(
            "orchestrator.defs.daily_basic_raw_io.os.replace",
            side_effect=OSError("blocked"),
        ),
        pytest.raises(OSError),
    ):
        write(tmp_path, [row(close="2")], write_mode="replace")
    assert file_sha256(target) == before
    codes = iter([["000001.SZ"], ["000002.SZ"]])
    with pytest.raises(DailyBasicValidationError, match="upstream_changed"):
        write(tmp_path, load_expected_codes=lambda: next(codes))
    assert file_sha256(target) == before


def test_nonblocking_lock_is_persistent_and_released(tmp_path):
    lock = tmp_path / "stage/daily_basic/locks" / f"{DAY}.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("a") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(DailyBasicValidationError, match="partition_locked"):
            write(tmp_path)
    write(tmp_path)
    assert lock.exists()


def test_late_response_never_consumed():
    now = [0.0]
    consumed = []
    source = Source([row()])
    original = source.call

    def late(*args):
        now[0] = 61
        return original(*args)

    source.call = late
    with pytest.raises(DailyBasicValidationError):
        fetch_daily_basic_pages(
            tushare=source,
            trade_date=DAY,
            fields=DAILY_BASIC_FIELDS,
            consume_page=lambda *args: consumed.append(args),
            clock=lambda: now[0],
            sleep_fn=lambda seconds: None,
        )
    assert not consumed
    assert len(source.calls) == 1


def test_pagination_streams_and_rate_limits():
    now = [0.0]
    starts = []
    source = Source([row(str(i)) for i in range(6001)])
    original = source.call

    def request(*args):
        starts.append(now[0])
        return original(*args)

    source.call = request
    sizes = []
    result = fetch_daily_basic_pages(
        tushare=source,
        trade_date=DAY,
        fields=DAILY_BASIC_FIELDS,
        consume_page=lambda offset, rows: sizes.append((offset, len(rows))),
        clock=lambda: now[0],
        sleep_fn=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )
    assert result.completed
    assert sizes == [(0, 6000), (6000, 1)]
    assert starts[1] - starts[0] >= 1
    assert not result.rows


def test_paths_reject_invalid_identity(tmp_path):
    with pytest.raises(ValueError):
        raw_daily_basic_path(tmp_path, "../invalid")
    with pytest.raises(ValueError, match="before_history_start"):
        raw_daily_basic_path(tmp_path, "2009-12-31")
    with pytest.raises(ValueError):
        write(tmp_path, run_id="../../bad")


def test_process_exit_releases_lock(tmp_path):
    lock = tmp_path / "stage/daily_basic/locks" / f"{DAY}.lock"
    lock.parent.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import fcntl,os,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX); os._exit(0)",
            str(lock),
        ],
        check=True,
        timeout=10,
    )
    assert write(tmp_path)["result_status"] == "written"


def test_corrupt_and_wrong_schema_are_red(tmp_path):
    target = raw_daily_basic_path(tmp_path / "lake", DAY)
    target.parent.mkdir(parents=True)
    with DB().connect() as connection:
        assert audit_daily_basic_file(connection, target, DAY).failed_rules == (
            "file_missing",
        )
        target.write_bytes(b"broken parquet")
        assert audit_daily_basic_file(connection, target, DAY).failed_rules
        connection.execute(
            "COPY (SELECT 'x' AS ts_code) TO ? (FORMAT PARQUET)", [str(target)]
        )
        assert audit_daily_basic_file(connection, target, DAY).failed_rules
