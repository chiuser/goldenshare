from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import duckdb

from orchestrator.defs.bootstrap import dc_board_bootstrap_cli
from orchestrator.defs.bootstrap.dc_board_bootstrap_plan import (
    DcBoardBootstrapPlanError,
    audit_tushare_partition,
    audit_prod_member_partition,
    audit_prod_member_partitions,
    build_date_plans,
    run_dry_run,
)
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.dc_board import (
    DC_INDEX_FIELDS,
    DC_INDEX_TYPES,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


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


class _FakeTushare:
    def call(self, api_name, params, fields):
        if api_name == "dc_index":
            idx_type = params["idx_type"]
            if params["offset"]:
                return TushareResult(rows=[], columns=tuple(fields), metadata={})
            return TushareResult(
                rows=[
                    {
                        "ts_code": f"BK{DC_INDEX_TYPES.index(idx_type) + 1:04d}.DC",
                        "trade_date": params["trade_date"],
                        "name": "板块",
                        "leading": "股票",
                        "leading_code": "000001.SZ",
                        "pct_change": 1.0,
                        "leading_pct": 1.0,
                        "total_mv": 1.0,
                        "turnover_rate": 1.0,
                        "up_num": 1,
                        "down_num": 1,
                        "idx_type": idx_type,
                        "level": "L1",
                    }
                ],
                columns=tuple(fields),
                metadata={},
            )
        raise AssertionError(api_name)


class _FakeProd:
    def connect_readonly_transaction(self):
        raise AssertionError("dc_index-only dry-run must not access Prod DB")


class _UnavailableProd:
    def connect_readonly_transaction(self):
        raise RuntimeError("prod credentials are unavailable")


class _FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.fetchmany_calls = []
        self.execute_sql = []
        self.itersize = None
        self.closed = False

    def execute(self, sql, _params):
        self.execute_sql.append(sql)
        return None

    def fetchmany(self, size):
        self.fetchmany_calls.append(size)
        page, self.rows = self.rows[:size], self.rows[size:]
        return page

    def fetchall(self):
        raise AssertionError("Prod audit must not call fetchall().")

    def close(self):
        self.closed = True


class _FakeProdMember:
    def __init__(self, cursor):
        self.cursor_value = cursor
        self.rollback_called = False
        self.connection_count = 0

    def connect_readonly_transaction(self):
        owner = self
        owner.connection_count += 1

        class _Context:
            def __enter__(self):
                return owner

            def __exit__(self, exc_type, exc, tb):
                owner.rollback_called = True
                return False

        return _Context()

    def cursor(self, name):
        self.cursor_name = name
        return self.cursor_value


class DcBoardBootstrapPlanTests(unittest.TestCase):
    def _calendar(self, root: Path, rows: list[tuple[str, str, bool]]) -> Path:
        path = root / "silver/calendar/trade_calendar/full/part-000.parquet"
        path.parent.mkdir(parents=True)
        connection = duckdb.connect(":memory:")
        values = ", ".join(
            f"('{exchange}', CAST('{trade_date}' AS DATE), {str(is_open).lower()}, NULL::DATE)"
            for exchange, trade_date, is_open in rows
        )
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(exchange, trade_date, is_open, pretrade_date)) "
            f"TO ? (FORMAT PARQUET)",
            [str(path)],
        )
        connection.close()
        return path

    def test_date_plans_use_standard_trade_date_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calendar = self._calendar(
                root,
                [("SSE", "2024-12-20", True), ("SSE", "2024-12-23", True)],
            )
            connection = duckdb.connect(":memory:")
            plans = build_date_plans(
                connection=connection,
                calendar_path=calendar,
                end_date="2024-12-23",
                datasets=("dc_index",),
            )
            connection.close()

        self.assertEqual(plans[0].expected_trade_dates, ("2024-12-20", "2024-12-23"))
        self.assertEqual(len(plans[0].fingerprint), 64)

    def test_duplicate_calendar_date_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calendar = self._calendar(
                root,
                [("SSE", "2024-12-20", True), ("SSE", "2024-12-20", True)],
            )
            connection = duckdb.connect(":memory:")
            with self.assertRaisesRegex(DcBoardBootstrapPlanError, "duplicate SSE open dates"):
                build_date_plans(
                    connection=connection,
                    calendar_path=calendar,
                    datasets=("dc_index",),
                )
            connection.close()

    def test_future_end_date_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calendar = self._calendar(root, [("SSE", "2024-12-20", True)])
            connection = duckdb.connect(":memory:")
            with self.assertRaisesRegex(DcBoardBootstrapPlanError, "in the future"):
                build_date_plans(
                    connection=connection,
                    calendar_path=calendar,
                    end_date="2999-01-01",
                    datasets=("dc_index",),
                )
            connection.close()

    def test_tushare_source_audit_does_not_write_a_target(self):
        policy = TushareRequestPolicy(
            minimum_interval_seconds=0,
            max_retries=0,
            max_requests=20,
            max_elapsed_seconds=10,
        )
        connection = duckdb.connect(":memory:")
        audit = audit_tushare_partition(
            connection=connection,
            tushare=_FakeTushare(),
            dataset="dc_index",
            trade_date="2024-12-20",
            policy=policy,
        )
        connection.close()

        self.assertFalse(audit.failed)
        self.assertEqual(audit.source_row_count, 3)
        self.assertEqual(audit.request_count, 3)

    def test_prod_member_audit_streams_chunks_and_rolls_back(self):
        cursor = _FakeCursor(
            [
                ("2024-12-20", "BK0001.DC", "000001.SZ", "股票一"),
                ("2024-12-20", "BK0001.DC", "000002.SZ", "股票二"),
            ]
        )
        prod = _FakeProdMember(cursor)
        connection = duckdb.connect(":memory:")
        audit = audit_prod_member_partition(
            connection=connection,
            prod_postgres=prod,
            trade_date="2024-12-20",
            chunk_size=1,
            cursor_itersize=1,
        )
        connection.close()

        self.assertFalse(audit.failed)
        self.assertEqual(audit.source_row_count, 2)
        self.assertEqual(audit.chunk_count, 2)
        self.assertEqual(cursor.fetchmany_calls, [1, 1, 1])
        self.assertTrue(cursor.closed)
        self.assertTrue(prod.rollback_called)

    def test_prod_member_range_audit_uses_one_cursor_and_keeps_date_boundaries(self):
        cursor = _FakeCursor(
            [
                ("2024-12-20", 2, 0, 0, 0, 0),
                ("2024-12-23", 1, 0, 0, 0, 0),
            ]
        )
        prod = _FakeProdMember(cursor)
        connection = duckdb.connect(":memory:")
        audits = audit_prod_member_partitions(
            connection=connection,
            prod_postgres=prod,
            expected_trade_dates=("2024-12-20", "2024-12-23"),
            chunk_size=1,
            cursor_itersize=1,
        )
        connection.close()

        self.assertEqual([audit.trade_date for audit in audits], ["2024-12-20", "2024-12-23"])
        self.assertEqual([audit.source_row_count for audit in audits], [2, 1])
        self.assertEqual([audit.chunk_count for audit in audits], [1, 2])
        self.assertEqual(prod.connection_count, 1)
        self.assertEqual(cursor.fetchmany_calls, [1, 1, 1])
        self.assertIn("trade_date, ts_code, con_code, name", cursor.execute_sql[0])
        self.assertNotIn("SELECT *", cursor.execute_sql[0])
        self.assertTrue(cursor.closed)
        self.assertTrue(prod.rollback_called)

    def test_dry_run_has_no_apply_command_and_reports_missing_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._calendar(root, [("SSE", "2024-12-20", True)])
            report = run_dry_run(
                lake_root=root,
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(),
                prod_postgres=_FakeProd(),
                datasets=("dc_index",),
                end_date="2024-12-20",
            )
            self.assertFalse(report.should_stop)
            self.assertEqual(report.target_audits[0].missing_count, 1)
            self.assertEqual(report.target_audits[1].missing_count, 1)
            self.assertEqual(report.expected_file_count, 2)

        with self.assertRaises(SystemExit):
            dc_board_bootstrap_cli._parser().parse_args(["apply"])

    def test_m7_planner_has_no_lake_or_dagster_write_path(self):
        source = Path(
            dc_board_bootstrap_cli.__file__
        ).with_name("dc_board_bootstrap_plan.py").read_text(encoding="utf-8")
        self.assertNotIn("report_runless_asset_event", source)
        self.assertNotIn("AssetMaterialization", source)
        self.assertNotIn("os.replace", source)

    def test_source_access_error_is_reported_without_writing_or_raising(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._calendar(root, [("SSE", "2024-12-20", True)])
            report = run_dry_run(
                lake_root=root,
                duckdb_resource=_MemoryDuckDB(),
                tushare=_FakeTushare(),
                prod_postgres=_UnavailableProd(),
                datasets=("dc_member",),
                end_date="2024-12-20",
            )

        self.assertTrue(report.should_stop)
        self.assertEqual(report.stop_reason_codes, ("source_audit_failed",))
        self.assertEqual(report.source_audits[0].failure_reason, "source_access_error")


if __name__ == "__main__":
    unittest.main()
