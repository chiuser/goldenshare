"""Pure-relation golden samples; no writer, CSV, real facts or Dagster instance."""

from stock_suspend_confirmed_test_support import require_isolated_context

require_isolated_context()  # Must precede business imports and collection.

from pathlib import Path

import pytest

from orchestrator.defs import duckdb_sql as sql
from orchestrator.defs.stock_suspend_confirmed_contract import ConfirmedFactsError

RELATIONS = {"normalized_relation": "normalized", "confirmed_relation": "confirmed",
             "dates_relation": "selected_dates"}
COUNTS = (
    "selected_fact_keys", "add_missing_inserted_keys", "add_missing_reused_keys",
    "replace_confirmed_keys", "replace_confirmed_matched_raw_keys", "removed_raw_rows",
    "conflict_rows", "output_rows",
)


def _inputs(connection, *, raw=(), facts=(), dates=("2020-01-02",)):
    assert len(raw) <= 32 and len(facts) <= 32 and len(dates) <= 14
    connection.execute("CREATE TEMP TABLE normalized(ts_code VARCHAR, trade_date DATE, "
                       "suspend_timing VARCHAR, suspend_type VARCHAR)")
    connection.execute("CREATE TEMP TABLE confirmed(ts_code VARCHAR, trade_date DATE, "
                       "suspend_timing VARCHAR, suspend_type VARCHAR, merge_mode VARCHAR)")
    connection.execute("CREATE TEMP TABLE selected_dates(trade_date DATE)")
    # Bounded literal test input, not a production row-insertion path.
    for name, rows, width in (("normalized", raw, 4), ("confirmed", facts, 5),
                              ("selected_dates", [(d,) for d in dates], 1)):
        if rows:
            placeholders = "(" + ",".join(["?"] * width) + ")"
            connection.execute(f"INSERT INTO {name} VALUES " + ",".join([placeholders] * len(rows)),
                               [value for row in rows for value in row])


def _merged_select():
    # This is the permanent shared CTE, not a second public merge entrypoint.
    return sql._stock_suspend_confirmed_ctes(**RELATIONS) + "SELECT * FROM suspend_merged"


def _rows(connection):
    query = _merged_select()
    columns = connection.execute(f"DESCRIBE ({query})").fetchall()
    assert [(c[0], c[1]) for c in columns] == [
        ("ts_code", "VARCHAR"), ("trade_date", "DATE"),
        ("suspend_timing", "VARCHAR"), ("suspend_type", "VARCHAR"),
    ]
    return connection.execute(
        f"SELECT ts_code, CAST(trade_date AS VARCHAR), suspend_timing, suspend_type "
        f"FROM ({query}) ORDER BY ts_code, trade_date, suspend_timing, suspend_type"
    ).fetchall()


def _stats(connection, expected):
    result = connection.execute(sql.stock_suspend_confirmed_stats_select(**RELATIONS))
    assert [c[0] for c in result.description] == [*COUNTS, "samples"]
    assert [str(c[1]) for c in result.description[:8]] == ["BIGINT"] * 8
    row = result.fetchone()
    assert row[:8] == expected
    assert result.fetchone() is None
    assert expected[0] == sum(expected[1:4])
    assert len(row[8]) <= 20
    return row[8]


def _conflicts(connection):
    query = sql.stock_suspend_confirmed_conflicts_select(**RELATIONS)
    total = connection.execute(f"SELECT count(*) FROM ({query})").fetchone()[0]
    samples = connection.execute(
        f"SELECT ts_code, CAST(trade_date AS VARCHAR), suspend_type, suspend_timing "
        f"FROM ({query}) ORDER BY ts_code, trade_date, suspend_type, suspend_timing LIMIT 20"
    ).fetchall()
    return total, samples


@pytest.mark.parametrize("present", [False, True])
def test_add_missing(connection, present):
    row = ("000001.SZ", "2020-01-02", None, "S")
    _inputs(connection, raw=[row] if present else [], facts=[(*row, "add_missing")])
    assert _rows(connection) == [("000001.SZ", "2020-01-02", None, "S")]
    assert _conflicts(connection) == (0, [])
    samples = _stats(connection, (1, int(not present), int(present), 0, 0, 0, 0, 1))
    assert [(s["category"], s["ts_code"], str(s["trade_date"])) for s in samples] == [
        ("add_missing_reused" if present else "add_missing_inserted", "000001.SZ", "2020-01-02")
    ]


def test_raw_duplicates(connection):
    row = ("000001.SZ", "2020-01-02", None, "S")
    _inputs(connection, raw=[row, row], facts=[(*row, "add_missing")])
    assert _rows(connection) == [("000001.SZ", "2020-01-02", None, "S"),
                                 ("000001.SZ", "2020-01-02", None, "S")]
    assert _conflicts(connection) == (0, [])
    _stats(connection, (1, 0, 1, 0, 0, 0, 0, 2))
    # Same grouping semantics as the current key check; actual check execution is
    # intentionally left to the writer/check integration suite, not claimed here.
    assert connection.execute(
        f"SELECT count(*) FROM ({_merged_select()}) GROUP BY ts_code, trade_date, "
        "suspend_type, COALESCE(suspend_timing, '') HAVING count(*) > 1"
    ).fetchall() == [(2,)]


@pytest.mark.parametrize("raw, expected", [
    ([("000001.SZ", "2020-01-02", None, "R")], [("000001.SZ", "2020-01-02", "R", None)]),
    ([("000001.SZ", "2020-01-02", "09:30-10:00", "S")],
     [("000001.SZ", "2020-01-02", "S", "09:30-10:00")]),
    ([("000001.SZ", "2020-01-02", None, "S"), ("000001.SZ", "2020-01-02", None, "R")],
     [("000001.SZ", "2020-01-02", "R", None)]),
])
def test_conflict(connection, raw, expected):
    _inputs(connection, raw=raw, facts=[("000001.SZ", "2020-01-02", None, "S", "add_missing")])
    assert _conflicts(connection) == (1, expected)
    # Do not execute the merge as if it were accepted after a conflict.


def test_unmatched_raw(connection):
    _inputs(connection, raw=[("000002.SZ", "2020-01-02", "09:30-10:00", "S"),
                             ("000003.SZ", "2020-01-02", None, "R"),
                             ("000004.SZ", "2020-01-02", None, None)])
    assert _rows(connection) == [("000002.SZ", "2020-01-02", "09:30-10:00", "S"),
                                 ("000003.SZ", "2020-01-02", None, "R"),
                                 ("000004.SZ", "2020-01-02", None, None)]
    _stats(connection, (0, 0, 0, 0, 0, 0, 0, 3))


@pytest.mark.parametrize("facts", [[], [("000001.SZ", "2020-01-03", None, "S", "add_missing")]])
def test_empty(connection, facts):
    _inputs(connection, facts=facts)
    assert _rows(connection) == []
    assert _conflicts(connection) == (0, [])
    assert _stats(connection, (0, 0, 0, 0, 0, 0, 0, 0)) == []


@pytest.mark.parametrize("code, day", [("688005.SH", "2026-01-16"), ("688766.SH", "2025-11-26")])
@pytest.mark.parametrize("raw_values", [[], [(None, "S")], [(None, "S"), (None, "R"), ("09:30-10:00", "S")]])
def test_replace_confirmed(connection, code, day, raw_values):
    _inputs(connection, raw=[(code, day, timing, kind) for timing, kind in raw_values]
            + [("000002.SZ", day, None, "R")],
            facts=[(code, day, None, "S", "replace_confirmed")], dates=[day])
    assert _rows(connection) == [("000002.SZ", day, None, "R"), (code, day, None, "S")]
    assert _conflicts(connection) == (0, [])
    _stats(connection, (1, 0, 0, 1, int(bool(raw_values)), len(raw_values), 0, 2))


def test_original_override_rows(connection):
    # Literal values from S0 section 4, not a read of the production files.
    _inputs(connection, raw=[("688005.SH", "2026-01-16", "09:30-09:30", "S"),
                             ("688766.SH", "2025-11-26", None, "R"),
                             ("688766.SH", "2025-11-26", "09:30-09:30", "S")],
            facts=[("688005.SH", "2026-01-16", None, "S", "replace_confirmed"),
                   ("688766.SH", "2025-11-26", None, "S", "replace_confirmed")],
            dates=["2026-01-16", "2025-11-26"])
    assert _rows(connection) == [("688005.SH", "2026-01-16", None, "S"),
                                 ("688766.SH", "2025-11-26", None, "S")]
    _stats(connection, (2, 0, 0, 2, 2, 3, 0, 2))


def test_timing_corrections(connection):
    # Independent literal expected values, never imported from the corrections tuple.
    expected = [
        ("000055.SZ", "2015-07-06", "10:36-15:00", "S"),
        ("000078.SZ", "2015-03-20", "10:29-15:00", "S"),
        ("000159.SZ", "2016-02-22", "10:55-15:00", "S"),
        ("000498.SZ", "2017-08-16", "09:48-15:00", "S"),
        ("000510.SZ", "2016-03-16", "14:43-15:00", "S"),
        ("000533.SZ", "2016-03-25", "13:48-15:00", "S"),
        ("000566.SZ", "2014-01-02", "13:55-15:00", "S"),
        ("000609.SZ", "2015-04-27", "10:16-15:00", "S"),
        ("000655.SZ", "2015-05-21", "11:07-15:00", "S"),
        ("000659.SZ", "2016-08-18", "13:44-15:00", "S"),
        ("000678.SZ", "2014-03-13", "13:02-15:00", "S"),
        ("000711.SZ", "2016-10-19", "13:15-15:00", "S"),
        ("300272.SZ", "2017-08-14", "10:02-15:00", "S"),
        ("300731.SZ", "2017-12-08", "09:30-10:00", "S"),
    ]
    _inputs(connection, raw=[(code, day, "bad-original-timing", kind) for code, day, _, kind in expected],
            dates=[row[1] for row in expected])
    assert _rows(connection) == expected
    _stats(connection, (0, 0, 0, 0, 0, 0, 0, 14))


@pytest.mark.parametrize("timing, conflicts", [(None, 0), ("bad-original-timing", 1)])
def test_timing_overlap(connection, timing, conflicts):
    _inputs(connection, raw=[("000566.SZ", "2014-01-02", timing, "S")],
            facts=[("000566.SZ", "2014-01-02", None, "S", "add_missing")], dates=["2014-01-02"])
    total, samples = _conflicts(connection)
    assert total == conflicts
    if conflicts:
        assert samples == [("000566.SZ", "2014-01-02", "S", "bad-original-timing")]
    else:
        # Match the approved old ordering: conflict before correction, reuse after.
        assert _rows(connection) == [("000566.SZ", "2014-01-02", "13:55-15:00", "S"),
                                     ("000566.SZ", "2014-01-02", None, "S")]
        _stats(connection, (1, 1, 0, 0, 0, 0, 0, 2))


def test_selected_dates(connection):
    _inputs(connection, facts=[("000001.SZ", "2020-01-02", None, "S", "add_missing"),
                              ("000002.SZ", "2020-01-03", None, "S", "add_missing")],
            dates=["2020-01-02", "2020-01-03"])
    assert _rows(connection) == [("000001.SZ", "2020-01-02", None, "S"),
                                 ("000002.SZ", "2020-01-03", None, "S")]
    _stats(connection, (2, 2, 0, 0, 0, 0, 0, 2))
    connection.execute("DELETE FROM selected_dates WHERE trade_date = DATE '2020-01-03'")
    assert _rows(connection) == [("000001.SZ", "2020-01-02", None, "S")]
    _stats(connection, (1, 1, 0, 0, 0, 0, 0, 1))


def test_no_date_filter(connection):
    _inputs(connection, raw=[("000001.SZ", "2020-01-03", None, "R")])
    # The writer must reject a misplaced input row, not silently hide it in SQL.
    assert _rows(connection) == [("000001.SZ", "2020-01-03", None, "R")]


def test_conflict_stats(connection):
    _inputs(connection, raw=[("000001.SZ", "2020-01-02", None, "R")] * 25
            + [("688005.SH", "2026-01-16", None, "R")] * 3,
            facts=[("000001.SZ", "2020-01-02", None, "S", "add_missing"),
                   ("688005.SH", "2026-01-16", None, "S", "replace_confirmed"),
                   ("688766.SH", "2025-11-26", None, "S", "replace_confirmed")],
            dates=["2020-01-02", "2026-01-16", "2025-11-26"])
    assert _conflicts(connection) == (25, [("000001.SZ", "2020-01-02", "R", None)] * 20)
    _stats(connection, (3, 1, 0, 2, 1, 3, 25, 28))


def test_bounded_classification_samples(connection):
    # 25 independent synthetic keys, generated in SQL, not real approved facts.
    _inputs(connection)
    connection.execute("INSERT INTO confirmed SELECT 'TEST' || lpad(CAST(i AS VARCHAR), 2, '0'), "
                       "DATE '2020-01-02', NULL::VARCHAR, 'S', 'add_missing' FROM range(25) t(i)")
    samples = _stats(connection, (25, 25, 0, 0, 0, 0, 0, 25))
    assert len(samples) == 20
    assert [s["ts_code"] for s in samples] == [f"TEST{i:02d}" for i in range(20)]
    assert {s["category"] for s in samples} == {"add_missing_inserted"}


@pytest.mark.parametrize("timing, total", [(None, 0), ("09:30-10:00", 1)])
def test_null_conflict_semantics(connection, timing, total):
    _inputs(connection, raw=[("000001.SZ", "2020-01-02", timing, None)],
            facts=[("000001.SZ", "2020-01-02", None, "S", "add_missing")])
    assert _conflicts(connection)[0] == total  # Preserve the original SQL three-valued logic.


@pytest.mark.parametrize("argument", list(RELATIONS))
@pytest.mark.parametrize("invalid", ["", "a.b", "x; DROP TABLE normalized", "x" * 81])
def test_relation_names(argument, invalid):
    arguments = {**RELATIONS, argument: invalid}
    for helper in (sql._stock_suspend_confirmed_ctes, sql.stock_suspend_confirmed_conflicts_select,
                   sql.stock_suspend_confirmed_stats_select):
        with pytest.raises(ConfirmedFactsError, match="非法停牌关系名") as error:
            helper(**arguments)
        assert error.value.reason_code == "invalid_relation"


def test_pure_builders(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("pure SQL builders must not read files or use the old merge")

    for name in ("open", "stat", "mkdir", "replace"):
        monkeypatch.setattr(Path, name, forbidden)
    for name in ("suspend_full_day_ranges_values_sql", "suspend_full_day_raw_overrides_values_sql",
                 "silver_stock_suspend_daily_select"):
        monkeypatch.setattr(sql, name, forbidden)
    for helper in (sql._stock_suspend_confirmed_ctes, sql.stock_suspend_confirmed_conflicts_select,
                   sql.stock_suspend_confirmed_stats_select):
        query = helper(**RELATIONS)
        assert isinstance(query, str)
        assert "read_parquet" not in query and "COPY" not in query and ".csv" not in query


@pytest.mark.parametrize("arguments, reason", [
    (["--scope", "regression"], "regression requires --suite"),
    (["--scope", "regression", "--suite", "../test_stock_suspend_confirmed_merge.py"], "invalid choice"),
    (["--scope", "adapter", "--suite", "test_stock_suspend_confirmed_merge.py"], "only allowed with regression"),
    (["--scope", "regression", "--suite", "test_stock_suspend_confirmed_merge.py", "-k", "x"], "unrecognized arguments"),
])
def test_runner_selection_rejected(monkeypatch, capsys, arguments, reason):
    import importlib.util
    import sys

    path = Path(__file__).with_name("stock_suspend_confirmed_test_runner.py")
    spec = importlib.util.spec_from_file_location("confirmed_runner_selection_test", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    def forbidden():
        raise AssertionError("invalid suite must fail before creating a test directory")

    monkeypatch.setattr(runner, "create_isolation_root", forbidden)
    monkeypatch.setattr(sys, "argv", [str(path), *arguments])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
    assert reason in capsys.readouterr().err
