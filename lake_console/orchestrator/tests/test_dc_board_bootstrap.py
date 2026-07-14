import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.bootstrap.dc_board_bootstrap import (
    DC_MEMBER_BOOTSTRAP_SELECT_SQL,
    export_dc_member_partition_from_prod_db,
)
from orchestrator.defs.assets.dc_board import DcBoardRawValidationError


class _MemoryDuckDB:
    def connect(self):
        connection = duckdb.connect(":memory:")

        class _Context:
            def __enter__(self):
                return connection

            def __exit__(self, exc_type, exc, tb):
                connection.close()
                return False

        return _Context()


class _FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.fetchmany_calls = []
        self.itersize = None
        self.executed = None
        self.closed = False

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchmany(self, size):
        self.fetchmany_calls.append(size)
        page, self.rows = self.rows[:size], self.rows[size:]
        return page

    def fetchall(self):
        raise AssertionError("Bootstrap must not call fetchall().")

    def close(self):
        self.closed = True


class _FakeConnection:
    def __init__(self, cursor):
        self.cursor_value = cursor

    def cursor(self, name):
        self.cursor_name = name
        return self.cursor_value


class _FakeProdResource:
    def __init__(self, connection):
        self.connection = connection
        self.entered = False
        self.exited = False
        self.rollback_called = False

    def connect_readonly_transaction(self):
        owner = self
        class _Context:
            def __enter__(self):
                owner.entered = True
                return owner.connection

            def __exit__(self, exc_type, exc, tb):
                owner.rollback_called = True
                owner.exited = True
                return False

        return _Context()


class DcBoardBootstrapTests(unittest.TestCase):
    def test_prod_bootstrap_projects_four_fields_and_streams_fetchmany(self):
        cursor = _FakeCursor(
            [
                ("2026-07-14", "BK0001.DC", "000001.SZ", "股票一"),
                ("2026-07-14", "BK0001.DC", "000002.SZ", "股票二"),
                ("2026-07-14", "BK0002.DC", "000003.SH", "股票三"),
            ]
        )
        prod = _FakeProdResource(_FakeConnection(cursor))
        with tempfile.TemporaryDirectory() as temp_dir:
            result = export_dc_member_partition_from_prod_db(
                lake_root_path=Path(temp_dir),
                duckdb_resource=_MemoryDuckDB(),
                prod_postgres=prod,
                partition_key="2026-07-14",
                chunk_size=2,
                cursor_itersize=2,
            )

        sql, params = cursor.executed
        self.assertEqual(params[0].isoformat(), "2026-07-14")
        self.assertNotIn("*", sql)
        self.assertEqual(cursor.fetchmany_calls, [2, 2, 2])
        self.assertTrue(cursor.closed)
        self.assertTrue(prod.rollback_called)
        self.assertEqual(result.source_method, "prod_db_readonly_export")
        self.assertEqual(result.source_row_count, 3)

    def test_cross_chunk_duplicate_fails_without_replacing_existing_file(self):
        rows = [
            ("2026-07-14", "BK0001.DC", "000001.SZ", "股票一"),
            ("2026-07-14", "BK0001.DC", "000001.SZ", "股票一"),
        ]
        cursor = _FakeCursor(rows)
        prod = _FakeProdResource(_FakeConnection(cursor))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "raw/board/dc_member/trade_date=2026-07-14/part-000.parquet"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"existing-target")
            with self.assertRaises(DcBoardRawValidationError):
                export_dc_member_partition_from_prod_db(
                    lake_root_path=root,
                    duckdb_resource=_MemoryDuckDB(),
                    prod_postgres=prod,
                    partition_key="2026-07-14",
                    chunk_size=1,
                )
            self.assertEqual(target.read_bytes(), b"existing-target")

    def test_sql_contract_is_fixed_projection(self):
        normalized = " ".join(DC_MEMBER_BOOTSTRAP_SELECT_SQL.split()).lower()
        self.assertIn("trade_date, ts_code, con_code, name", normalized)
        self.assertNotIn("select *", normalized)


if __name__ == "__main__":
    unittest.main()
