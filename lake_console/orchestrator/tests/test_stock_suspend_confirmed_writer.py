"""Real one-partition writer tests on synthetic Parquet under the approved OS guard."""

from stock_suspend_confirmed_test_support import (
    connect_confirmed_test_duckdb,
    require_isolated_context,
)

require_isolated_context()

import inspect
import json
from dataclasses import replace
from pathlib import Path

import dagster as dg
import duckdb
import pytest

from orchestrator.defs import stock_suspend_confirmed_contract as contract
from orchestrator.defs.assets import suspend_d as writer
from orchestrator.defs.duckdb_sql import silver_stock_suspend_daily_select
from orchestrator.defs.paths import (
    raw_suspend_d_path,
    silver_stock_suspend_confirmed_path,
    silver_stock_suspend_daily_path,
    silver_stock_suspend_daily_staging_path,
)

DAY = "2020-01-02"


class Stopped(BaseException):
    """Fault boundary: no catch/cleanup; retry must rely on disk, not stack state."""


class ConnectionProbe:
    def __init__(self, connection, callback):
        self.connection = connection
        self.callback = callback

    def execute(self, sql, *args):
        self.callback("before", sql)
        result = self.connection.execute(sql, *args)
        self.callback("after", sql)
        return result


@pytest.fixture
def site(connection, fixed_lake, tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    return fixed_lake, staging


def _raw(connection, lake, rows=(), day=DAY):
    assert len(rows) <= 32
    path = raw_suspend_d_path(lake, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute("CREATE OR REPLACE TEMP TABLE test_raw(ts_code VARCHAR, trade_date VARCHAR, "
                       "suspend_timing VARCHAR, suspend_type VARCHAR)")
    if rows:
        connection.execute("INSERT INTO test_raw VALUES " + ",".join(["(?,?,?,?)"] * len(rows)),
                           [value for row in rows for value in row])
    connection.execute("COPY test_raw TO ? (FORMAT PARQUET)", [str(path)])
    return path


def _target(connection, lake, rows, day=DAY):
    path = silver_stock_suspend_daily_path(lake, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute("CREATE OR REPLACE TEMP TABLE test_target(ts_code VARCHAR, trade_date DATE, "
                       "suspend_timing VARCHAR, suspend_type VARCHAR)")
    if rows:
        connection.execute("INSERT INTO test_target VALUES " + ",".join(["(?,?,?,?)"] * len(rows)),
                           [value for row in rows for value in row])
    connection.execute("COPY test_target TO ? (FORMAT PARQUET, COMPRESSION UNCOMPRESSED)", [str(path)])
    return path


def _rows(connection, path):
    return connection.execute("SELECT ts_code, trade_date::VARCHAR, suspend_timing, suspend_type "
                              "FROM read_parquet(?, hive_partitioning=false) ORDER BY ALL", [str(path)]).fetchall()


def _run(connection, site, *, day=DAY, run="run-a"):
    return writer.write_silver_stock_suspend_daily_partition(
        connection, lake_root=site[0], staging_root=site[1], trade_date=day, run_id=run,
    )


def _candidate(site, run="run-a", day=DAY):
    return silver_stock_suspend_daily_staging_path(site[1], run, day)


def _checkpoint(site):
    return _candidate(site).with_name("checkpoint.json")


def _replace_spy(monkeypatch, target, *, stop=None):
    actual = writer.os.replace
    calls = []

    def replacement(source, destination):
        if Path(destination) == target:
            calls.append((str(source), str(destination)))
            if stop == "before":
                raise Stopped()
        actual(source, destination)
        if Path(destination) == target and stop == "after":
            raise Stopped()

    monkeypatch.setattr(writer.os, "replace", replacement)
    return calls


@pytest.mark.parametrize("day,raw,expected,timing", [
    (DAY, [], [("000001.SZ", DAY, None, "S")], 0),
    (DAY, [("000001.SZ", "20200102", "", "S")], [("000001.SZ", DAY, None, "S")], 0),
    (DAY, [("000001.SZ", "20200102", None, "S")] * 2, [("000001.SZ", DAY, None, "S")] * 2, 0),
    ("2020-01-03", [], [], 0),
    ("2026-01-16", [("688005.SH", "20260116", "09:30-09:30", "S"),
                    ("688005.SH", "20260116", None, "R")],
     [("688005.SH", "2026-01-16", None, "S")], 0),
    ("2014-01-02", [("000566.SZ", "20140102", None, "S")],
     [("000566.SZ", "2014-01-02", "13:55-15:00", "S")], 1),
])
def test_writer_literal_results(connection, site, monkeypatch, day, raw, expected, timing):
    _raw(connection, site[0], raw, day)
    target = silver_stock_suspend_daily_path(site[0], day)
    calls = _replace_spy(monkeypatch, target)
    result = _run(connection, site, day=day)
    assert result.status == "written" and result.output["row_count"] == len(expected)
    assert result.output["timing_count"] == timing
    assert result.output["schema"] == [["ts_code", "VARCHAR"], ["trade_date", "DATE"],
                                       ["suspend_timing", "VARCHAR"], ["suspend_type", "VARCHAR"]]
    assert _rows(connection, target) == expected and len(calls) == 1
    assert result.confirmed_logical_sha256 == contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256
    checkpoint = json.loads(_candidate(site, day=day).with_name("checkpoint.json").read_text())
    assert checkpoint["stage"] == "committed" and checkpoint["output"] == result.output
    assert not _candidate(site, day=day).exists()


def test_writer_rebuild_and_reuse(connection, site, monkeypatch):
    raw = _raw(connection, site[0])
    first = _run(connection, site)
    assert _rows(connection, first.target_path) == [("000001.SZ", DAY, None, "S")]
    # A real Raw replacement; a new run must not scan previous staging.
    _raw(connection, site[0], [("000002.SZ", "20200102", "10:00-10:30", "S")])
    second = _run(connection, site, run="run-b")
    expected = [("000001.SZ", DAY, None, "S"), ("000002.SZ", DAY, "10:00-10:30", "S")]
    assert _rows(connection, second.target_path) == expected
    # Different physical encoding but equal multiset is reused.
    _target(connection, site[0], expected)
    before = contract.suspend_file_identity(second.target_path)
    calls = _replace_spy(monkeypatch, second.target_path)
    third = _run(connection, site, run="run-c")
    assert third.status == "reused" and calls == []
    assert contract.suspend_file_identity(third.target_path) == before
    assert not _candidate(site, run="run-c").parent.exists()
    assert raw.exists() and _checkpoint(site).exists()


def test_writer_public_signature():
    parameters = inspect.signature(silver_stock_suspend_daily_select).parameters
    assert list(parameters) == ["normalized_relation", "confirmed_relation", "dates_relation"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())
    with pytest.raises(TypeError):
        silver_stock_suspend_daily_select(Path("old"), DAY)


def test_writer_asset_dependency():
    asset = writer.silver_stock_suspend_daily
    assert asset.asset_deps[asset.key] == {
        dg.AssetKey("raw_tushare_suspend_d"), dg.AssetKey("silver_stock_suspend_confirmed"),
    }
    assert list(inspect.signature(asset.op.compute_fn.decorated_fn).parameters) == ["context", "lake_root", "duckdb"]


@pytest.mark.parametrize("rows", [
    [("000001.SZ", "20200102", None, "R")],
    [("000001.SZ", "20200102", "10:00-10:30", "S")],
    [("000001.SZ", "20200102", None, "S"), ("000001.SZ", "20200102", None, "R")],
])
def test_writer_conflict(connection, site, monkeypatch, rows):
    _raw(connection, site[0], rows)
    target = _target(connection, site[0], [("000009.SZ", DAY, None, "R")])
    before = target.read_bytes()
    calls = _replace_spy(monkeypatch, target)
    with pytest.raises(contract.ConfirmedFactsError) as error:
        _run(connection, site)
    assert error.value.reason_code == "confirmed_raw_conflict"
    assert target.read_bytes() == before and calls == [] and not _candidate(site).parent.exists()


@pytest.mark.parametrize("raw_date", ["20200103", None, "not-a-date"])
def test_writer_wrong_raw_date(connection, site, monkeypatch, raw_date):
    _raw(connection, site[0], [("000002.SZ", raw_date, None, "S")])
    target = _target(connection, site[0], [])
    before = target.read_bytes()
    calls = _replace_spy(monkeypatch, target)
    with pytest.raises((contract.ConfirmedFactsError, duckdb.Error)) as error:
        _run(connection, site)
    if raw_date != "not-a-date":
        assert error.value.reason_code == "raw_partition_date_mismatch"
    assert target.read_bytes() == before and calls == [] and not _candidate(site).exists()


@pytest.mark.parametrize("kind", ["missing", "changed"])
def test_writer_invalid_fixed(connection, site, kind):
    _raw(connection, site[0])
    fixed = silver_stock_suspend_confirmed_path(site[0])
    if kind == "missing":
        fixed.rename(fixed.with_suffix(".held"))
    else:
        fixed.write_bytes(b"not-parquet")
    with pytest.raises(FileNotFoundError if kind == "missing" else duckdb.Error):
        _run(connection, site)
    assert not _candidate(site).exists() and not silver_stock_suspend_daily_path(site[0], DAY).exists()


@pytest.mark.parametrize("kind", ["copy", "broken", "different"])
def test_writer_candidate_failure(connection, site, monkeypatch, kind):
    _raw(connection, site[0])
    target = _target(connection, site[0], [])
    before = target.read_bytes()
    calls = _replace_spy(monkeypatch, target)

    def inject(when, sql):
        if not sql.lstrip().upper().startswith("COPY"):
            return
        if when == "before" and kind == "copy":
            raise RuntimeError("injected COPY failure")
        if when == "after" and kind == "broken":
            _candidate(site).write_bytes(b"broken")
        if when == "after" and kind == "different":
            connection.execute("COPY (SELECT * FROM test_target) TO ? (FORMAT PARQUET)", [str(_candidate(site))])

    expected = {"copy": RuntimeError, "broken": duckdb.Error, "different": contract.ConfirmedFactsError}
    with pytest.raises(expected[kind]):
        _run(ConnectionProbe(connection, inject), site)
    assert target.read_bytes() == before and calls == [] and not _checkpoint(site).exists()


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_writer_resume(connection, site, monkeypatch, boundary):
    _raw(connection, site[0])
    target = _target(connection, site[0], [])
    with monkeypatch.context() as patch:
        _replace_spy(patch, target, stop=boundary)
        with pytest.raises(Stopped):
            _run(connection, site)
    frozen = json.loads(_checkpoint(site).read_text())["output"]
    assert json.loads(_checkpoint(site).read_text())["stage"] == "prepared"
    calls = _replace_spy(monkeypatch, target)
    with connect_confirmed_test_duckdb(temp_directory=site[1] / "retry-duckdb") as retry:
        result = _run(retry, site)
    assert result.output == frozen and len(calls) == (1 if boundary == "before" else 0)
    assert json.loads(_checkpoint(site).read_text())["stage"] == "committed"
    assert _rows(connection, target) == [("000001.SZ", DAY, None, "S")]


@pytest.mark.parametrize("input_name,missing", [("raw", False), ("raw", True), ("confirmed", False), ("confirmed", True)])
def test_writer_committed_input_drift(connection, site, monkeypatch, input_name, missing):
    raw = _raw(connection, site[0])
    target = silver_stock_suspend_daily_path(site[0], DAY)
    with monkeypatch.context() as patch:
        _replace_spy(patch, target, stop="after")
        with pytest.raises(Stopped):
            _run(connection, site)
    frozen = json.loads(_checkpoint(site).read_text())["output"]
    path = raw if input_name == "raw" else silver_stock_suspend_confirmed_path(site[0])
    if missing:
        path.rename(path.with_suffix(".held"))
    else:
        path.write_bytes(path.read_bytes())  # Same bytes, changed identity is still drift.
    before = target.read_bytes()
    calls = _replace_spy(monkeypatch, target)
    with pytest.raises(contract.ConfirmedFactsError) as error:
        _run(connection, site)
    assert error.value.reason_code == "committed_input_drift"
    checkpoint = json.loads(_checkpoint(site).read_text())
    assert checkpoint["stage"] == "committed" and checkpoint["output"] == frozen
    assert checkpoint["error"]["reason_code"] == "committed_input_drift"
    assert calls == [] and target.read_bytes() == before


@pytest.mark.parametrize("changed", ["raw", "confirmed", "target", "candidate_missing", "candidate_changed", "target_missing"])
def test_writer_prepared_drift(connection, site, monkeypatch, changed):
    raw = _raw(connection, site[0])
    target = _target(connection, site[0], [])
    with monkeypatch.context() as patch:
        _replace_spy(patch, target, stop="before")
        with pytest.raises(Stopped):
            _run(connection, site)
    paths = {"raw": raw, "confirmed": silver_stock_suspend_confirmed_path(site[0]),
             "target": target, "candidate_missing": _candidate(site),
             "candidate_changed": _candidate(site), "target_missing": target}
    path = paths[changed]
    if changed.endswith("missing"):
        path.rename(path.with_suffix(".held"))
    else:
        path.write_bytes(path.read_bytes())
    before = target.read_bytes() if target.exists() else None
    calls = _replace_spy(monkeypatch, target)
    with pytest.raises(FileNotFoundError if changed == "candidate_missing" else contract.ConfirmedFactsError):
        _run(connection, site)
    assert calls == []
    assert (target.read_bytes() if target.exists() else None) == before


@pytest.mark.parametrize("damage", ["json", "missing", "stats", "type", "path", "run", "duplicate", "oversized"])
def test_writer_corrupt_checkpoint(connection, site, monkeypatch, damage):
    _raw(connection, site[0])
    target = _target(connection, site[0], [])
    with monkeypatch.context() as patch:
        _replace_spy(patch, target, stop="before")
        with pytest.raises(Stopped):
            _run(connection, site)
    checkpoint = json.loads(_checkpoint(site).read_text())
    if damage == "missing":
        del checkpoint["candidate"]["file_identity"]
    elif damage == "stats":
        del checkpoint["output"]["stats"]["removed_raw_rows"]
    elif damage == "type":
        checkpoint["output"]["row_count"] = True
    elif damage == "path":
        checkpoint["target"]["path"] = str(target.with_name("wrong.parquet"))
    elif damage == "run":
        checkpoint["run_id"] = "another-run"
    if damage == "oversized":
        actual = contract.suspend_file_identity

        def pretend_size(path):
            identity = actual(path)
            return replace(identity, size=1024 * 1024 + 1) if path == _checkpoint(site) else identity

        monkeypatch.setattr(contract, "suspend_file_identity", pretend_size)
    else:
        payload = json.dumps(checkpoint)
        if damage == "json":
            payload = "{"
        if damage == "duplicate":
            payload = payload[:-1] + ', "stage": "prepared"}'
        _checkpoint(site).write_text(payload)
    before = target.read_bytes()
    calls = _replace_spy(monkeypatch, target)
    with pytest.raises(contract.ConfirmedFactsError) as error:
        _run(connection, site)
    assert error.value.reason_code == "checkpoint_invalid"
    assert target.read_bytes() == before and calls == []


@pytest.mark.parametrize("missing", [False, True])
def test_writer_committed_target_changed(connection, site, monkeypatch, missing):
    _raw(connection, site[0])
    result = _run(connection, site)
    if missing:
        result.target_path.rename(result.target_path.with_suffix(".held"))
    else:
        _target(connection, site[0], [])
    calls = _replace_spy(monkeypatch, result.target_path)
    with pytest.raises(contract.ConfirmedFactsError) as error:
        _run(connection, site)
    assert error.value.reason_code == "committed_target_mismatch" and calls == []


@pytest.mark.parametrize("stage", ["prepared", "committed"])
def test_writer_checkpoint_write_failure(connection, site, monkeypatch, stage):
    _raw(connection, site[0])
    target = _target(connection, site[0], [])
    before = target.read_bytes()
    actual = writer.os.replace
    checkpoint_writes = []

    def fail_checkpoint(source, destination):
        if Path(destination) == _checkpoint(site):
            checkpoint_writes.append(str(source))
            if len(checkpoint_writes) == (1 if stage == "prepared" else 2):
                raise OSError("checkpoint disk failure")
        actual(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(writer.os, "replace", fail_checkpoint)
        with pytest.raises(OSError, match="disk failure"):
            _run(connection, site)
    assert list(_candidate(site).parent.glob("checkpoint.*.tmp"))
    if stage == "prepared":
        assert target.read_bytes() == before and _candidate(site).exists() and not _checkpoint(site).exists()
        with pytest.raises(contract.ConfirmedFactsError) as error:
            _run(connection, site)
        assert error.value.reason_code == "unprepared_candidate"
    else:
        assert json.loads(_checkpoint(site).read_text())["stage"] == "prepared"
        before = target.read_bytes()
        calls = _replace_spy(monkeypatch, target)
        _run(connection, site)
        assert calls == [] and target.read_bytes() == before
        assert json.loads(_checkpoint(site).read_text())["stage"] == "committed"


def test_writer_orphan_candidate(connection, site):
    _raw(connection, site[0])
    path = _candidate(site)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"partial candidate")
    with pytest.raises(contract.ConfirmedFactsError) as error:
        _run(connection, site)
    assert error.value.reason_code == "unprepared_candidate" and path.read_bytes() == b"partial candidate"


@pytest.mark.parametrize("input_name", ["raw", "confirmed"])
def test_writer_load_drift(connection, site, input_name):
    raw = _raw(connection, site[0])
    fixed = silver_stock_suspend_confirmed_path(site[0])
    path = raw if input_name == "raw" else fixed
    fragment = "TEMP TABLE suspend_normalized" if input_name == "raw" else 'TEMP TABLE "suspend_confirmed"'

    def mutate(when, sql):
        if when == "after" and fragment in sql:
            path.write_bytes(path.read_bytes())

    with pytest.raises(contract.ConfirmedFactsError) as error:
        _run(ConnectionProbe(connection, mutate), site)
    assert error.value.reason_code == "input_drift" and not _candidate(site).exists()


@pytest.mark.parametrize("changed,hidden", [("raw", False), ("confirmed", False), ("candidate", False),
                                           ("target", False), ("raw", True), ("confirmed", True), ("candidate", True)])
def test_writer_prepared_window_drift(connection, site, monkeypatch, changed, hidden):
    raw = _raw(connection, site[0])
    target = _target(connection, site[0], [])
    paths = {"raw": raw, "confirmed": silver_stock_suspend_confirmed_path(site[0]),
             "candidate": _candidate(site), "target": target}
    actual = writer._save_suspend_checkpoint

    def mutate(path, checkpoint):
        actual(path, checkpoint)
        victim = paths[changed]
        before = victim.stat()
        payload = bytearray(victim.read_bytes())
        if hidden:
            payload[-1] ^= 1
        victim.write_bytes(payload)
        if hidden:
            writer.os.utime(victim, ns=(before.st_atime_ns, before.st_mtime_ns))

    monkeypatch.setattr(writer, "_save_suspend_checkpoint", mutate)
    calls = _replace_spy(monkeypatch, target)
    with pytest.raises(contract.ConfirmedFactsError):
        _run(connection, site)
    assert calls == [] and _rows(connection, target) == []


@pytest.mark.parametrize("kind", ["missing_root", "overlap", "symlink", "invalid_day"])
def test_writer_invalid_paths(connection, site, kind):
    _raw(connection, site[0])
    if kind == "missing_root":
        site = site[0], site[1] / "absent"
    elif kind == "overlap":
        site = site[0], site[0]
    elif kind == "symlink":
        alias = site[1] / "link"
        alias.symlink_to(site[0], target_is_directory=True)
        site = alias, site[1]
    with pytest.raises((contract.ConfirmedFactsError, ValueError)):
        _run(connection, site, day="20200102" if kind == "invalid_day" else DAY)
