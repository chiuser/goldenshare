"""Complete Raw history source checks, using doc328's independent 261 columns.

Fixtures deliberately bypass conversion to exercise invalid actual relations.
No network, Dagster instance or formal Lake paths are accessed.
"""

from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from orchestrator.defs.checks import stk_factor_pro as checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.run_contracts.stk_factor_pro import (
    SourceFileRecord,
    UnitProjection,
    stk_factor_pro_schema_digest,
    stk_factor_pro_unit_key,
)
from tests.stk_factor_pro_history_test_support import NAMES, connection, contract

START, END = date(2026, 10, 15), date(2026, 10, 16)
CODE = "000001.SZ"
RELATION = "history_source_under_check"
SCHEMA = tuple(
    (field, "VARCHAR" if i < 2 else "DOUBLE") for i, field in enumerate(NAMES)
)


def create(conn, values=(), *, schema=SCHEMA):
    fields = ",".join(f'"{field}" {kind}' for field, kind in schema)
    conn.execute(f"CREATE TEMP TABLE {RELATION} ({fields})")
    for value in values:
        conn.execute(
            f"INSERT INTO {RELATION} VALUES ({','.join('?' for _ in schema)})", value
        )


def source_row(*, code=CODE, day="20261015", field=None, value=None):
    result = [code, day] + [1.25] * 259
    result[NAMES.index("macd_bfq")] = -1.25
    result[NAMES.index("pe")] = None
    if field is not None:
        result[NAMES.index(field)] = value
    return tuple(result)


def require(conn, **changes):
    return checks.require_factor_history_relation(
        conn,
        RELATION,
        **{
            "object_code": CODE,
            "start_date": START,
            "end_date": END,
            **changes,
        },
    )


def test_complete_history_allows_closed_boundaries_negative_numbers_and_null(tmp_path):
    with connection(tmp_path) as conn:
        create(conn, (source_row(), source_row(day="20261016")))
        assert require(conn) == (2, SCHEMA)


def test_empty_history_still_requires_and_returns_complete_schema(tmp_path):
    with connection(tmp_path) as conn:
        create(conn)
        assert require(conn) == (0, SCHEMA)


@pytest.mark.parametrize(
    "day",
    [None, "2026-10-15", "2026101", "202610150", "20260230", "20261014", "20261017"],
)
def test_history_rejects_null_malformed_impossible_or_outside_dates(tmp_path, day):
    with connection(tmp_path) as conn:
        create(conn, (source_row(day=day),))
        with pytest.raises(ValueError, match="日期"):
            require(conn)


@pytest.mark.parametrize("code", [None, "600000.SH", "bad-code"])
def test_history_rejects_wrong_or_invalid_stock(tmp_path, code):
    with connection(tmp_path) as conn:
        create(conn, (source_row(code=code),))
        with pytest.raises(ValueError, match="主键"):
            require(conn)


def test_history_rejects_duplicate_two_column_key(tmp_path):
    with connection(tmp_path) as conn:
        create(conn, (source_row(), source_row()))
        with pytest.raises(ValueError, match="重复键"):
            require(conn)


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
def test_history_rejects_nonfinite_values_in_any_business_field(tmp_path, number):
    with connection(tmp_path) as conn:
        create(conn, (source_row(field=NAMES[-1], value=number),))
        with pytest.raises(ValueError, match="非有限"):
            require(conn)


@pytest.mark.parametrize(
    "kind", ["missing", "extra", "order", "date-type", "numeric-type"]
)
def test_history_rejects_schema_difference_even_when_empty(tmp_path, kind):
    schema = list(SCHEMA)
    if kind == "missing":
        schema.pop()
    elif kind == "extra":
        schema.append(("created_at", "TIMESTAMP"))
    elif kind == "order":
        schema[2], schema[3] = schema[3], schema[2]
    elif kind == "date-type":
        schema[1] = ("trade_date", "DATE")
    else:
        schema[-1] = (NAMES[-1], "DECIMAL(18,4)")
    with connection(tmp_path) as conn:
        create(conn, schema=tuple(schema))
        with pytest.raises(ValueError, match="完整合同"):
            require(conn)


@pytest.mark.parametrize(
    "changes",
    [
        {"object_code": "bad-code"},
        {"object_code": None},
        {"start_date": "2026-10-15"},
        {"end_date": datetime(2026, 10, 16, tzinfo=ZoneInfo("Asia/Shanghai"))},
        {"start_date": END, "end_date": START},
    ],
)
def test_history_input_types_and_closed_range_are_explicit(tmp_path, changes):
    with connection(tmp_path) as conn:
        create(conn)
        with pytest.raises(ValueError, match="闭区间"):
            require(conn, **changes)


def test_day_raw_check_still_rejects_another_valid_day(tmp_path):
    with connection(tmp_path) as conn:
        create(conn, (source_row(), source_row(day="20261016")))
        with pytest.raises(ValueError, match="日期"):
            checks.require_factor_relation(
                conn, RELATION, target_trade_date=START, layer="raw"
            )


def test_day_raw_and_silver_still_use_distinct_exact_date_types(tmp_path):
    with connection(tmp_path) as conn:
        create(conn, (source_row(),))
        assert checks.require_factor_relation(
            conn, RELATION, target_trade_date=START, layer="raw"
        ) == (1, SCHEMA)
        with pytest.raises(ValueError, match="完整合同"):
            checks.require_factor_relation(
                conn, RELATION, target_trade_date=START, layer="silver"
            )
        conn.execute(
            f"CREATE TEMP TABLE silver_source_under_check AS SELECT * REPLACE (CAST(strptime(trade_date,'%Y%m%d') AS DATE) AS trade_date) FROM {RELATION}"
        )
        count, schema = checks.require_factor_relation(
            conn, "silver_source_under_check", target_trade_date=START, layer="silver"
        )
        assert count == 1 and schema[1] == ("trade_date", "DATE")
        with pytest.raises(ValueError, match="日期"):
            checks.require_factor_relation(
                conn, "silver_source_under_check", target_trade_date=END, layer="silver"
            )


def file_record(path, *, count=1):
    unit = UnitProjection(5, CODE, None, START, END)
    key = stk_factor_pro_unit_key(unit)
    return SourceFileRecord(
        "history",
        key,
        "native-unit",
        0,
        5,
        CODE,
        None,
        START,
        END,
        count,
        count,
        f"source/history/units/{key}.parquet",
        checks.factor_file_sha(path),
        count,
        stk_factor_pro_schema_digest("raw"),
        contract().contract_content_digest,
        datetime(2026, 10, 16, 19, tzinfo=ZoneInfo("Asia/Shanghai")),
    )


def test_source_file_verifier_uses_common_history_helper(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        create(conn, (source_row(),))
        path = tmp_path / "unit.parquet"
        conn.execute(copy_query_to_parquet(f"SELECT * FROM {RELATION}", path))
        calls = []
        original = checks.require_factor_history_relation

        def tracked(connection, relation, **kwargs):
            calls.append((relation, kwargs))
            return original(connection, relation, **kwargs)

        monkeypatch.setattr(history, "require_factor_history_relation", tracked)
        history._verify_source_unit(conn, path, file_record(path))
        assert calls == [
            (
                "stk_factor_pro_verified_source_unit",
                {"object_code": CODE, "start_date": START, "end_date": END},
            )
        ]
        assert (
            conn.execute(
                "SELECT count(*) FROM duckdb_views() WHERE view_name='stk_factor_pro_verified_source_unit'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("fault", ["count", "sha", "actual-date"])
def test_source_file_verifier_keeps_row_count_sha_and_content_checks(tmp_path, fault):
    with connection(tmp_path) as conn:
        create(
            conn,
            (source_row(day="20261017" if fault == "actual-date" else "20261015"),),
        )
        path = tmp_path / "unit.parquet"
        conn.execute(copy_query_to_parquet(f"SELECT * FROM {RELATION}", path))
        record = file_record(path, count=2 if fault == "count" else 1)
        if fault == "sha":
            record = replace(record, file_sha256="a" * 64)
        with pytest.raises(ValueError):
            history._verify_source_unit(conn, path, record)
        assert (
            conn.execute(
                "SELECT count(*) FROM duckdb_views() WHERE view_name='stk_factor_pro_verified_source_unit'"
            ).fetchone()[0]
            == 0
        )
