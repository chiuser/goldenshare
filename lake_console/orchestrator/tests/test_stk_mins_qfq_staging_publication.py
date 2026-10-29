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
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io import stk_mins_qfq_publication as publication_module
from orchestrator.defs.io.stk_mins_qfq_publication import StkMinsQfqPublication
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    gold_stk_mins_qfq_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
)

DAY = "2026-10-22"
PRIOR = "2026-10-21"
CODES = ("000001.SZ", "600000.SH")


@pytest.fixture(autouse=True)
def isolated_writer_connections(tmp_path, monkeypatch):
    """Replace only connection configuration; every real SQL/writer still runs.

    The public MACD daily wrapper has no settings input. Neither it nor older
    tests in this file may create the production DuckDB temporary directory.
    """
    directory = tmp_path / "duckdb"
    directory.mkdir()
    settings = DuckDBConnectionSettings(
        temp_directory=directory,
        memory_limit="128MiB",
        max_temp_directory_size="64MiB",
        threads=1,
    )

    def isolated(*_args, **kwargs):
        return connect_configured_duckdb(settings, **kwargs)

    monkeypatch.setattr(stk_mins_qfq, "connect_configured_duckdb", isolated)
    monkeypatch.setattr(stk_mins_qfq_macd_kdj, "connect_configured_duckdb", isolated)


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


def _write_contract_rows(path, schema, rows, *, order_by):
    """Fixture layout comes from the real producers' current column contracts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column.name for column in schema)
    definitions = ", ".join(f'"{column.name}" {column.type}' for column in schema)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(f"CREATE TEMP TABLE fixture_rows ({definitions})")
        connection.executemany(
            f"INSERT INTO fixture_rows VALUES ({', '.join('?' for _ in columns)})",
            [[row[column] for column in columns] for row in rows],
        )
        connection.execute(
            f"COPY (SELECT * FROM fixture_rows ORDER BY {order_by}) "
            "TO ? (FORMAT PARQUET)",
            [str(path)],
        )


def _daily_inputs(tmp_path, *, codes=CODES, include_suspended=False):
    """Two-year contracts, three date sentinels, and a suspended state-only code.

    Quote rows are produced by the actual QFQ writer. Historical indicator
    numbers are independent literal sentinels: this fixture tests preservation,
    not historical formula acceptance. Previous state is also literal, and
    constant close=10 with HHV/LLV=11/9 gives current DIF/DEA/MACD=0, K/D/J=50.
    """
    root = tmp_path / "daily-lake"
    after = "2026-10-23"
    source_sql = " UNION ALL ".join(
        _sql(codes=codes, day=day, price=10) for day in (PRIOR, DAY, after)
    )
    stk_mins_qfq.write_gold_stk_mins_qfq_rows_to_year_files(
        lake_root=root,
        freq=5,
        qfq_select_sql=source_sql,
        replace_trade_dates=(PRIOR, DAY, after),
    )
    params_key = "macd_12_26_9__kdj_9_3_3"
    for code in codes:
        old_rows = []
        for day, marker in ((PRIOR, 1.0), (after, 2.0)):
            old_rows.append({
                "ts_code": code, "freq": 5, "trade_date": day,
                "trade_time": f"{day} 09:35:00",
                "macd_dif_qfq": marker,
                "macd_dea_qfq": marker / 4,
                "macd_qfq": 1.5 * marker,
                "kdj_k_qfq": 10.0,
                "kdj_d_qfq": 20.0,
                "kdj_qfq": -10.0,
                "params_key": params_key, "indicator_version": 1,
            })
        _write_contract_rows(
            gold_stk_mins_qfq_macd_kdj_path(root, 5, code, 2026),
            GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA, old_rows, order_by="trade_time",
        )
    state_rows = [{
        "ts_code": code, "freq": 5, "trade_date": PRIOR,
        "last_trade_time": f"{PRIOR} 09:35:00",
        "macd_ema_fast": 10.0, "macd_ema_slow": 10.0, "macd_dea": 0.0,
        "kdj_k": 50.0, "kdj_d": 50.0,
        "params_key": params_key, "indicator_version": 1,
    } for code in codes]
    if include_suspended:
        state_rows.append({
            **state_rows[0], "ts_code": "300001.SZ",
            "last_trade_time": "2025-12-31 09:35:00",
            "macd_ema_fast": 9.0, "macd_ema_slow": 8.0,
            "macd_dea": 1.0, "kdj_k": 61.0, "kdj_d": 42.0,
        })
    prior_state = gold_stk_mins_qfq_macd_kdj_state_path(root, 5, PRIOR)
    _write_contract_rows(
        prior_state, GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA, state_rows,
        order_by="ts_code",
    )
    return root, prior_state


def _daily(root, *, operation="daily-publication"):
    return stk_mins_qfq_macd_kdj.write_gold_stk_mins_qfq_macd_kdj_asset_partition(
        lake_root=root, freq=5, partition_key=DAY,
        previous_expected_trade_date=PRIOR,
        allow_without_previous_state=False,
        publication_id=operation,
    )


def _daily_targets(root, codes=CODES):
    return tuple(
        gold_stk_mins_qfq_macd_kdj_path(root, 5, code, 2026)
        for code in codes
    ) + (gold_stk_mins_qfq_macd_kdj_state_path(root, 5, DAY),)


def _replace_same_bytes(path):
    """Simulate an external atomic rewrite, even though byte length is equal."""
    replacement = path.with_name("fixture-replacement.parquet")
    replacement.write_bytes(path.read_bytes())
    os.replace(replacement, path)


def test_daily_one_complete_publication_preserves_history_state_and_is_idempotent(
    tmp_path,
):
    codes = CODES[:1]
    root, prior = _daily_inputs(tmp_path, codes=codes, include_suspended=True)
    prior_before = _physical(prior)
    old_rows = {
        code: _rows(gold_stk_mins_qfq_macd_kdj_path(root, 5, code, 2026), "*")
        for code in codes
    }
    binds = []
    original_bind = StkMinsQfqPublication.bind

    def capture_bind(publication, connection, **kwargs):
        if publication.scope["family"] == "macd_kdj":
            binds.append(kwargs["targets"])
        return original_bind(publication, connection, **kwargs)

    with patch.object(StkMinsQfqPublication, "bind", capture_bind):
        result = _daily(root)
    assert binds == [_daily_targets(root, codes)]
    assert result.indicator_row_count == 1
    assert result.state_row_count == 2
    assert _physical(prior) == prior_before
    for code in codes:
        path = gold_stk_mins_qfq_macd_kdj_path(root, 5, code, 2026)
        rows = _rows(path, "*")
        assert [row for row in rows if str(row[2]) != DAY] == old_rows[code]
        current = next(row for row in rows if str(row[2]) == DAY)
        assert current[4:7] == pytest.approx((0, 0, 0), abs=1e-12)
        assert current[7:10] == pytest.approx((50, 50, 50), abs=1e-12)
    state = _daily_targets(root, codes)[-1]
    old_suspended = next(row for row in _rows(prior, "*") if row[0] == "300001.SZ")
    suspended = next(row for row in _rows(state, "*") if row[0] == "300001.SZ")
    assert str(suspended[2]) == DAY
    assert suspended[:2] + suspended[3:] == old_suspended[:2] + old_suspended[3:]
    before = {path: _physical(path) for path in _daily_targets(root, codes)}
    _daily(root)
    assert {path: _physical(path) for path in before} == before
    assert _physical(prior) == prior_before
    assert not list(root.rglob("*.tmp"))


def test_daily_publication_lock_covers_input_preparation(tmp_path):
    root, _prior = _daily_inputs(tmp_path)
    prepare = stk_mins_qfq_macd_kdj._prepare_daily_macd_kdj_replacement_tables
    observed = []

    def locked_prepare(*args, **kwargs):
        with (
            pytest.raises(BlockingIOError),
            StkMinsQfqPublication(
                lake_root=root, family="macd_kdj", freq=5,
                trade_dates=(PRIOR,), publication_id="concurrent-writer",
            ),
        ):
            pass
        observed.append(True)
        return prepare(*args, **kwargs)

    with patch.object(
        stk_mins_qfq_macd_kdj,
        "_prepare_daily_macd_kdj_replacement_tables",
        side_effect=locked_prepare,
    ):
        _daily(root)
    assert observed == [True]


def test_daily_multiple_stock_batches_still_bind_one_complete_target_set(tmp_path):
    # The approved batch-boundary fixture is 65 stocks with only three rows each.
    codes = tuple(f"{index:06d}.SZ" for index in range(1, 66))
    root, prior = _daily_inputs(tmp_path, codes=codes)
    prior_before = _physical(prior)
    binds = []
    original_bind = StkMinsQfqPublication.bind

    def capture_bind(publication, connection, **kwargs):
        binds.append(kwargs["targets"])
        return original_bind(publication, connection, **kwargs)

    with patch.object(StkMinsQfqPublication, "bind", capture_bind):
        result = _daily(root)
    assert binds == [_daily_targets(root, codes)]
    assert result.indicator_row_count == 65
    assert result.state_row_count == 65
    assert len(binds[0]) == 66
    assert _physical(prior) == prior_before


def test_daily_old_frozen_input_conflict_does_not_invalidate_formal_history(tmp_path):
    root, prior = _daily_inputs(tmp_path)
    _daily(root)
    targets = _daily_targets(root)
    before = {path: _physical(path) for path in (*targets, prior)}
    # A real producer update changes the subsequent replacement values. Reusing
    # the original daily publication must reject its old frozen input digest.
    stk_mins_qfq.write_gold_stk_mins_qfq_rows_to_year_files(
        lake_root=root,
        freq=5,
        qfq_select_sql=_sql(price=20),
        replace_trade_dates=(DAY,),
    )
    with pytest.raises(ValueError, match="inputs or targets changed"):
        _daily(root)
    assert {path: _physical(path) for path in before} == before
    for path in targets:
        assert _rows(path, "trade_date")


def test_daily_second_candidate_failure_preserves_all_formal_results_then_resumes(
    tmp_path,
):
    root, prior = _daily_inputs(tmp_path)
    targets = _daily_targets(root)
    before = {path: _physical(path) for path in targets[:-1]}
    prior_before = _physical(prior)
    validated = StkMinsQfqPublication.validated
    calls = []

    def fail_second(publication, *args, **kwargs):
        result = validated(publication, *args, **kwargs)
        calls.append(args[0])
        if len(calls) == 2:
            raise RuntimeError("daily candidate interrupted")
        return result

    with (
        patch.object(StkMinsQfqPublication, "validated", fail_second),
        pytest.raises(RuntimeError, match="daily candidate interrupted"),
    ):
        _daily(root)
    assert len(calls) == 2
    assert {path: _physical(path) for path in before} == before
    assert _physical(prior) == prior_before
    assert not targets[-1].exists()
    assert list((tmp_path / "daily-lake_staging").rglob("candidates/*/gold/**/*.parquet"))
    _daily(root)
    assert targets[-1].exists()
    assert _physical(prior) == prior_before


@pytest.mark.parametrize("after_replace", [False, True])
def test_daily_resumes_both_replace_boundaries_without_rewriting_completed_file(
    tmp_path, after_replace,
):
    root, prior = _daily_inputs(tmp_path)
    targets = _daily_targets(root)
    prior_before = _physical(prior)
    original_replace = os.replace
    stop_target = targets[0] if after_replace else targets[1]

    def interrupt(source, destination):
        if Path(destination) == stop_target:
            if after_replace:
                original_replace(source, destination)
            raise RuntimeError("daily process exited at replace")
        return original_replace(source, destination)

    with (
        patch.object(publication_module.os, "replace", side_effect=interrupt),
        pytest.raises(RuntimeError, match="daily process exited"),
    ):
        _daily(root)
    first = _physical(targets[0])
    _daily(root)
    assert _physical(targets[0]) == first
    assert targets[-1].exists()
    assert _physical(prior) == prior_before


def test_daily_changed_source_during_computation_stops_before_bind(tmp_path):
    root, prior = _daily_inputs(tmp_path)
    targets = _daily_targets(root)
    before = {path: _physical(path) for path in targets[:-1]}
    source = gold_stk_mins_qfq_path(root, 5, CODES[0], 2026)
    calculate = stk_mins_qfq_macd_kdj._populate_macd_kdj_indicator_work_rows

    def changed_after_calculation(*args, **kwargs):
        result = calculate(*args, **kwargs)
        _replace_same_bytes(source)
        return result

    with (
        patch.object(
            stk_mins_qfq_macd_kdj, "_populate_macd_kdj_indicator_work_rows",
            side_effect=changed_after_calculation,
        ),
        patch.object(StkMinsQfqPublication, "bind") as bind,
        pytest.raises(RuntimeError, match="source file changed"),
    ):
        _daily(root)
    bind.assert_not_called()
    assert {path: _physical(path) for path in before} == before
    assert prior.exists() and not targets[-1].exists()
    macd_staging = tmp_path / "daily-lake_staging" / "stk_mins_qfq" / "macd_kdj"
    assert not list(macd_staging.rglob("operation.json"))


@pytest.mark.parametrize("changed_input", ["qfq", "previous_state"])
def test_daily_source_change_while_building_candidates_stops_before_promotion(
    tmp_path, changed_input,
):
    root, prior = _daily_inputs(tmp_path)
    targets = _daily_targets(root)
    before = {path: _physical(path) for path in targets[:-1]}
    source = (
        gold_stk_mins_qfq_path(root, 5, CODES[0], 2026)
        if changed_input == "qfq" else prior
    )
    write_indicator = stk_mins_qfq_macd_kdj._write_indicator_group_to_year_file
    changed = False

    def change_after_candidate(*args, **kwargs):
        nonlocal changed
        result = write_indicator(*args, **kwargs)
        if not changed:
            _replace_same_bytes(source)
            changed = True
        return result

    with (
        patch.object(
            stk_mins_qfq_macd_kdj, "_write_indicator_group_to_year_file",
            side_effect=change_after_candidate,
        ),
        patch.object(StkMinsQfqPublication, "promote") as promote,
        pytest.raises(RuntimeError, match="source file changed"),
    ):
        _daily(root)
    promote.assert_not_called()
    assert {path: _physical(path) for path in before} == before
    assert not targets[-1].exists()
    assert len(list(
        (tmp_path / "daily-lake_staging").rglob("candidates/*/gold/**/*.parquet")
    )) == 3


def test_daily_normal_reads_and_unread_year_change_do_not_false_block(tmp_path):
    root, prior = _daily_inputs(tmp_path)
    source = gold_stk_mins_qfq_path(root, 5, CODES[0], 2026)
    unused = gold_stk_mins_qfq_path(root, 5, CODES[0], 2024)
    unused.parent.mkdir(parents=True)
    unused.write_bytes(b"not a selected source year")
    calculate = stk_mins_qfq_macd_kdj._populate_macd_kdj_indicator_work_rows

    def ordinary_reads(*args, **kwargs):
        result = calculate(*args, **kwargs)
        source.read_bytes()  # A normal read may update atime, not input identity.
        prior.read_bytes()
        _replace_same_bytes(unused)
        return result

    with patch.object(
        stk_mins_qfq_macd_kdj, "_populate_macd_kdj_indicator_work_rows",
        side_effect=ordinary_reads,
    ):
        result = _daily(root)
    assert result.indicator_row_count == 2
    assert result.state_row_count == 2
