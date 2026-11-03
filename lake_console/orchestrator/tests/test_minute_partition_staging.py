"""Literal current producer contracts; real file/SQL checks, isolated failures."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import duckdb
import pytest

from orchestrator.defs.assets import index_mins, index_mins_silver, stk_mins
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io import minute_partition_writer as io

DAY = "2026-10-22"


def sql(dataset, day=DAY, duplicate=False):
    stock = "stk" in dataset
    freq = "1::INTEGER" if stock else "'1min'::VARCHAR"
    fields = f"""ts_code::VARCHAR AS ts_code,{freq} AS freq,
        TIMESTAMP '{day} 09:30:00' AS trade_time,
        10::DOUBLE AS open,10.5::DOUBLE AS close,11::DOUBLE AS high,9::DOUBLE AS low,
        100::{"BIGINT" if dataset == "raw_stk_mins" else "DOUBLE"} AS vol,
        1000::DOUBLE AS amount,'XSHG'::VARCHAR AS exchange,10::DOUBLE AS vwap"""
    if dataset == "silver_stk_mins":
        fields = f"""ts_code::VARCHAR AS ts_code,{freq} AS freq,DATE '{day}' AS trade_date,
            TIMESTAMP '{day} 09:30:00' AS trade_time,10::DOUBLE AS open,
            11::DOUBLE AS high,9::DOUBLE AS low,10.5::DOUBLE AS close,
            100::DOUBLE AS vol,1000::DOUBLE AS amount,'SSE'::VARCHAR AS exchange"""
    values = "('600000.SH'),('600000.SH')" if duplicate else "('600000.SH')"
    return f"SELECT {fields} FROM (VALUES {values}) codes(ts_code)"


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    def connect():
        return duckdb.connect(
            config={
                "temp_directory": str(tmp_path / "duckdb"),
                "memory_limit": "128MB",
                "threads": "1",
                "max_temp_directory_size": "0B",
            }
        )

    for module in (io, index_mins, index_mins_silver, stk_mins):
        monkeypatch.setattr(module, "connect_configured_duckdb", connect)
    monkeypatch.setattr(io, "gettempdir", lambda: str(tmp_path))


def publication(root, dataset="raw_index_mins", *, source=True, overwrite=False):
    path = root / "input.txt"
    if source and not path.exists():
        path.write_text("input v1")
    return io.MinutePartitionPublication(
        dataset=dataset,
        target=root / "output" / f"{dataset}.parquet",
        day=DAY,
        freq=1,
        publication_id="operation",
        source_paths=(path,) if source else (),
        source_identity=("approved-request", 1),
        overwrite=overwrite,
    )


def builder(dataset):
    def build(candidate):
        with io.connect_configured_duckdb() as c:
            c.execute(copy_query_to_parquet(sql(dataset), candidate))
        return {"row_count": 1, "source_rows": 1, "diagnostics": {"source": "literal"}}

    return build


@pytest.mark.parametrize("dataset", tuple(io.CONTRACTS))
@pytest.mark.parametrize("after", [False, True])
def test_registered_families_resume_without_rebuild(tmp_path, dataset, after):
    p = publication(tmp_path, dataset)
    original = os.replace

    def interrupt(source, target):
        if Path(target) == p.target:
            if after:
                original(source, target)
            raise RuntimeError("interrupted")
        original(source, target)

    with (
        patch.object(io.os, "replace", side_effect=interrupt),
        pytest.raises(RuntimeError, match="interrupted"),
    ):
        p.run(builder(dataset))
    before = p.target.read_bytes() if after else None
    restored = publication(tmp_path, dataset)
    result = restored.run(lambda _: pytest.fail("repeated source export"))
    assert result == {
        "row_count": 1,
        "source_rows": 1,
        "diagnostics": {"source": "literal"},
    }
    assert restored.reused
    if before:
        assert p.target.read_bytes() == before
    stat = p.target.stat()
    publication(tmp_path, dataset).run(lambda _: pytest.fail("repeated completed work"))
    assert (stat.st_ino, stat.st_mtime_ns) == (
        p.target.stat().st_ino,
        p.target.stat().st_mtime_ns,
    )
    assert (
        json.loads((p.directory / "receipt.json").read_text())["status"] == "promoted"
    )
    assert "goldenshare_minute_staging" in p.directory.parts
    assert not list(p.target.parent.glob("*.tmp"))


@pytest.mark.parametrize("bad", ["schema", "date", "duplicate", "count", "freq"])
def test_bad_candidate_preserves_formal_and_failed_file(tmp_path, bad):
    p = publication(tmp_path, "silver_index_mins", overwrite=True)
    p.target.parent.mkdir()
    p.target.write_bytes(b"formal old contents")

    def bad_builder(candidate):
        query = sql(
            "silver_index_mins",
            day="2026-10-21" if bad == "date" else DAY,
            duplicate=bad == "duplicate",
        )
        if bad == "schema":
            query = "SELECT 1 AS wrong"
        if bad == "freq":
            query = query.replace("'1min'", "'5min'")
        with io.connect_configured_duckdb() as c:
            c.execute(copy_query_to_parquet(query, candidate))
        return {"row_count": 2 if bad == "count" else 1}

    with pytest.raises(ValueError, match="candidate"):
        p.run(bad_builder)
    assert p.target.read_bytes() == b"formal old contents"
    failed = list(p.directory.glob("attempt=*/part-000.parquet"))
    assert len(failed) == 1
    p.run(builder("silver_index_mins"))
    assert failed[0].exists()


@pytest.mark.parametrize("damage", ["source", "candidate", "target"])
def test_changed_input_candidate_target_reject(tmp_path, damage):
    p = publication(tmp_path)
    original = os.replace

    def interrupt(source, target):
        if Path(target) == p.target:
            raise RuntimeError("hold")
        original(source, target)

    with (
        patch.object(io.os, "replace", side_effect=interrupt),
        pytest.raises(RuntimeError, match="hold"),
    ):
        p.run(builder("raw_index_mins"))
    receipt = json.loads((p.directory / "receipt.json").read_text())
    damaged = {
        "source": tmp_path / "input.txt",
        "candidate": Path(receipt["candidate"]),
        "target": p.target,
    }[damage]
    damaged.parent.mkdir(parents=True, exist_ok=True)
    damaged.write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        publication(tmp_path).run(lambda _: pytest.fail("must stop"))


def test_paths_lock_space_reject_before_build(tmp_path, monkeypatch):
    for dataset, target in (
        ("other", tmp_path / "x"),
        ("raw_index_mins", Path("/unapproved/lake/x")),
        ("raw_index_mins", tmp_path / ".." / "escaped"),
    ):
        with pytest.raises(ValueError):
            io.MinutePartitionPublication(
                dataset=dataset, target=target, day=DAY, freq=1, source_identity="x"
            )
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with pytest.raises(ValueError):
        io.MinutePartitionPublication(
            dataset="raw_index_mins",
            target=tmp_path / "link/x",
            day=DAY,
            freq=1,
            source_identity="x",
        )
    p = publication(tmp_path)
    p.namespace.mkdir(parents=True)
    fd = os.open(p.namespace / "writer.lock", os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        io.fcntl.flock(fd, io.fcntl.LOCK_EX | io.fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            p.run(lambda _: pytest.fail("locked"))
    finally:
        os.close(fd)
    usage = io.shutil.disk_usage(tmp_path)
    monkeypatch.setattr(io.shutil, "disk_usage", lambda _: usage._replace(free=0))
    with pytest.raises(OSError, match="space"):
        p.run(lambda _: pytest.fail("no space"))


def test_actual_index_raw_silver_and_pool_identity(tmp_path, monkeypatch):
    source = tmp_path / "source.parquet"
    with io.connect_configured_duckdb() as c:
        c.execute(copy_query_to_parquet(sql("raw_index_mins"), source))
    monkeypatch.setattr(index_mins, "_load_duckdb_postgres_extension", lambda _: None)
    monkeypatch.setattr(
        index_mins, "_attach_prod_postgres_database", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        index_mins,
        "build_prod_index_mins_duckdb_source_sql",
        lambda **kw: f"SELECT * FROM {read_parquet(source, hive_partitioning=False)}",
    )
    kwargs = {
        "lake_root": tmp_path / "lake",
        "duckdb": SimpleNamespace(),
        "prod_postgres": SimpleNamespace(duckdb_connection_string=lambda: "test-only"),
        "source_freq": "1min",
        "partition_key": DAY,
        "active_pool": ("600000.SH",),
        "publication_id": "actual",
    }
    raw = index_mins.write_raw_index_mins_partition_from_prod_db(**kwargs)
    assert raw.written_row_count == raw.returned_code_count == 1
    silver = index_mins_silver.write_silver_index_mins_partition(
        lake_root=tmp_path / "lake",
        duckdb=SimpleNamespace(),
        freq=1,
        partition_key=DAY,
        publication_id="actual",
    )
    with io.connect_configured_duckdb() as c:
        rows = c.execute(
            f"SELECT ts_code,open,close,vol FROM {read_parquet(silver.silver_file_path, hive_partitioning=False)}"
        ).fetchall()
    assert rows == [("600000.SH", 10.0, 10.5, 100.0)]
    monkeypatch.setattr(
        index_mins,
        "_build_raw_index_mins_partition_from_prod_db",
        lambda **kw: pytest.fail("re-exported"),
    )
    assert (
        index_mins.write_raw_index_mins_partition_from_prod_db(**kwargs).query_count
        == 0
    )
    with pytest.raises(ValueError, match="inputs changed"):
        index_mins.write_raw_index_mins_partition_from_prod_db(
            **{**kwargs, "active_pool": ("000001.SZ",)}
        )


def test_real_process_exit_after_replace(tmp_path):
    p = publication(tmp_path, source=False)
    code = """
import os,sys,duckdb
from pathlib import Path
from orchestrator.defs.io import minute_partition_writer as io
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
root=Path(sys.argv[1]);io.gettempdir=lambda:str(root)
def connect():
    return duckdb.connect(config={"temp_directory":str(root/"duckdb"),"threads":"1","memory_limit":"128MB","max_temp_directory_size":"0B","autoinstall_known_extensions":"false","autoload_known_extensions":"false"})
io.connect_configured_duckdb=connect
p=io.MinutePartitionPublication(dataset='raw_index_mins',target=root/'output/raw_index_mins.parquet',day='2026-10-22',freq=1,publication_id='operation',source_identity=('approved-request',1))
original=os.replace
def replace(source,target):
    original(source,target)
    if Path(target)==p.target:os._exit(17)
io.os.replace=replace
def build(path):
    with connect() as c:c.execute(copy_query_to_parquet(sys.argv[2],path))
    return {'row_count':1}
p.run(build)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(tmp_path), sql("raw_index_mins")],
        timeout=15,
        check=False,
    )
    assert result.returncode == 17
    before = p.target.stat()
    p.run(lambda _: pytest.fail("must reuse"))
    assert p.target.stat().st_ino == before.st_ino


def test_formal_layout_mapping_and_cross_device_reject_before_generation(
    tmp_path, monkeypatch
):
    formal, staging = tmp_path / "formal", tmp_path / "staging"
    formal.mkdir()
    staging.mkdir()
    monkeypatch.setattr(io, "DEFAULT_LAKE_ROOT", str(formal))
    monkeypatch.setattr(io, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    target = io.raw_index_mins_path(formal, "1min", DAY)
    p = io.MinutePartitionPublication(
        dataset="raw_index_mins",
        target=target,
        day=DAY,
        freq=1,
        source_identity="fixed-source",
    )
    assert p.directory.is_relative_to(staging)
    with pytest.raises(ValueError, match="does not match"):
        io.MinutePartitionPublication(
            dataset="raw_index_mins",
            target=formal / "wrong.parquet",
            day=DAY,
            freq=1,
            source_identity="fixed-source",
        )
    target.parent.mkdir(parents=True)
    original = Path.stat

    def different_device(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path == target.parent:
            return SimpleNamespace(st_dev=value.st_dev + 1, st_mode=value.st_mode)
        return value

    monkeypatch.setattr(Path, "stat", different_device)
    with pytest.raises(ValueError, match="filesystem"):
        p.run(lambda _: pytest.fail("cross-device build must not run"))


@pytest.mark.parametrize("day,has_seed", [("2014-06-03", True), (DAY, False)])
def test_stock_silver_binds_actual_seed_only_for_correction_dates(
    tmp_path, monkeypatch, day, has_seed
):
    """Wrapper argument boundary only; OS suites exercise the actual producer."""
    captured = {}

    class StopAfterBinding:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.directory = tmp_path / "operation"

        def run(self, _builder):
            raise RuntimeError("binding captured")

    monkeypatch.setattr(stk_mins, "MinutePartitionPublication", StopAfterBinding)
    monkeypatch.setattr(
        stk_mins,
        "load_stk_mins_price_correction_catalog",
        lambda: pytest.fail("wrapper must not parse catalog"),
    )
    with pytest.raises(RuntimeError, match="binding captured"):
        stk_mins.write_silver_stk_mins_partition(
            lake_root=tmp_path / "lake",
            duckdb=SimpleNamespace(),
            freq=1,
            partition_key=day,
        )
    assert (
        stk_mins.STK_MINS_PRICE_CORRECTIONS_SEED_PATH in captured["source_paths"]
    ) is has_seed
    assert captured["source_identity"][1:] == (
        "2026-09-12",
        ("600355.SH", "300344.SZ", "300391.SZ"),
    )
