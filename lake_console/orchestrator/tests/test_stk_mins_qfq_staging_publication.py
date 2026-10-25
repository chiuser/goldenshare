"""File-boundary failures plus real QFQ/MACD writers on isolated Parquet.

Inputs follow GOLD_STK_MINS_QFQ_SCHEMA and the existing canonical producers.
Literal prior-day values are independent expectations; filesystem tests replace
only the stated failure boundary, never the writer or its business validators.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from orchestrator.defs import stk_mins_qfq, stk_mins_qfq_macd_kdj
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io import stk_mins_qfq_publication as publication_module
from orchestrator.defs.io.stk_mins_qfq_publication import StkMinsQfqPublication
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    gold_stk_mins_qfq_path,
)

DAY = "2026-10-22"
PRIOR = "2026-10-21"
CODES = ("000001.SZ", "600000.SH")


def _sql(codes=CODES, *, day=DAY, price=10) -> str:
    return " UNION ALL ".join(
        f"""SELECT '{code}'::VARCHAR AS ts_code, 5::INTEGER AS freq,
        DATE '{day}' AS trade_date, TIMESTAMP '{day} 09:35:00' AS trade_time,
        {price}::DOUBLE AS open, {price + 1}::DOUBLE AS high,
        {price - 1}::DOUBLE AS low, {price}::DOUBLE AS close,
        100::DOUBLE AS vol, 1000::DOUBLE AS amount,
        '{"SSE" if code.endswith(".SH") else "SZSE"}'::VARCHAR AS exchange"""
        for code in codes
    )


def _write(root: Path, *, operation="operation", price=10):
    return stk_mins_qfq.write_gold_stk_mins_qfq_rows_to_year_files(
        lake_root=root,
        freq=5,
        qfq_select_sql=_sql(price=price),
        replace_trade_dates=(DAY,),
        publication_id=operation,
    )


def _target(root: Path, code=CODES[0]) -> Path:
    return gold_stk_mins_qfq_path(root, 5, code, 2026)


def _physical(path: Path):
    value = path.stat()
    return value.st_ino, value.st_mtime_ns, path.read_bytes()


def _rows(path: Path, columns="trade_date, close"):
    with duckdb.connect() as connection:
        return connection.execute(
            f"SELECT {columns} FROM {read_parquet(path, hive_partitioning=False)} "
            "ORDER BY trade_date"
        ).fetchall()


def _publication(root: Path, operation="operation"):
    return StkMinsQfqPublication(
        lake_root=root,
        family="qfq",
        freq=5,
        trade_dates=(DAY,),
        publication_id=operation,
    )


def test_qfq_real_writer_stages_and_preserves_literal_prior_rows(tmp_path):
    root = tmp_path / "lake"
    stk_mins_qfq.write_gold_stk_mins_qfq_rows_to_year_files(
        lake_root=root,
        freq=5,
        qfq_select_sql=_sql(day=PRIOR, price=9),
        replace_trade_dates=(PRIOR,),
    )
    copies = []
    original = stk_mins_qfq.copy_query_to_parquet

    def capture(sql, path):
        copies.append(path)
        return original(sql, path)

    with patch.object(stk_mins_qfq, "copy_query_to_parquet", side_effect=capture):
        result = _write(root)
    assert len(result) == 2
    assert all(not path.is_relative_to(root) for path in copies)
    assert all("candidates" in path.parts for path in copies)
    assert not list(root.rglob("*.tmp"))
    for code in CODES:
        assert [(str(day), close) for day, close in _rows(_target(root, code))] == [
            (PRIOR, 9.0),
            (DAY, 10.0),
        ]


def test_second_qfq_candidate_failure_never_changes_first_formal_file(tmp_path):
    root = tmp_path / "lake"
    _write(root, operation="seed", price=8)
    before = [_physical(_target(root, code)) for code in CODES]
    original = stk_mins_qfq._validate_written_year_file
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        row_count = original(*args, **kwargs)
        if calls == 2:
            raise RuntimeError("candidate validation interrupted")
        return row_count

    with (
        patch.object(
            stk_mins_qfq, "_validate_written_year_file", side_effect=fail_second
        ),
        pytest.raises(RuntimeError, match="interrupted"),
    ):
        _write(root)
    assert before == [_physical(_target(root, code)) for code in CODES]
    assert (
        len(list((tmp_path / "lake_staging").rglob("candidates/*/gold/**/*.parquet")))
        == 2
    )
    _write(root)
    assert all(_rows(_target(root, code))[0][1] == 10 for code in CODES)


@pytest.mark.parametrize("after_replace", [False, True])
def test_real_writer_resumes_both_sides_of_replace_without_rewriting_completed_file(
    tmp_path,
    after_replace,
):
    root = tmp_path / "lake"
    original = os.replace
    target = _target(root, CODES[1] if not after_replace else CODES[0])

    def interrupt(source, destination):
        if Path(destination) == target:
            if after_replace:
                original(source, destination)
            raise RuntimeError("process exited at replace boundary")
        return original(source, destination)

    with (
        patch.object(publication_module.os, "replace", side_effect=interrupt),
        pytest.raises(RuntimeError, match="process exited"),
    ):
        _write(root)
    first = _physical(_target(root))
    result = _write(root)
    assert len(result) == 2
    assert _physical(_target(root)) == first
    assert all(_rows(_target(root, code))[0][1] == 10 for code in CODES)


def test_same_inputs_replay_is_idempotent_and_changed_inputs_fail(tmp_path):
    root = tmp_path / "lake"
    _write(root)
    before = _physical(_target(root))
    _write(root)
    assert _physical(_target(root)) == before
    with pytest.raises(ValueError, match="inputs or targets changed"):
        _write(root, price=20)
    assert _physical(_target(root)) == before


def test_completed_target_external_change_is_rejected(tmp_path):
    root = tmp_path / "lake"
    _write(root)
    _target(root).write_bytes(b"external change")
    with pytest.raises(ValueError, match="Completed QFQ target changed"):
        _write(root)
    assert _target(root).read_bytes() == b"external change"


@pytest.mark.parametrize("damage", ["candidate", "target", "receipt"])
def test_pre_promotion_conflicts_stop_without_overwriting(tmp_path, damage):
    root = tmp_path / "lake"
    _write(root, operation="seed", price=8)
    formal = _target(root)
    before = _physical(formal)
    with _publication(root) as publication, duckdb.connect() as connection:
        publication.bind(
            connection, inputs={"rows": "SELECT 1 AS id"}, targets=(formal,)
        )
        candidate, _ = publication.candidate(formal)
        candidate.write_bytes(b"validated candidate")
        publication.validated(formal, candidate, 1)
        if damage == "candidate":
            candidate.write_bytes(b"damaged candidate")
        elif damage == "target":
            formal.write_bytes(b"external target")
        else:
            receipt_path = publication._receipt_path(formal)
            receipt = json.loads(receipt_path.read_text())
            receipt["target"] = str(root / "gold" / "wrong.parquet")
            receipt_path.write_text(json.dumps(receipt))
        with pytest.raises(ValueError):
            publication.promote()
    if damage == "target":
        assert formal.read_bytes() == b"external target"
    else:
        assert _physical(formal) == before


def test_incomplete_set_cannot_start_promotion(tmp_path):
    root = tmp_path / "lake"
    with _publication(root) as publication, duckdb.connect() as connection:
        paths = tuple(_target(root, code) for code in CODES)
        publication.bind(connection, inputs={"rows": "SELECT 1 AS id"}, targets=paths)
        candidate, _ = publication.candidate(paths[0])
        candidate.write_bytes(b"candidate")
        publication.validated(paths[0], candidate, 1)
        with pytest.raises(ValueError, match="not completely validated"):
            publication.promote()
        assert not any(path.exists() for path in paths)


def test_one_writer_across_dates_and_process_exit_releases_lock(tmp_path):
    root = tmp_path / "lake"
    with (
        _publication(root),
        pytest.raises(BlockingIOError),
        StkMinsQfqPublication(
            lake_root=root,
            family="qfq",
            freq=5,
            trade_dates=(PRIOR,),
            publication_id="another",
        ),
    ):
        pass
    source = """
import os,sys
from pathlib import Path
from orchestrator.defs.io.stk_mins_qfq_publication import StkMinsQfqPublication
with StkMinsQfqPublication(lake_root=Path(sys.argv[1]), family='qfq', freq=5,
                         trade_dates=('2026-10-22',), publication_id='child'):
    os._exit(7)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", source, str(root)], timeout=15, check=False
    )
    assert result.returncode == 7
    with _publication(root):
        pass


def test_symlink_escape_and_unapproved_root_fail(tmp_path):
    root = tmp_path / "lake"
    root.mkdir()
    (root / "gold").symlink_to(tmp_path / "outside")
    with (
        _publication(root) as publication,
        duckdb.connect() as connection,
        pytest.raises(ValueError, match="symlink"),
    ):
        publication.bind(
            connection, inputs={"rows": "SELECT 1 AS id"}, targets=(_target(root),)
        )
    with pytest.raises(ValueError, match="formal lake"):
        _publication(Path("/usr/unapproved-qfq-test-lake"))
    with (
        _publication(tmp_path / "separate") as publication,
        duckdb.connect() as connection,
        pytest.raises(ValueError),
    ):
        publication.bind(
            connection, inputs={"rows": "SELECT 1 AS id"}, targets=(_target(root),)
        )


def test_cross_device_check_and_space_shortage_fail_before_copy(tmp_path, monkeypatch):
    root = tmp_path / "lake"
    with _publication(root) as publication, duckdb.connect() as connection:
        formal = _target(root)
        publication.bind(
            connection, inputs={"rows": "SELECT 1 AS id"}, targets=(formal,)
        )
        original = Path.stat

        def other_device(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if "candidates" in path.parts and stat.S_ISDIR(value.st_mode):
                values = list(value)
                values[2] += 1
                return os.stat_result(values)
            return value

        # Only replace the st_dev observation; production guard still executes.
        with (
            patch.object(Path, "stat", other_device),
            pytest.raises(ValueError, match="same filesystem"),
        ):
            publication.candidate(formal)
        assert not formal.exists()
    usage = publication_module.shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        publication_module.shutil, "disk_usage", lambda _: usage._replace(free=0)
    )
    with (
        _publication(root, "space") as publication,
        duckdb.connect() as connection,
        pytest.raises(OSError, match="Insufficient"),
    ):
        publication.bind(
            connection, inputs={"rows": "SELECT 1 AS id"}, targets=(formal,)
        )


def test_macd_state_failure_preserves_annual_output_then_resumes(tmp_path):
    root = tmp_path / "lake"
    stk_mins_qfq.write_gold_stk_mins_qfq_rows_to_year_files(
        lake_root=root,
        freq=5,
        qfq_select_sql=_sql(day=PRIOR),
        replace_trade_dates=(PRIOR,),
    )
    _write(root, operation="source")
    source_paths = tuple(_target(root, code) for code in CODES)
    _, previous_states, _ = stk_mins_qfq_macd_kdj.write_gold_stk_mins_qfq_macd_kdj_rows(
        lake_root=root,
        freq=5,
        source_qfq_paths=source_paths,
        target_trade_dates=(PRIOR,),
    )
    prior = previous_states[0].path
    indicator = gold_stk_mins_qfq_macd_kdj_path(root, 5, CODES[0], 2026)
    before = _physical(indicator)
    arguments = {
        "lake_root": root,
        "freq": 5,
        "source_qfq_paths": source_paths,
        "target_trade_dates": (DAY,),
        "previous_state_paths": (prior,),
        "publication_id": "macd",
    }
    with (
        patch.object(
            stk_mins_qfq_macd_kdj,
            "_write_state_partition_file",
            side_effect=RuntimeError("state build interrupted"),
        ),
        pytest.raises(RuntimeError, match="state build"),
    ):
        stk_mins_qfq_macd_kdj.write_gold_stk_mins_qfq_macd_kdj_rows(**arguments)
    assert _physical(indicator) == before
    state = gold_stk_mins_qfq_macd_kdj_state_path(root, 5, DAY)
    assert not state.exists()
    indicators, states, _ = stk_mins_qfq_macd_kdj.write_gold_stk_mins_qfq_macd_kdj_rows(
        **arguments
    )
    assert len(indicators) == 2 and len(states) == 1
    assert [str(row[0]) for row in _rows(indicator, "trade_date")] == [PRIOR, DAY]
    # Constant close has analytic DIF=0; allow ordinary DOUBLE EMA rounding.
    assert all(
        value == pytest.approx(0, abs=1e-12)
        for (value,) in _rows(indicator, "macd_dif_qfq")
    )
    before = _physical(indicator), _physical(state)
    stk_mins_qfq_macd_kdj.write_gold_stk_mins_qfq_macd_kdj_rows(**arguments)
    assert (_physical(indicator), _physical(state)) == before
    assert not list(root.rglob("*.tmp"))


def test_original_target_side_temporary_paths_are_removed():
    for module in (stk_mins_qfq, stk_mins_qfq_macd_kdj):
        assert "def _temp_path_for" not in Path(module.__file__).read_text()


def test_real_process_exit_after_replace_resumes_from_persisted_receipt(tmp_path):
    root = tmp_path / "lake"
    source = """
import os,sys
from pathlib import Path
from orchestrator.defs.stk_mins_qfq import write_gold_stk_mins_qfq_rows_to_year_files
from orchestrator.defs.io import stk_mins_qfq_publication as publication
root=Path(sys.argv[1])
# The child must use its own isolated temp setting, just as the parent does.
from dataclasses import replace
from orchestrator.defs import duckdb_connection
settings=replace(duckdb_connection.DEFAULT_DUCKDB_CONNECTION_SETTINGS,
    temp_directory=root.parent.resolve() / 'child-duckdb')
settings.temp_directory.mkdir(exist_ok=True)
duckdb_connection.connect_configured_duckdb.__wrapped__.__defaults__=(settings,)
original=os.replace
def exit_after_replace(source,target):
    original(source,target)
    if Path(target).is_relative_to(root) and Path(target).suffix=='.parquet':
        os._exit(17)
publication.os.replace=exit_after_replace
write_gold_stk_mins_qfq_rows_to_year_files(lake_root=root, freq=5,
    qfq_select_sql=sys.argv[2], replace_trade_dates=('2026-10-22',),
    publication_id='operation')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", source, str(root), _sql()],
        timeout=15,
        check=False,
    )
    assert result.returncode == 17
    completed = _physical(_target(root))
    _write(root)
    assert _physical(_target(root)) == completed
    assert all(_rows(_target(root, code))[0][1] == 10 for code in CODES)


def test_existing_specialist_candidate_root_stays_in_staging(tmp_path, monkeypatch):
    formal = tmp_path / "formal"
    staging = tmp_path / "staging"
    formal.mkdir()
    staging.mkdir()
    candidate_root = staging / "specialist" / "candidates"
    candidate_root.mkdir(parents=True)
    monkeypatch.setattr(publication_module, "DEFAULT_LAKE_ROOT", str(formal))
    monkeypatch.setattr(publication_module, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    result = _write(candidate_root)
    assert len(result) == 2
    assert all(item.path.is_relative_to(staging) for item in result)
    assert not list(formal.rglob("*.parquet"))
    assert list(staging.rglob("operation.json"))


def test_symlink_in_destination_root_ancestor_is_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        _publication(alias / "lake")


def test_resume_does_not_reserve_another_complete_annual_copy(tmp_path, monkeypatch):
    root = tmp_path / "lake"
    target = _target(root)
    with _publication(root) as publication, duckdb.connect() as connection:
        publication.bind(
            connection, inputs={"rows": "SELECT 1 AS id"}, targets=(target,)
        )
        candidate, _ = publication.candidate(target)
        candidate.write_bytes(b"x" * (8 * 1024 * 1024))
        publication.validated(target, candidate, 1)
        publication.promote()
    usage = publication_module.shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        publication_module.shutil,
        "disk_usage",
        lambda _: usage._replace(free=65 * 1024 * 1024),
    )
    before = _physical(target)
    with _publication(root) as publication, duckdb.connect() as connection:
        publication.bind(
            connection, inputs={"rows": "SELECT 1 AS id"}, targets=(target,)
        )
        assert publication.candidate(target) == (None, 1)
        publication.promote()
    assert _physical(target) == before


def test_receipt_directory_failure_releases_acquired_writer_lock(tmp_path):
    publication = _publication(tmp_path / "lake")
    publication.directory.mkdir(parents=True)
    obstruction = publication.directory / "files"
    obstruction.write_text("not a directory")
    with pytest.raises(FileExistsError):
        publication.__enter__()
    assert publication.descriptor is None
    obstruction.unlink()  # Only the obstruction created by this isolated fixture.
    with _publication(tmp_path / "lake"):
        pass
