"""Exact comparison results and normal-query work, using independent doc328 fields."""

from unittest.mock import Mock

import pytest

from orchestrator.defs.checks.stk_factor_pro import compare_factor_relations
from tests.stk_factor_pro_test_support import NAMES, connection, row

A, B = "000001.SZ", "600000.SH"


def relations(conn, *, layer="raw"):
    # doc328 declares two strings and 259 floats; the verified Raw producer
    # stores them as VARCHAR/DOUBLE. Silver changes only trade_date to DATE.
    columns = ",".join(
        f'"{name}" {"VARCHAR" if index < 2 else "DOUBLE"}'
        for index, name in enumerate(NAMES)
    )
    conn.execute(f"CREATE TEMP TABLE expected ({columns})")
    placeholders = "(" + ",".join("?" for _ in NAMES) + ")"
    conn.execute(
        f"INSERT INTO expected VALUES {placeholders},{placeholders}",
        [*row(A), *row(B)],
    )
    if layer == "silver":
        conn.execute(
            "ALTER TABLE expected ALTER trade_date TYPE DATE "
            "USING CAST(strptime(trade_date,'%Y%m%d') AS DATE)"
        )
    conn.execute(
        "CREATE TEMP TABLE actual AS SELECT * FROM expected ORDER BY ts_code DESC"
    )


def assert_result(result, counts, changed_fields):
    # Counts are literal case expectations; never computed by the comparator.
    assert (
        result.expected_rows,
        result.actual_rows,
        result.missing_key_count,
        result.unexpected_key_count,
        result.changed_row_count,
    ) == counts
    assert result.changed_field_counts == tuple(
        (name, changed_fields.get(name, 0)) for name in NAMES[2:]
    )


@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_equal_full_rows_use_one_five_column_query(tmp_path, layer):
    with connection(tmp_path) as conn:
        relations(conn, layer=layer)
        observed = Mock(wraps=conn)
        result = compare_factor_relations(
            observed, expected="expected", actual="actual"
        )
        assert_result(result, (2, 2, 0, 0, 0), {})
        assert observed.execute.call_count == 1
        assert len(conn.description) == 5


@pytest.mark.parametrize("field", NAMES[2:])
def test_each_numeric_field_is_compared_and_diagnosed(tmp_path, field):
    with connection(tmp_path) as conn:
        relations(conn)
        conn.execute(f'UPDATE actual SET "{field}"=2.5 WHERE ts_code=?', [A])
        observed = Mock(wraps=conn)
        result = compare_factor_relations(
            observed, expected="expected", actual="actual"
        )
        assert_result(result, (2, 2, 0, 0, 1), {field: 1})
        assert observed.execute.call_count == 2
        assert len(conn.description) == 259
        assert all(
            "read_parquet" not in call.args[0].lower()
            for call in observed.execute.call_args_list
        )


@pytest.mark.parametrize(
    "mutation,counts",
    [
        (
            "UPDATE actual SET ts_code='000002.SZ' WHERE ts_code='000001.SZ'",
            (2, 2, 1, 1, 0),
        ),
        (
            "UPDATE actual SET trade_date='20261015' WHERE ts_code='000001.SZ'",
            (2, 2, 1, 1, 0),
        ),
        ("DELETE FROM actual WHERE ts_code='000001.SZ'", (2, 1, 1, 0, 0)),
        ("DELETE FROM expected", (0, 2, 0, 2, 0)),
        ("DELETE FROM actual", (2, 0, 2, 0, 0)),
        ("DELETE FROM expected; DELETE FROM actual", (0, 0, 0, 0, 0)),
    ],
)
def test_missing_extra_dates_and_empty_inputs_need_no_field_diagnostics(
    tmp_path, mutation, counts
):
    with connection(tmp_path) as conn:
        relations(conn)
        conn.execute(mutation)
        observed = Mock(wraps=conn)
        result = compare_factor_relations(
            observed, expected="expected", actual="actual"
        )
        assert_result(result, counts, {})
        assert observed.execute.call_count == 1
        assert len(conn.description) == 5


@pytest.mark.parametrize("replace_key", [False, True])
def test_multiple_changes_count_only_matching_rows(tmp_path, replace_key):
    with connection(tmp_path) as conn:
        relations(conn)
        conn.execute("UPDATE actual SET close=11,open=2.25,pe=0 WHERE ts_code=?", [A])
        conn.execute("UPDATE actual SET close=12 WHERE ts_code=?", [B])
        if replace_key:
            conn.execute("UPDATE actual SET ts_code='000002.SZ' WHERE ts_code=?", [B])
        observed = Mock(wraps=conn)
        result = compare_factor_relations(
            observed, expected="expected", actual="actual"
        )
        assert_result(
            result,
            (2, 2, 1, 1, 1) if replace_key else (2, 2, 0, 0, 2),
            {"close": 1 if replace_key else 2, "open": 1, "pe": 1},
        )
        assert observed.execute.call_count == 2


@pytest.mark.parametrize(
    "field,value,changed",
    [("pe", None, 0), ("pe", 0, 1), ("open", None, 1), ("vol", -0.0, 0)],
)
def test_null_zero_and_signed_zero_keep_exact_semantics(
    tmp_path, field, value, changed
):
    with connection(tmp_path) as conn:
        relations(conn, layer="silver")
        conn.execute(f'UPDATE actual SET "{field}"=? WHERE ts_code=?', [value, A])
        observed = Mock(wraps=conn)
        result = compare_factor_relations(
            observed, expected="expected", actual="actual"
        )
        assert_result(result, (2, 2, 0, 0, changed), {field: changed})
        assert observed.execute.call_count == 1 + changed


def test_sql_error_propagates_without_retry():
    # Only the injected SQL failure is substituted; no successful SDK boundary
    # or content-comparison claim relies on this mock.
    conn = Mock()
    conn.execute.side_effect = RuntimeError("isolated SQL failure")
    with pytest.raises(RuntimeError, match="isolated SQL failure"):
        compare_factor_relations(conn, expected="expected", actual="actual")
    assert conn.execute.call_count == 1
