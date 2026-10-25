"""Real isolated factor repair: physical source reuse, formulas and publication.

Inputs follow SILVER_STK_MINS_SCHEMA/SILVER_ADJ_FACTOR_SCHEMA and the real M9C
producer fixtures. Session times below independently reproduce the documented
1/5/30/60 minute producer grid. Literal output expectations do not call any
canonical window, price, diagnostic or repair helper. Only the connection's
temporary directory and an explicitly injected os.replace failure are replaced;
DuckDB, formula SQL, candidate validation and publication execute for real.
"""

import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs import duckdb_connection, resources, stk_mins_qfq
from orchestrator.defs import stk_mins_qfq_factor_repair as repair
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.io import stk_mins_qfq_publication as publication
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
    silver_stock_basic_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STOCK_BASIC_SCHEMA,
)

OLDER = "2025-12-30"
PREVIOUS = "2026-10-21"
TARGET = "2026-10-22"
FUTURE = "2026-10-23"
CODE = "600000.SH"
KEEP = "000001.SZ"
NEW = "688999.SH"
FREQUENCIES = (1, 5, 15, 30, 60, 90, 120)
# count, first time, first volume, last volume, for one literal source stock/day.
GOLDEN_WINDOWS = {
    1: (241, "09:30:00", 100.0, 100.0),
    5: (48, "09:35:00", 600.0, 500.0),
    15: (16, "09:45:00", 400.0, 300.0),
    30: (8, "10:00:00", 700.0, 600.0),
    60: (4, "10:30:00", 300.0, 200.0),
    90: (3, "11:00:00", 400.0, 200.0),
    120: (2, "11:30:00", 300.0, 200.0),
}


def _clock(start, end, step):
    current = datetime.fromisoformat(f"2000-01-01 {start}")
    stop = datetime.fromisoformat(f"2000-01-01 {end}")
    result = []
    while current <= stop:
        result.append(current.strftime("%H:%M:%S"))
        current += timedelta(minutes=step)
    return tuple(result)


SOURCE_TIMES = {
    1: (*_clock("09:30", "11:30", 1), *_clock("13:01", "15:00", 1)),
    5: ("09:30:00", *_clock("09:35", "11:30", 5), *_clock("13:05", "15:00", 5)),
    30: ("09:30:00", "10:00:00", "10:30:00", "11:00:00", "11:30:00", "13:30:00", "14:00:00", "14:30:00", "15:00:00"),
    60: ("09:30:00", "10:30:00", "11:30:00", "14:00:00", "15:00:00"),
}


def _write_rows(path, schema, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    names = tuple(column.name for column in schema)
    definitions = ", ".join(f'"{column.name}" {column.type}' for column in schema)
    with duckdb.connect() as connection:
        connection.execute(f"CREATE TEMP TABLE input_rows ({definitions})")
        if rows:
            connection.executemany(
                f"INSERT INTO input_rows VALUES ({', '.join('?' for _ in names)})",
                [[row.get(name) for name in names] for row in rows],
            )
        connection.execute(copy_query_to_parquet("SELECT * FROM input_rows", path))


def _silver(path, *, source, day, codes, bad=None, open_value=10.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    code_values = ", ".join(f"({duckdb_string(code)})" for code in codes)
    times = ", ".join(f"({duckdb_string(time)})" for time in SOURCE_TIMES[source])
    frequency = (
        f"CASE WHEN ts_code='{CODE}' AND clock='09:30:00' THEN 999 ELSE {source} END"
        if bad == "frequency" else str(source)
    )
    open_sql = (
        f"CASE WHEN ts_code='{CODE}' AND clock='09:30:00' THEN NULL ELSE {open_value} END"
        if bad == "null_price" else str(open_value)
    )
    sql = f"""
    SELECT CAST(ts_code AS VARCHAR) AS ts_code, CAST({frequency} AS INTEGER) AS freq,
      DATE '{day}' AS trade_date, CAST('{day} ' || clock AS TIMESTAMP) AS trade_time,
      CAST({open_sql} AS DOUBLE) AS open, 12::DOUBLE AS high, 8::DOUBLE AS low,
      11::DOUBLE AS close, 100::DOUBLE AS vol, 1000::DOUBLE AS amount,
      CASE WHEN ts_code LIKE '%.SH' THEN 'SSE' ELSE 'SZSE' END::VARCHAR AS exchange
    FROM (VALUES {code_values}) AS codes(ts_code)
    CROSS JOIN (VALUES {times}) AS times(clock)
    """ if codes else """
    SELECT NULL::VARCHAR AS ts_code, NULL::INTEGER AS freq, NULL::DATE AS trade_date,
      NULL::TIMESTAMP AS trade_time, NULL::DOUBLE AS open, NULL::DOUBLE AS high,
      NULL::DOUBLE AS low, NULL::DOUBLE AS close, NULL::DOUBLE AS vol, NULL::DOUBLE AS amount,
      NULL::VARCHAR AS exchange WHERE false
    """
    if bad == "duplicate":
        sql = f"SELECT * FROM ({sql}) UNION ALL SELECT * FROM ({sql}) WHERE ts_code='{CODE}' AND strftime(trade_time, '%H:%M:%S')='09:30:00'"
    with duckdb.connect() as connection:
        connection.execute(copy_query_to_parquet(sql, path))


def _gold_row(code, day, freq, price):
    return {
        "ts_code": code, "freq": freq, "trade_date": day,
        "trade_time": f"{day} {GOLDEN_WINDOWS[freq][1]}", "open": price, "high": price,
        "low": price, "close": price, "vol": 1.0, "amount": 2.0,
        "exchange": "SSE" if code.endswith(".SH") else "SZSE",
    }


def _inputs(root, *, days=(PREVIOUS, TARGET), codes=(CODE,), empty_year=False):
    _write_rows(
        silver_stock_basic_path(root), SILVER_STOCK_BASIC_SCHEMA,
        [{"ts_code": code, "list_date": TARGET if code == NEW else "2000-01-01"}
         for code in (*codes, KEEP, NEW)],
    )
    for day in days:
        factor_codes = (*codes, KEEP, NEW) if day == TARGET else (*codes, KEEP)
        _write_rows(
            silver_adj_factor_path(root, day), SILVER_ADJ_FACTOR_SCHEMA,
            [{"ts_code": code, "trade_date": day,
              "adj_factor": 4.0 if day == TARGET and code in (*codes, NEW) else 2.0}
             for code in factor_codes],
        )
        source_codes = (KEEP,) if empty_year and day == OLDER else (
            (*codes, KEEP, NEW) if day == TARGET else (*codes, KEEP)
        )
        for source in SOURCE_TIMES:
            _silver(silver_stk_mins_path(root, source, day), source=source, day=day, codes=source_codes)
    for frequency in FREQUENCIES:
        _write_rows(gold_stk_mins_qfq_path(root, frequency, KEEP, 2026), GOLD_STK_MINS_QFQ_SCHEMA,
                    [_gold_row(KEEP, TARGET, frequency, 777.0)])


def _rows(path):
    with duckdb.connect() as connection:
        return connection.execute(
            f"SELECT trade_date, strftime(trade_time,'%H:%M:%S'), open, high, low, close, vol, amount "
            f"FROM {read_parquet(path, hive_partitioning=False)} ORDER BY trade_time"
        ).fetchall()


def _identity(path):
    stat = path.stat()
    return stat.st_ino, stat.st_mtime_ns, path.read_bytes()


@pytest.fixture
def isolated_engine(tmp_path, monkeypatch):
    """Keep every real factory in tmp; preserve each caller's temp_policy."""
    spill = tmp_path / "duckdb-temp"
    spill.mkdir()
    queries = []
    policies = []
    actual = duckdb_connection.connect_configured_duckdb

    class Connection:
        def __init__(self, connection, policy):
            self.connection = connection
            self.policy = policy

        def execute(self, sql, *args, **kwargs):
            queries.append((str(sql), self.policy))
            return self.connection.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    @contextmanager
    def connect(settings=duckdb_connection.DEFAULT_DUCKDB_CONNECTION_SETTINGS, *, temp_policy="managed"):
        with actual(replace(settings, temp_directory=spill), temp_policy=temp_policy) as connection:
            policies.append((temp_policy, connection.execute("SELECT current_setting('max_temp_directory_size')").fetchone()[0]))
            yield Connection(connection, temp_policy)

    for target in (repair, stk_mins_qfq, resources):
        monkeypatch.setattr(target, "connect_configured_duckdb", connect, raising=False)
    return queries, policies


def _execute(root, *, days=(PREVIOUS, TARGET), frequencies=(1, 5, 15, 30, 60), identity=None):
    return repair.execute_gold_stk_mins_qfq_factor_repair(
        lake_root=root, duckdb_resource=resources.DuckDBResource(), trade_date=TARGET,
        expected_trade_dates=days, registered_partition_keys=days,
        freqs=frequencies, publication_id=identity,
    )


def _physical_references(queries, path):
    literal = duckdb_string(path)
    return [(sql, policy) for sql, policy in queries
            if "read_parquet" in sql.lower() and literal in sql
            and not sql.lstrip().upper().startswith("DESCRIBE")]


def test_four_source_relations_and_annual_factors_are_shared(tmp_path, isolated_engine):
    root = tmp_path / "lake"
    days = (OLDER, PREVIOUS, TARGET)
    _inputs(root, days=days)
    report = _execute(root, days=days, identity="shared-sources")
    queries, policies = isolated_engine
    for day in days:
        for source in SOURCE_TIMES:
            references = _physical_references(queries, silver_stk_mins_path(root, source, day))
            assert len(references) == 1, (source, day, references)
            assert references[0][1] == "existing_no_spill"
    assert len(_physical_references(queries, silver_adj_factor_path(root, OLDER))) == 1
    assert len(_physical_references(queries, silver_adj_factor_path(root, PREVIOUS))) <= 2
    assert len(_physical_references(queries, silver_adj_factor_path(root, TARGET))) <= 3
    assert any(policy == "existing_no_spill" and size == "0 bytes" for policy, size in policies)
    assert report.planned_batch_count == 10
    assert report.derived_planned_batch_count == 4
    assert report.repaired_code_count == 1


def test_seven_frequency_prices_windows_quantities_and_outside_dates_use_literal_goldens(
    tmp_path, isolated_engine,
):
    root = tmp_path / "lake"
    _inputs(root)
    preserved = {
        gold_stk_mins_qfq_path(root, frequency, KEEP, 2026):
        _identity(gold_stk_mins_qfq_path(root, frequency, KEEP, 2026))
        for frequency in FREQUENCIES
    }
    for frequency in FREQUENCIES:
        _write_rows(gold_stk_mins_qfq_path(root, frequency, CODE, 2026), GOLD_STK_MINS_QFQ_SCHEMA,
                    [_gold_row(CODE, FUTURE, frequency, 999.0)])
    report = _execute(root, identity="seven-goldens")
    assert report.plan.factor_changed_code_count == 1
    assert report.plan.new_current_code_count == 1
    assert {path: _identity(path) for path in preserved} == preserved
    for frequency, (count, first_time, first_volume, last_volume) in GOLDEN_WINDOWS.items():
        rows = _rows(gold_stk_mins_qfq_path(root, frequency, CODE, 2026))
        previous = [row for row in rows if str(row[0]) == PREVIOUS]
        target = [row for row in rows if str(row[0]) == TARGET]
        future = [row for row in rows if str(row[0]) == FUTURE]
        assert len(previous) == count and len(target) == count
        # The first aggregated window opens at the auction CLOSE (11), per the
        # canonical auction contract, not the auction OPEN (10). 1m is unchanged.
        first_open = 10.0 if frequency == 1 else 11.0
        assert previous[0][1:] == (first_time, first_open / 2, 6.0, 4.0, 5.5, first_volume, first_volume * 10)
        assert target[0][1:] == (first_time, first_open, 12.0, 8.0, 11.0, first_volume, first_volume * 10)
        assert previous[-1][1:] == ("15:00:00", 5.0, 6.0, 4.0, 5.5, last_volume, last_volume * 10)
        assert len(future) == 1 and future[0][2:] == (999.0, 999.0, 999.0, 999.0, 1.0, 2.0)


def test_26_changed_codes_do_not_touch_unchanged_or_new_stock(tmp_path, isolated_engine):
    root = tmp_path / "lake"
    codes = tuple(f"{600000 + index:06d}.SH" for index in range(26))
    _inputs(root, codes=codes)
    new_path = gold_stk_mins_qfq_path(root, 1, NEW, 2026)
    _write_rows(new_path, GOLD_STK_MINS_QFQ_SCHEMA, [_gold_row(NEW, TARGET, 1, 888.0)])
    preserved = {path: _identity(path) for path in (gold_stk_mins_qfq_path(root, 1, KEEP, 2026), new_path)}
    report = _execute(root, frequencies=(1,), identity="26-code-scope")
    assert report.plan.repair_required_code_count == report.repaired_code_count == 26
    assert report.plan.new_current_code_count == 1
    assert {entry.ts_code for entry in report.code_results} == set(codes)
    assert {path: _identity(path) for path in preserved} == preserved


@pytest.mark.parametrize("bad", ["frequency", "null_price", "duplicate"])
def test_bad_raw_source_cannot_be_filtered_before_real_diagnostics(tmp_path, isolated_engine, bad):
    root = tmp_path / "lake"
    _inputs(root)
    _silver(silver_stk_mins_path(root, 1, PREVIOUS), source=1, day=PREVIOUS, codes=(CODE,), bad=bad)
    with pytest.raises(RuntimeError, match="incomplete|invalid|Canonical|canonical"):
        _execute(root, frequencies=(1, 5), identity=f"bad-{bad}")
    assert not gold_stk_mins_qfq_path(root, 1, CODE, 2026).exists()


def test_empty_prior_year_does_not_create_planned_but_empty_targets(tmp_path, isolated_engine):
    root = tmp_path / "lake"
    days = (OLDER, PREVIOUS, TARGET)
    _inputs(root, days=days, empty_year=True)
    report = _execute(root, days=days, frequencies=(1, 5), identity="empty-year")
    assert report.planned_batch_count == 4 and report.non_empty_batch_count == 2
    assert report.repaired_code_count == 1 and report.rewritten_file_count == 2
    assert not any(gold_stk_mins_qfq_path(root, frequency, CODE, 2025).exists() for frequency in (1, 5))


def test_cross_year_results_preserve_original_year_and_date_contract(tmp_path, isolated_engine):
    root = tmp_path / "lake"
    days = (OLDER, PREVIOUS, TARGET)
    _inputs(root, days=days)
    report = _execute(root, days=days, frequencies=(1, 5), identity="cross-year")
    assert report.rewritten_file_count == 4
    for frequency, count in ((1, 241), (5, 48)):
        rows = _rows(gold_stk_mins_qfq_path(root, frequency, CODE, 2025))
        assert len(rows) == count
        assert {str(row[0]) for row in rows} == {OLDER}
        assert rows[0][2:6] == (5.0 if frequency == 1 else 5.5, 6.0, 4.0, 5.5)


@pytest.mark.parametrize("change_input", [False, True])
def test_same_publication_resumes_actual_replace_without_recopy_or_rejects_changed_input(
    tmp_path, isolated_engine, monkeypatch, change_input,
):
    root = tmp_path / "lake"
    _inputs(root)
    first = gold_stk_mins_qfq_path(root, 1, CODE, 2026)
    actual = os.replace
    interrupted = False

    def stop_after_replace(source, destination):
        nonlocal interrupted
        actual(source, destination)
        if Path(destination) == first and not interrupted:
            interrupted = True
            raise RuntimeError("injected after formal replace")

    with monkeypatch.context() as fault:
        fault.setattr(publication.os, "replace", stop_after_replace)
        with pytest.raises(RuntimeError, match="injected after formal replace"):
            _execute(root, frequencies=(1, 5), identity="resumable-root")
    assert interrupted
    before = _identity(first)
    queries, _ = isolated_engine
    queries.clear()
    if change_input:
        _silver(silver_stk_mins_path(root, 1, PREVIOUS), source=1, day=PREVIOUS, codes=(CODE,), open_value=11.0)
        with pytest.raises(ValueError, match="inputs or targets changed"):
            _execute(root, frequencies=(1, 5), identity="resumable-root")
    else:
        report = _execute(root, frequencies=(1, 5), identity="resumable-root")
        assert report.repaired_code_count == 1
    assert _identity(first) == before
    assert not any(sql.lstrip().upper().startswith("COPY") and "/candidates/" in sql
                   and "/freq=1/" in sql and "/year=2026/" in sql for sql, _ in queries)


def test_source_changed_after_real_diagnostics_is_rejected_before_publication(
    tmp_path, isolated_engine, monkeypatch,
):
    root = tmp_path / "lake"
    _inputs(root)
    actual = repair._assert_repair_source_ready

    def change_source_after_diagnostics(*args, **kwargs):
        actual(*args, **kwargs)
        _silver(
            silver_stk_mins_path(root, 1, PREVIOUS), source=1,
            day=PREVIOUS, codes=(CODE,), open_value=11.0,
        )

    monkeypatch.setattr(repair, "_assert_repair_source_ready", change_source_after_diagnostics)
    with pytest.raises(RuntimeError, match="inputs changed"):
        _execute(root, frequencies=(1,), identity="input-mutated-during-run")
    assert not gold_stk_mins_qfq_path(root, 1, CODE, 2026).exists()
