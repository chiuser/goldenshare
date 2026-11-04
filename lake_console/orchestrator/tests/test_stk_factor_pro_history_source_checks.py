"""Complete Raw history source checks, using doc328's independent 261 columns.

Fixtures deliberately bypass conversion to exercise invalid actual relations.
No network, Dagster instance or formal Lake paths are accessed.
"""

from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from orchestrator.defs.checks import stk_factor_pro as checks
from orchestrator.defs.io import stk_factor_pro_download as downloads
from orchestrator.defs.io import stk_factor_pro_history as history
from tests.stk_factor_pro_history_test_support import NAMES, connection

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


def test_each_unit_is_audited_once_and_source_assembly_reads_no_unit_again(
    tmp_path, monkeypatch
):
    from tests.test_stk_factor_pro_history_download import (
        prepare,
        run_download,
        sample_downloader,
    )

    records, calls, phase = {}, Counter(), {"assembly": False}
    first_audit = checks.require_factor_history_relation
    first_sha = checks.factor_file_sha
    assemble = history.verify_stk_factor_pro_current_source

    def audit_once(connection, relation, **kwargs):
        calls[kwargs["object_code"]] += 1
        return first_audit(connection, relation, **kwargs)

    def sha_once(path):
        if "source/history/units/" in Path(path).as_posix():
            assert not phase["assembly"], "source assembly must use the first file SHA"
            calls["unit_sha"] += 1
        return first_sha(path)

    def assemble_once(*args, **kwargs):
        calls["assembly"] += 1
        phase["assembly"] = True
        try:
            return assemble(*args, **kwargs)
        finally:
            phase["assembly"] = False

    for module in (checks, downloads, history):
        if hasattr(module, "require_factor_history_relation"):
            monkeypatch.setattr(module, "require_factor_history_relation", audit_once)
        if hasattr(module, "factor_file_sha"):
            monkeypatch.setattr(module, "factor_file_sha", sha_once)
        if hasattr(module, "verify_stk_factor_pro_current_source"):
            monkeypatch.setattr(
                module, "verify_stk_factor_pro_current_source", assemble_once
            )

    with connection(tmp_path) as conn:

        class UnitReads:
            def __getattr__(self, name):
                return getattr(conn, name)

            def execute(self, query, parameters=None):
                if "read_parquet" in str(
                    query
                ).lower() and "source/history/units/" in str(query) + repr(parameters):
                    assert not phase["assembly"], (
                        "source assembly must retain the original SQL rows"
                    )
                    calls["unit_read"] += 1
                return (
                    conn.execute(query)
                    if parameters is None
                    else conn.execute(query, parameters)
                )

        observed = UnitReads()
        _, args = prepare(observed, tmp_path, known_records=records)
        source = run_download(
            observed, args, sample_downloader(), known_records=records
        )
        assert calls == {
            "000001.SZ": 1,
            "600000.SH": 1,
            "unit_sha": 2,
            "unit_read": 2,
            "assembly": 1,
        }
        assert source.source_relation == "stk_factor_pro_history_source"
        assert len(source.files) == len(source.file_identities) == 2
        assert conn.execute(
            f"SELECT ts_code,trade_date FROM {source.source_relation} ORDER BY trade_date"
        ).fetchall() == [
            ("000001.SZ", "20261015"),
            ("000001.SZ", "20261016"),
        ]
        downloads.release_stk_factor_pro_history_source(conn)


@pytest.mark.parametrize(
    "fault", ["missing-file-fact", "missing-file-identity", "wrong-run"]
)
def test_source_assembly_rejects_mismatched_first_facts_without_file_rescan(
    tmp_path, fault
):
    from tests.test_stk_factor_pro_history_download import (
        prepare,
        run_download,
        sample_downloader,
    )

    records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=records)
        source = run_download(conn, args, sample_downloader(), known_records=records)
        values = {
            "connection": conn,
            "current_run_id": source.identity.creator_run_id,
            "expected_units": source.source_complete.expected_units,
            "source_relation": source.source_relation,
            "source_complete_ref": source.source_complete_ref,
            "known_records": records,
            "verified_files": source.files,
            "file_identities": source.file_identities,
        }
        if fault == "missing-file-fact":
            values["verified_files"] = source.files[:-1]
        elif fault == "missing-file-identity":
            values["file_identities"] = source.file_identities[:-1]
        else:
            values["current_run_id"] = "another-run"
        with pytest.raises(ValueError):
            history.verify_stk_factor_pro_current_source(
                root, source.source_complete, **values
            )
        downloads.release_stk_factor_pro_history_source(conn)
