from contextlib import contextmanager
from datetime import datetime
import unittest

from orchestrator.defs.prod_db.index_mins import (
    PROD_INDEX_MINS_ACTIVE_POOL_QUERY,
    PROD_INDEX_MINS_DUCKDB_ATTACH_OPTIONS,
    PROD_INDEX_MINS_DUCKDB_ATTACHED_DATABASE,
    PROD_INDEX_MINS_RANGE_QUERY,
    PROD_INDEX_MINS_SOURCE_PROBE_QUERY,
    build_prod_index_mins_duckdb_source_sql,
    build_prod_index_mins_range_query,
    load_prod_index_mins_active_pool,
    probe_prod_index_mins_source,
    validate_prod_index_mins_query_contract,
)


class FakeCursor:
    def __init__(self, *, pages=(), aggregate_rows=(), error_on_execute=False):
        self.pages = list(pages)
        self.aggregate_rows = list(aggregate_rows)
        self.error_on_execute = error_on_execute
        self.executed = []
        self.fetchmany_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        if self.error_on_execute:
            raise RuntimeError("source query failed")
        self.executed.append((sql, params))

    def fetchmany(self, size):
        self.fetchmany_calls.append(size)
        if self.pages:
            return self.pages.pop(0)
        return []

    def fetchone(self):
        if not self.aggregate_rows:
            return None
        return self.aggregate_rows.pop(0)

    def fetchall(self):
        raise AssertionError("active pool loader must use bounded fetchmany")


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_instance


class FakeProdPostgres:
    def __init__(self, connection):
        self.connection = connection
        self.connection_count = 0

    @contextmanager
    def connect_readonly_transaction(self):
        self.connection_count += 1
        yield self.connection


def _aggregate_rows(*, source_row_count=10, returned_code_count=2, distinct_key_count=10):
    return [
        (
            source_row_count,
            returned_code_count,
            distinct_key_count,
            datetime(2026, 7, 28, 9, 30),
            datetime(2026, 7, 28, 15, 0),
        )
        for _ in range(5)
    ]


class IndexMinsProdDbTests(unittest.TestCase):
    def test_duckdb_source_query_is_explicit_and_read_only(self) -> None:
        sql = build_prod_index_mins_duckdb_source_sql(
            source_freq="1min",
            start_datetime="2026-07-27 00:00:00",
            end_datetime="2026-07-28 00:00:00",
            effective_codes=("000001.SZ", "000300.SH"),
        )
        normalized = " ".join(sql.lower().split())
        self.assertNotIn("select *", normalized)
        self.assertIn(
            f"from {PROD_INDEX_MINS_DUCKDB_ATTACHED_DATABASE}.raw_tushare.index_mins",
            normalized,
        )
        self.assertIn("trade_time >= timestamp", normalized)
        self.assertIn("trade_time < timestamp", normalized)
        self.assertIn("cast(ts_code as varchar) in", normalized)
        self.assertEqual(PROD_INDEX_MINS_DUCKDB_ATTACH_OPTIONS, "TYPE POSTGRES, READ_ONLY")

    def test_query_contract_is_explicit_and_bounded(self) -> None:
        validate_prod_index_mins_query_contract()
        sql, params = build_prod_index_mins_range_query(
            source_freq="1min",
            start_datetime="2026-07-28 00:00:00",
            end_datetime="2026-07-29 00:00:00",
            effective_codes=("000001.SH", "399001.SZ"),
        )
        normalized_sql = " ".join(sql.lower().split())
        self.assertEqual(sql, PROD_INDEX_MINS_RANGE_QUERY)
        self.assertNotIn("select *", normalized_sql)
        self.assertIn("from raw_tushare.index_mins", normalized_sql)
        self.assertIn("freq = %s", normalized_sql)
        self.assertIn("trade_time >= %s::timestamp", normalized_sql)
        self.assertIn("trade_time < %s::timestamp", normalized_sql)
        self.assertIn("ts_code = any(%s::text[])", normalized_sql)
        self.assertIn("order by ts_code, trade_time", normalized_sql)
        self.assertEqual(params[0], "1min")
        self.assertEqual(params[3], ["000001.SH", "399001.SZ"])

    def test_range_query_rejects_empty_or_reversed_window(self) -> None:
        with self.assertRaises(ValueError):
            build_prod_index_mins_range_query(
                source_freq="1min",
                start_datetime="2026-07-29 00:00:00",
                end_datetime="2026-07-28 00:00:00",
                effective_codes=("000001.SH",),
            )
        with self.assertRaises(ValueError):
            build_prod_index_mins_range_query(
                source_freq="1min",
                start_datetime="2026-07-28 00:00:00",
                end_datetime="2026-07-29 00:00:00",
                effective_codes=(),
            )

    def test_active_pool_is_streamed_and_hashed(self) -> None:
        cursor = FakeCursor(
            pages=[[("399001.SZ",)], [("000001.SH",)], []],
        )
        resource = FakeProdPostgres(FakeConnection(cursor))
        pool = load_prod_index_mins_active_pool(prod_postgres=resource)

        self.assertEqual(pool.codes, ("399001.SZ", "000001.SH"))
        self.assertEqual(len(pool.code_set_hash), 64)
        self.assertEqual(resource.connection_count, 1)
        self.assertEqual(len(cursor.executed), 1)
        self.assertEqual(cursor.executed[0][0], PROD_INDEX_MINS_ACTIVE_POOL_QUERY)
        self.assertEqual(cursor.executed[0][1], ("index_mins",))
        self.assertEqual(cursor.fetchmany_calls, [500, 500, 500])

    def test_active_pool_rejects_duplicate_and_unbounded_codes(self) -> None:
        duplicate_cursor = FakeCursor(
            pages=[[("000001.SH",), ("000001.SH",)], []],
        )
        with self.assertRaises(ValueError):
            load_prod_index_mins_active_pool(
                prod_postgres=FakeProdPostgres(FakeConnection(duplicate_cursor)),
            )

        oversized_cursor = FakeCursor(
            pages=[[(f"{index:06d}.SH",) for index in range(2)], []],
        )
        with self.assertRaises(ValueError):
            load_prod_index_mins_active_pool(
                prod_postgres=FakeProdPostgres(FakeConnection(oversized_cursor)),
                max_codes=1,
            )

    def test_source_probe_uses_one_connection_and_five_aggregate_queries(self) -> None:
        cursor = FakeCursor(aggregate_rows=_aggregate_rows())
        resource = FakeProdPostgres(FakeConnection(cursor))
        readiness = probe_prod_index_mins_source(
            prod_postgres=resource,
            trade_date="2026-07-28",
            effective_codes=("000001.SH", "399001.SZ"),
        )

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.reason_code, "prod_index_mins_source_ready")
        self.assertEqual(len(readiness.frequency_coverages), 5)
        self.assertEqual(resource.connection_count, 1)
        self.assertEqual(len(cursor.executed), 5)
        self.assertTrue(all(query == PROD_INDEX_MINS_SOURCE_PROBE_QUERY for query, _ in cursor.executed))
        self.assertEqual(
            [params[0] for _, params in cursor.executed],
            ["1min", "5min", "15min", "30min", "60min"],
        )

    def test_source_probe_fails_closed_for_empty_coverage(self) -> None:
        rows = _aggregate_rows()
        rows[2] = (0, 0, 0, None, None)
        cursor = FakeCursor(aggregate_rows=rows)
        readiness = probe_prod_index_mins_source(
            prod_postgres=FakeProdPostgres(FakeConnection(cursor)),
            trade_date="2026-07-28",
            effective_codes=("000001.SH", "399001.SZ"),
        )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason_code, "prod_index_mins_source_empty")

    def test_source_probe_fails_closed_for_duplicate_keys(self) -> None:
        rows = _aggregate_rows(source_row_count=11, distinct_key_count=10)
        cursor = FakeCursor(aggregate_rows=rows)
        readiness = probe_prod_index_mins_source(
            prod_postgres=FakeProdPostgres(FakeConnection(cursor)),
            trade_date="2026-07-28",
            effective_codes=("000001.SH", "399001.SZ"),
        )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason_code, "prod_index_mins_source_duplicate_key")

    def test_source_probe_fails_closed_for_query_error(self) -> None:
        cursor = FakeCursor(error_on_execute=True)
        readiness = probe_prod_index_mins_source(
            prod_postgres=FakeProdPostgres(FakeConnection(cursor)),
            trade_date="2026-07-28",
            effective_codes=("000001.SH", "399001.SZ"),
        )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason_code, "prod_index_mins_source_query_error")
        self.assertEqual(readiness.scan_error_code, "RuntimeError")


if __name__ == "__main__":
    unittest.main()
