"""Small synthetic fixtures only; never depend on the historical CSV or Lake."""

from stock_suspend_confirmed_test_support import (
    FACTS_SQL,
    GOLDEN_BYTES,
    GOLDEN_HASH,
    require_isolated_context,
)

ALLOWED = require_isolated_context()

from dataclasses import replace
from hashlib import sha256
from unittest.mock import Mock

import duckdb
import pytest

from orchestrator.defs import stock_suspend_confirmed_contract as contract
from orchestrator.defs.paths import (
    silver_stock_suspend_confirmed_path,
    silver_stock_suspend_daily_staging_path,
    stock_suspend_confirmed_staging_dir,
)


def test_literal_encoding_and_real_approval_rejection(connection):
    connection.execute(f"CREATE TEMP TABLE sample AS {FACTS_SQL}")
    assert sha256(GOLDEN_BYTES).hexdigest() == GOLDEN_HASH
    assert contract.confirmed_logical_sha256(connection, "sample") == GOLDEN_HASH
    assert not contract.validate_confirmed_content(connection, "sample").passed
    assert contract.STOCK_SUSPEND_CONFIRMED_COUNTS == (4022, 4022, 29, 1857, 4020, 2)
    assert contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256 == "c88a7406ecda31c7dfe92b20b1d9cc719ffd2d049ece93113676ef4e60db4307"


def test_sample_approval_and_same_count_changed_key(connection, fixed_lake):
    inspection = contract.inspect_confirmed_file(connection, silver_stock_suspend_confirmed_path(fixed_lake))
    contract.load_confirmed_relation(connection, inspection, relation_name="facts")
    assert contract.validate_confirmed_schema(connection, "facts").passed
    assert contract.validate_confirmed_content(connection, "facts").passed
    connection.execute("UPDATE facts SET ts_code='000002.SZ' WHERE ts_code='000001.SZ'")
    assert not contract.validate_confirmed_content(connection, "facts").passed


@pytest.mark.parametrize("mutation", [
    "UPDATE facts SET suspend_timing=''", "UPDATE facts SET suspend_type='R'",
    "UPDATE facts SET merge_mode='unknown'", "UPDATE facts SET ts_code=NULL",
    "UPDATE facts SET trade_date=NULL", "UPDATE facts SET trade_date='infinity'::DATE",
    "UPDATE facts SET ts_code='000001.SZ', trade_date='2020-01-02'::DATE",
    "DELETE FROM facts", "UPDATE facts SET merge_mode='replace_confirmed'",
])
def test_content_negative_cases(connection, fixed_lake, mutation):
    inspection = contract.inspect_confirmed_file(connection, silver_stock_suspend_confirmed_path(fixed_lake))
    contract.load_confirmed_relation(connection, inspection, relation_name="facts")
    connection.execute(mutation)
    assert not contract.validate_confirmed_content(connection, "facts").passed


@pytest.mark.parametrize("select_sql", [
    "SELECT ts_code,trade_date,suspend_timing,suspend_type FROM facts",
    "SELECT *,1 AS extra FROM facts",
    "SELECT trade_date,ts_code,suspend_timing,suspend_type,merge_mode FROM facts",
    "SELECT ts_code,trade_date::VARCHAR trade_date,suspend_timing,suspend_type,merge_mode FROM facts",
    "SELECT ts_code,trade_date,NULL::INTEGER suspend_timing,suspend_type,merge_mode FROM facts",
])
def test_physical_schema_rejected_before_cast(connection, fixed_lake, tmp_path, select_sql):
    connection.execute(f"CREATE TEMP TABLE facts AS {FACTS_SQL}")
    path = tmp_path / "bad.parquet"
    connection.execute(f"COPY ({select_sql}) TO ? (FORMAT PARQUET)", [str(path)])
    inspection = contract.inspect_confirmed_file(connection, path)
    assert not inspection.schema_validation.passed
    with pytest.raises(contract.ConfirmedFactsError, match="schema"):
        contract.load_confirmed_relation(connection, inspection, relation_name="bad")


def test_reordered_compressed_file_has_same_logical_identity(connection, fixed_lake, tmp_path):
    path = tmp_path / "reordered.parquet"
    connection.execute(f"COPY ({FACTS_SQL} ORDER BY ts_code DESC) TO ? (FORMAT PARQUET, COMPRESSION GZIP)", [str(path)])
    contract.load_confirmed_relation(connection, contract.inspect_confirmed_file(connection, path), relation_name="reordered")
    assert contract.confirmed_logical_sha256(connection, "reordered") == GOLDEN_HASH
    assert contract.suspend_file_sha256(path) != contract.suspend_file_sha256(silver_stock_suspend_confirmed_path(fixed_lake))


@pytest.mark.parametrize("identifier", ["../escape", "", "a/b", "a.b", "a"*81])
def test_invalid_operation_paths(tmp_path, identifier):
    with pytest.raises(ValueError):
        stock_suspend_confirmed_staging_dir(tmp_path, identifier)


def test_path_rejections(tmp_path):
    with pytest.raises(ValueError):
        silver_stock_suspend_daily_staging_path(tmp_path, "run", "20260116")
    with pytest.raises(contract.ConfirmedFactsError):
        contract.assert_suspend_path(tmp_path / ".." / "escape", root=tmp_path)
    with pytest.raises(contract.ConfirmedFactsError):
        contract.assert_suspend_path(tmp_path / "absent" / "file", root=tmp_path / "absent")
    target = tmp_path / "file"
    target.write_text("unchanged")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(contract.ConfirmedFactsError):
        contract.suspend_file_identity(link)
    with pytest.raises(contract.ConfirmedFactsError):
        contract.suspend_file_identity(tmp_path)
    with pytest.raises(contract.ConfirmedFactsError):
        contract.suspend_relation_identifier("facts; DROP TABLE facts")


@pytest.mark.parametrize("rows", [0, 1, 2, 3])
def test_c08_inspection_separates_schema_and_count(connection, fixed_lake, tmp_path, rows):
    path = tmp_path / "count.parquet"
    sql = f"SELECT * FROM ({FACTS_SQL}) LIMIT {rows}"
    if rows == 3:
        sql = f"{FACTS_SQL} UNION ALL SELECT '000003.SZ', DATE '2020-01-03', NULL::VARCHAR, 'S', 'add_missing'"
    connection.execute(f"COPY ({sql}) TO ? (FORMAT PARQUET)", [str(path)])
    observed = Mock(wraps=connection)
    inspection = contract.inspect_confirmed_file(observed, path)
    assert inspection.row_count == rows and inspection.schema_validation.passed
    assert observed.execute.call_count == 2  # DESCRIBE and count, no row decode.
    observed.reset_mock()
    if rows > 2:
        with pytest.raises(contract.ConfirmedFactsError) as rejected:
            contract.load_confirmed_relation(observed, inspection, relation_name="counts")
        assert rejected.value.reason_code == "row_count_mismatch"
        assert observed.execute.call_count == 0
    else:
        contract.load_confirmed_relation(observed, inspection, relation_name="counts")
        assert observed.execute.call_count == 1
        assert contract.validate_confirmed_schema(connection, "counts").passed
        result = contract.validate_confirmed_content(connection, "counts")
        assert result.passed == (rows == 2)
        assert result.reason_code == ("ok" if rows == 2 else "row_count_mismatch")


@pytest.mark.parametrize("problem", [
    "missing", "corrupt", "oversize", "inspection_drift", "load_drift", "load_missing", "decode_error",
])
def test_c09_inspection_io_and_identity(connection, fixed_lake, tmp_path, monkeypatch, problem):
    path = silver_stock_suspend_confirmed_path(fixed_lake)
    inspection = contract.inspect_confirmed_file(connection, path)
    identity = contract.suspend_file_identity
    observed = Mock(wraps=connection)
    expected_type, expected_reason = contract.ConfirmedFactsError, None
    if problem in ("missing", "load_missing"):
        path.rename(path.with_suffix(".absent"))
        expected_type = FileNotFoundError
    elif problem == "corrupt":
        path.write_bytes(b"synthetic corrupt parquet")
        expected_type = (duckdb.InvalidInputException, duckdb.IOException)
    elif problem == "oversize":
        monkeypatch.setattr(contract, "suspend_file_identity", lambda p: replace(identity(p), size=100 * 1024**2 + 1))
        expected_reason = "size_exceeded"
    elif problem in ("load_drift", "inspection_drift"):
        if problem == "load_drift":
            replacement = tmp_path / "replacement.parquet"
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
        else:
            calls = []

            def changed_identity(p):
                calls.append(p)
                return replace(identity(p), mtime_ns=inspection.file_identity.mtime_ns + (len(calls) > 1))

            monkeypatch.setattr(contract, "suspend_file_identity", changed_identity)
        expected_reason = "input_drift"
    elif problem == "decode_error":
        observed.execute.side_effect = duckdb.IOException("synthetic decode failure")
        expected_type = duckdb.IOException
    with pytest.raises(expected_type) as rejected:
        if problem.startswith("load_") or problem == "decode_error":
            contract.load_confirmed_relation(observed, inspection, relation_name="bad")
        else:
            contract.inspect_confirmed_file(observed, path)
    if expected_reason:
        assert rejected.value.reason_code == expected_reason
    sql_calls = [call.args[0] for call in observed.execute.call_args_list]
    assert not any("COPY" in sql.upper() for sql in sql_calls)
    if problem in ("oversize", "load_drift", "load_missing", "missing"):
        assert not sql_calls
    if problem == "decode_error":
        assert len(sql_calls) == 1 and sql_calls[0].startswith("CREATE OR REPLACE TEMP TABLE")
        assert connection.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name='bad'").fetchone()[0] == 0
