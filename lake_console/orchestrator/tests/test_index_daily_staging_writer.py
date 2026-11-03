"""Actual date writers plus isolated failures at publication boundaries.

Raw fields follow RAW_INDEX_DAILY_SCHEMA; the eleven codes are the versioned
major_indices.cn_a.csv, not generated from the writer's result. Prices below are
literal expectations. No production database, Lake, instance or source calls.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import duckdb
import pytest

from orchestrator.defs.assets import index_daily, market_major_indices
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io import index_daily_writer as writer
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_market_major_indices_daily_path,
    raw_index_daily_path,
    raw_index_daily_staging_path,
    silver_index_daily_path,
)

DAY = "2026-10-22"
CODES = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "899050.BJ",
    "000510.SH",
    "000016.SH",
    "000680.SH",
)


@pytest.fixture(autouse=True)
def isolate_staging(tmp_path, monkeypatch):
    monkeypatch.setattr(writer, "gettempdir", lambda: str(tmp_path))


def _raw(tmp_path, *, price=10.0, duplicate=False):
    path = tmp_path / "raw.parquet"
    if path.exists():
        path.unlink()  # Only this fixture's synthetic source, never a business table/file.
    codes = CODES + CODES[:1] if duplicate else CODES
    rows = ",".join(f"('{code}')" for code in codes)
    sql = f"""SELECT ts_code::VARCHAR AS ts_code,'20261022'::VARCHAR AS trade_date,
        {price}::DOUBLE AS open,11::DOUBLE AS high,9::DOUBLE AS low,10.5::DOUBLE AS close,
        10::DOUBLE AS pre_close,0.5::DOUBLE AS change,5::DOUBLE AS pct_chg,
        100::DOUBLE AS vol,1000::DOUBLE AS amount FROM (VALUES {rows}) AS codes(ts_code)"""
    with duckdb.connect() as connection:
        connection.execute(copy_query_to_parquet(sql, path))
    return path


def _silver(tmp_path, *, operation="operation", raw=None):
    raw = raw or tmp_path / "raw.parquet"
    target = silver_index_daily_path(tmp_path / "lake", DAY)
    with duckdb.connect() as connection:
        return index_daily.write_silver_index_daily_partition_from_raw_file(
            connection,
            raw_path=raw,
            target_path=target,
            partition_key=DAY,
            publication_id=operation,
        )


def _gold(tmp_path, *, operation="operation"):
    target = gold_market_major_indices_daily_path(tmp_path / "lake", DAY)
    with duckdb.connect() as connection:
        count = market_major_indices.create_major_indices_seed_table(connection)
        return market_major_indices.write_gold_market_major_indices_daily_partition(
            connection,
            seed_table_name="major_indices_seed",
            seed_count=count,
            silver_path=silver_index_daily_path(tmp_path / "lake", DAY),
            target_path=target,
            partition_key=DAY,
            publication_id=operation,
        )


def _physical(path):
    value = path.stat()
    return value.st_ino, value.st_mtime_ns, path.read_bytes()


def _target(tmp_path, dataset):
    return (
        silver_index_daily_path
        if dataset == "silver"
        else gold_market_major_indices_daily_path
    )(
        tmp_path / "lake",
        DAY,
    )


def _run(tmp_path, dataset):
    return _silver(tmp_path) if dataset == "silver" else _gold(tmp_path)


def _prepare(tmp_path, dataset):
    _raw(tmp_path)
    if dataset == "gold":
        _silver(tmp_path)


def test_actual_two_writers_keep_values_duplicates_seed_and_staging(tmp_path):
    _raw(tmp_path, duplicate=True)
    result = _silver(tmp_path)
    assert result.source_row_count == 12
    assert result.duplicate_removed_count == 1
    assert result.output_row_count == 11
    gold = _gold(tmp_path)
    assert gold["output_row_count"] == 11 and gold["active_seed_row_count"] == 11
    with duckdb.connect() as connection:
        rows = connection.execute(
            f"SELECT rank,ts_code,close,change_amount FROM {read_parquet(_target(tmp_path, 'gold'), hive_partitioning=False)} ORDER BY rank"
        ).fetchall()
    assert rows == [(rank, code, 10.5, 0.5) for rank, code in enumerate(CODES, start=1)]
    for receipt_path in tmp_path.rglob("receipt.json"):
        receipt = json.loads(receipt_path.read_text())
        assert "goldenshare_index_daily_staging" in receipt_path.parts
        assert receipt["status"] == "promoted"
        assert not Path(receipt["candidate"]).is_relative_to(tmp_path / "lake")
    assert not list((tmp_path / "lake").rglob("*.tmp"))


@pytest.mark.parametrize("dataset", ["silver", "gold"])
@pytest.mark.parametrize("after_replace", [False, True])
def test_interruption_on_both_sides_of_replace_then_idempotent_resume(
    tmp_path, dataset, after_replace
):
    _prepare(tmp_path, dataset)
    target = _target(tmp_path, dataset)
    original = os.replace

    def interrupt(source, destination):
        if Path(destination) == target:
            if after_replace:
                original(source, destination)
            raise RuntimeError("interrupted at replace")
        return original(source, destination)

    with (
        patch.object(writer.os, "replace", side_effect=interrupt),
        pytest.raises(RuntimeError, match="interrupted"),
    ):
        _run(tmp_path, dataset)
    before = _physical(target) if after_replace else None
    _run(tmp_path, dataset)
    if before is not None:
        assert _physical(target) == before
    completed = _physical(target)
    _run(tmp_path, dataset)
    assert _physical(target) == completed


@pytest.mark.parametrize("dataset", ["silver", "gold"])
def test_validation_failure_preserves_previous_target_and_candidate(tmp_path, dataset):
    _prepare(tmp_path, dataset)
    if dataset == "silver":
        _silver(tmp_path, operation="seed")
    else:
        _gold(tmp_path, operation="seed")
    target = _target(tmp_path, dataset)
    before = _physical(target)
    with (
        patch.object(
            writer, "_validate_candidate", side_effect=ValueError("invalid candidate")
        ),
        pytest.raises(ValueError, match="invalid candidate"),
    ):
        _run(tmp_path, dataset)
    assert _physical(target) == before
    assert any(p.is_file() for p in tmp_path.rglob("attempt=*/part-000.parquet"))
    _run(tmp_path, dataset)


@pytest.mark.parametrize("damage", ["candidate", "target", "input", "receipt"])
def test_resume_rejects_conflicts(tmp_path, damage):
    _prepare(tmp_path, "silver")
    target = _target(tmp_path, "silver")
    original = os.replace

    def interrupt(source, destination):
        if Path(destination) == target:
            raise RuntimeError("interrupted")
        return original(source, destination)

    with (
        patch.object(writer.os, "replace", side_effect=interrupt),
        pytest.raises(RuntimeError),
    ):
        _silver(tmp_path)
    receipt_path = next(tmp_path.rglob("receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    if damage == "candidate":
        Path(receipt["candidate"]).write_bytes(b"damaged")
    elif damage == "target":
        target.write_bytes(b"external target")
    elif damage == "input":
        _raw(tmp_path, price=9)
    else:
        receipt["target"] = str(target.with_name("wrong.parquet"))
        receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        _silver(tmp_path)
    if damage == "target":
        assert target.read_bytes() == b"external target"
    else:
        assert not target.exists()


def test_candidate_contract_checks_wrong_schema_date_and_rows(tmp_path):
    path = tmp_path / "candidate.parquet"
    with duckdb.connect() as connection:
        connection.execute(copy_query_to_parquet("SELECT 1 AS wrong", path))
        with pytest.raises(ValueError, match="schema"):
            writer._validate_candidate(
                connection, path, dataset="silver_index_daily", day=DAY, expected_rows=1
            )
    _raw(tmp_path)
    _silver(tmp_path)
    path = _target(tmp_path, "silver")
    with duckdb.connect() as connection:
        for day, expected in [("2026-10-21", 11), (DAY, 12)]:
            with pytest.raises(ValueError, match="row count or target date"):
                writer._validate_candidate(
                    connection,
                    path,
                    dataset="silver_index_daily",
                    day=day,
                    expected_rows=expected,
                )


def test_lock_and_initialization_failure_release_lock(tmp_path, monkeypatch):
    namespace = tmp_path / "lock"
    with (
        writer._writer_lock(namespace),
        pytest.raises(BlockingIOError),
        writer._writer_lock(namespace),
    ):
        pass
    _raw(tmp_path)
    original = Path.mkdir

    def fail_operation_directory(path, *args, **kwargs):
        if path.name.startswith("run_id="):
            raise PermissionError("initialization failed")
        return original(path, *args, **kwargs)

    with (
        patch.object(Path, "mkdir", fail_operation_directory),
        pytest.raises(PermissionError),
    ):
        _silver(tmp_path)
    _silver(tmp_path)


def test_symlink_wrong_root_cross_device_and_low_space(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="formal lake"):
        writer._staging_base(
            Path("/Volumes/unapproved/target.parquet"), "silver_index_daily", DAY
        )
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "other")
    with pytest.raises(ValueError, match="symlink"):
        writer._staging_base(alias / "part.parquet", "silver_index_daily", DAY)
    _raw(tmp_path)
    original = Path.stat

    def other_device(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if any(p.startswith("attempt=") for p in path.parts) and stat.S_ISDIR(
            value.st_mode
        ):
            fields = list(value)
            fields[2] += 1
            return os.stat_result(fields)
        return value

    with (
        patch.object(Path, "stat", other_device),
        pytest.raises(ValueError, match="filesystem"),
    ):
        _silver(tmp_path)
    assert not _target(tmp_path, "silver").exists()
    usage = writer.shutil.disk_usage(tmp_path)
    monkeypatch.setattr(writer.shutil, "disk_usage", lambda _: usage._replace(free=0))
    with pytest.raises(OSError, match="Insufficient"):
        _silver(tmp_path, operation="low-space")


def test_real_process_exit_after_replace_resumes_without_rewriting(tmp_path):
    _raw(tmp_path)
    source = """
import os,sys,duckdb
from pathlib import Path
from orchestrator.defs.assets.index_daily import write_silver_index_daily_partition_from_raw_file
from orchestrator.defs.io import index_daily_writer as writer
root=Path(sys.argv[1]);target=Path(sys.argv[2]);original=os.replace
def exit_after_replace(source,destination):
    original(source,destination)
    if Path(destination)==target:os._exit(17)
writer.os.replace=exit_after_replace
with duckdb.connect() as connection:
    write_silver_index_daily_partition_from_raw_file(connection,raw_path=root/'raw.parquet',
        target_path=target,partition_key='2026-10-22',publication_id='operation')
"""
    target = _target(tmp_path, "silver")
    result = subprocess.run(
        [sys.executable, "-B", "-c", source, str(tmp_path), str(target)],
        env={**os.environ, "TMPDIR": str(tmp_path)},
        timeout=15,
        check=False,
    )
    assert result.returncode == 17
    before = _physical(target)
    _silver(tmp_path)
    assert _physical(target) == before


def test_old_private_target_side_tmp_writers_removed():
    for module in (index_daily, market_major_indices):
        assert (
            "def _replace_parquet_from_query" not in Path(module.__file__).read_text()
        )


def _publish_raw(root, operation="operation"):
    return index_daily._write_raw_index_daily_rows_from_prod_db_source(
        duckdb=SimpleNamespace(
            connect=lambda: duckdb.connect(
                config={
                    "temp_directory": str(root / "duckdb"),
                    "memory_limit": "128MB",
                    "max_temp_directory_size": "0B",
                    "threads": "1",
                }
            )
        ),
        source_sql=f"SELECT * FROM {read_parquet(root / 'raw.parquet', hive_partitioning=False)}",
        target_path=raw_index_daily_path(root / "lake", DAY),
        staging_path=raw_index_daily_staging_path(root / "lake", operation, DAY),
        index_codes=CODES,
        partition_key=DAY,
        load_postgres_extension=False,
    )


def test_raw_formal_staging_path_uses_external_root_and_rejects_bad_identity():
    path = raw_index_daily_staging_path(Path(DEFAULT_LAKE_ROOT), "run-1", DAY)
    assert path == (
        Path(DEFAULT_LAKE_STAGING_ROOT)
        / "index_daily/raw_index_daily/run_id=run-1"
        / f"trade_date={DAY}/part-000.parquet"
    )
    assert not path.is_relative_to(DEFAULT_LAKE_ROOT)
    for operation in ("", "..", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            raw_index_daily_staging_path(DEFAULT_LAKE_ROOT, operation, DAY)
    with pytest.raises(ValueError):
        raw_index_daily_staging_path(DEFAULT_LAKE_ROOT, "run-1", "20261022")


@pytest.mark.parametrize("after_replace", [False, True])
def test_raw_interruption_preserves_candidate_and_resumes(tmp_path, after_replace):
    _raw(tmp_path)
    target = raw_index_daily_path(tmp_path / "lake", DAY)
    original = os.replace

    def interrupt(source, destination):
        if Path(destination) == target:
            if after_replace:
                original(source, destination)
            raise RuntimeError("raw interrupted")
        return original(source, destination)

    with (
        patch.object(writer.os, "replace", side_effect=interrupt),
        pytest.raises(RuntimeError, match="raw interrupted"),
    ):
        _publish_raw(tmp_path)
    before = _physical(target) if after_replace else None
    result = _publish_raw(tmp_path)
    assert result.row_count == 11 and result.expected_code_count == 11
    assert result.missing_code_count == result.extra_code_count == 0
    completed = _physical(target)
    if before is not None:
        assert completed == before
    _publish_raw(tmp_path)
    assert _physical(target) == completed
    with duckdb.connect() as connection:
        observed = connection.execute(
            f"SELECT ts_code,trade_date,open FROM {read_parquet(target, hive_partitioning=False)} ORDER BY ts_code"
        ).fetchall()
    assert observed == [(code, "20261022", 10.0) for code in sorted(CODES)]


def test_raw_same_count_changed_values_reject_resume(tmp_path):
    _raw(tmp_path)
    _publish_raw(tmp_path)
    target = raw_index_daily_path(tmp_path / "lake", DAY)
    before = _physical(target)
    _raw(tmp_path, price=10.25)
    with pytest.raises(ValueError, match="inputs or target changed"):
        _publish_raw(tmp_path)
    assert _physical(target) == before
    _publish_raw(tmp_path, operation="changed-source-independent-run")
    assert _physical(target) != before


def test_raw_candidate_validator_runs_before_replace_and_failed_files_survive(tmp_path):
    _raw(tmp_path)
    _publish_raw(tmp_path, operation="seed")
    target = raw_index_daily_path(tmp_path / "lake", DAY)
    before = _physical(target)
    anchor = raw_index_daily_staging_path(tmp_path / "lake", "operation", DAY)
    anchor.parent.mkdir(parents=True)
    anchor.write_bytes(b"previous failed candidate")
    with (
        patch.object(
            index_daily,
            "_assert_raw_index_daily_staging_contract",
            side_effect=RuntimeError("bad raw candidate"),
        ),
        pytest.raises(RuntimeError, match="bad raw candidate"),
    ):
        _publish_raw(tmp_path)
    assert _physical(target) == before
    assert anchor.read_bytes() == b"previous failed candidate"
    failed = list(anchor.parent.glob("attempt=*/part-000.parquet"))
    assert len(failed) == 1
    _publish_raw(tmp_path)
    assert failed[0].exists()
    assert anchor.read_bytes() == b"previous failed candidate"


def test_raw_requires_business_identity_and_validator(tmp_path):
    with (
        duckdb.connect() as connection,
        pytest.raises(ValueError, match="source identity and candidate validation"),
    ):
        writer.write_index_daily_partition(
            connection,
            "SELECT 1",
            dataset="raw_index_daily",
            partition_key=DAY,
            target_path=raw_index_daily_path(tmp_path / "lake", DAY),
            source_paths=(),
            expected_rows=1,
        )


def test_raw_real_process_exit_after_replace_resumes(tmp_path):
    _raw(tmp_path)
    source = """
import os,sys,duckdb
from types import SimpleNamespace
from pathlib import Path
from orchestrator.defs.assets.index_daily import _write_raw_index_daily_rows_from_prod_db_source
from orchestrator.defs.io import index_daily_writer as writer
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import raw_index_daily_staging_path
root=Path(sys.argv[1]);target=Path(sys.argv[2]);original=os.replace
def exit_after_replace(source,destination):
    original(source,destination)
    if Path(destination)==target:os._exit(17)
writer.os.replace=exit_after_replace
_write_raw_index_daily_rows_from_prod_db_source(duckdb=SimpleNamespace(connect=lambda:duckdb.connect(config={
    'temp_directory':str(root/'duckdb'),'memory_limit':'128MB','threads':'1','max_temp_directory_size':'0B'})),
    source_sql=f"SELECT * FROM {read_parquet(root/'raw.parquet',hive_partitioning=False)}",
    target_path=target,staging_path=raw_index_daily_staging_path(root/'lake','operation','2026-10-22'),
    index_codes=tuple(sys.argv[3:]),partition_key='2026-10-22',load_postgres_extension=False)
"""
    target = raw_index_daily_path(tmp_path / "lake", DAY)
    result = subprocess.run(
        [sys.executable, "-B", "-c", source, str(tmp_path), str(target), *CODES],
        env={**os.environ, "TMPDIR": str(tmp_path)},
        timeout=15,
        check=False,
    )
    assert result.returncode == 17
    before = _physical(target)
    _publish_raw(tmp_path)
    assert _physical(target) == before
