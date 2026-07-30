from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

import duckdb

from orchestrator.defs.bootstrap.index_mins_bootstrap_plan import (
    IndexMinsBootstrapPlanError,
    build_date_plan,
    run_dry_run,
)
from orchestrator.defs.paths import raw_index_mins_path, silver_trade_calendar_path
from orchestrator.defs.prod_db.index_mins import (
    IndexMinsActivePool,
    ProdIndexMinsFrequencyReadiness,
    ProdIndexMinsSourceRangeProbe,
    ProdIndexMinsSourceReadiness,
)


class _MemoryDuckDB:
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


class _FakeProd:
    pass


def _calendar(root: Path, dates: tuple[str, ...]) -> None:
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        values = ", ".join(f"(DATE '{value}', 'SSE', true)" for value in dates)
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(trade_date, exchange, is_open)) TO ? (FORMAT PARQUET)",
            [str(path)],
        )
    finally:
        connection.close()


def _readiness(trade_date: str, *, row_count: int = 10) -> ProdIndexMinsSourceReadiness:
    coverages = tuple(
        ProdIndexMinsFrequencyReadiness(
            source_freq=source_freq,
            expected_code_count=2,
            returned_code_count=2,
            source_row_count=row_count,
            distinct_key_count=row_count,
            min_trade_time=datetime.fromisoformat(f"{trade_date} 09:30:00"),
            max_trade_time=datetime.fromisoformat(f"{trade_date} 15:00:00"),
        )
        for source_freq in ("1min", "5min", "15min", "30min", "60min")
    )
    return ProdIndexMinsSourceReadiness(
        trade_date=trade_date,
        expected_code_count=2,
        expected_code_set_hash="a" * 64,
        frequency_coverages=coverages,
        elapsed_ms=1,
    )


class IndexMinsBootstrapPlanTests(unittest.TestCase):
    def test_date_plan_uses_sse_open_dates_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _calendar(root, ("2025-01-02", "2025-01-03", "2025-01-06"))
            connection = duckdb.connect(":memory:")
            try:
                plan = build_date_plan(
                    connection=connection,
                    lake_root=root,
                    end_date="2025-01-03",
                )
            finally:
                connection.close()
        self.assertEqual(plan.expected_trade_dates, ("2025-01-02", "2025-01-03"))
        self.assertEqual(plan.start_date, "2025-01-02")
        self.assertEqual(plan.to_dict()["expected_date_count"], 2)
        self.assertEqual(len(plan.fingerprint), 64)

    def test_future_end_date_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _calendar(root, ("2025-01-02", "2025-01-03"))
            connection = duckdb.connect(":memory:")
            try:
                with self.assertRaises(IndexMinsBootstrapPlanError):
                    build_date_plan(
                        connection=connection,
                        lake_root=root,
                        end_date=(date.today() + timedelta(days=1)).isoformat(),
                    )
            finally:
                connection.close()

    def test_duplicate_calendar_dates_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _calendar(root, ("2025-01-02", "2025-01-02"))
            connection = duckdb.connect(":memory:")
            try:
                with self.assertRaises(IndexMinsBootstrapPlanError):
                    build_date_plan(connection=connection, lake_root=root)
            finally:
                connection.close()

    def test_dry_run_reports_source_budget_and_target_counts(self) -> None:
        dates = ("2025-01-02", "2025-01-03")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _calendar(root, dates)

            def load_pool(*, prod_postgres):
                return IndexMinsActivePool(
                    codes=("000001.SH", "399001.SZ"),
                    code_set_hash="a" * 64,
                )

            def probe(*, prod_postgres, trade_dates, effective_codes, **kwargs):
                readiness = tuple(_readiness(value) for value in trade_dates)
                return ProdIndexMinsSourceRangeProbe(
                readiness_by_date=readiness,
                    query_count=1,
                    elapsed_ms=3,
                )

            report = run_dry_run(
                lake_root=root,
                prod_postgres=_FakeProd(),
                duckdb_resource=_MemoryDuckDB(),
                active_pool_loader=load_pool,
                source_probe_runner=probe,
            )

        self.assertFalse(report.should_stop)
        self.assertEqual(report.expected_raw_file_count, 10)
        self.assertEqual(report.expected_silver_file_count, 14)
        self.assertEqual(report.source_probe.query_count, 1)
        self.assertEqual(report.target_audits[0].missing_count, 10)
        self.assertEqual(report.target_audits[1].missing_count, 14)
        self.assertGreater(report.disk_budget.estimated_required_bytes, 0)

    def test_existing_invalid_target_blocks_without_writing(self) -> None:
        dates = ("2025-01-02",)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _calendar(root, dates)
            path = raw_index_mins_path(root, "1min", dates[0])
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = duckdb.connect(":memory:")
            try:
                connection.execute(
                    "COPY (SELECT 1 AS wrong_column) TO ? (FORMAT PARQUET)",
                    [str(path)],
                )
            finally:
                connection.close()

            def load_pool(*, prod_postgres):
                return IndexMinsActivePool(
                    codes=("000001.SH", "399001.SZ"),
                    code_set_hash="a" * 64,
                )

            def probe(*, prod_postgres, trade_dates, effective_codes, **kwargs):
                return ProdIndexMinsSourceRangeProbe(
                    readiness_by_date=tuple(_readiness(value) for value in trade_dates),
                    query_count=5,
                    elapsed_ms=1,
                )

            report = run_dry_run(
                lake_root=root,
                prod_postgres=_FakeProd(),
                duckdb_resource=_MemoryDuckDB(),
                active_pool_loader=load_pool,
                source_probe_runner=probe,
            )
            self.assertTrue(report.should_stop)
            self.assertIn("invalid_existing_target", report.stop_reason_codes)
            self.assertEqual(report.target_audits[0].invalid_existing_count, 1)
            self.assertTrue(path.exists())

    def test_existing_valid_target_is_checked_in_one_batch_metric_query(self) -> None:
        dates = ("2025-01-02",)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _calendar(root, dates)
            path = raw_index_mins_path(root, "1min", dates[0])
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = duckdb.connect(":memory:")
            try:
                connection.execute(
                    """
                    COPY (
                      SELECT
                        '000001.SH'::VARCHAR AS ts_code,
                        '1min'::VARCHAR AS freq,
                        TIMESTAMP '2025-01-02 09:30:00' AS trade_time,
                        1.0::DOUBLE AS open,
                        1.1::DOUBLE AS close,
                        1.2::DOUBLE AS high,
                        0.9::DOUBLE AS low,
                        10.0::DOUBLE AS vol,
                        20.0::DOUBLE AS amount,
                        'SSE'::VARCHAR AS exchange,
                        1.05::DOUBLE AS vwap
                    ) TO ? (FORMAT PARQUET)
                    """,
                    [str(path)],
                )
            finally:
                connection.close()

            def load_pool(*, prod_postgres):
                return IndexMinsActivePool(
                    codes=("000001.SH", "399001.SZ"),
                    code_set_hash="a" * 64,
                )

            def probe(*, prod_postgres, trade_dates, effective_codes, **kwargs):
                return ProdIndexMinsSourceRangeProbe(
                    readiness_by_date=tuple(_readiness(value) for value in trade_dates),
                    query_count=5,
                    elapsed_ms=1,
                )

            report = run_dry_run(
                lake_root=root,
                prod_postgres=_FakeProd(),
                duckdb_resource=_MemoryDuckDB(),
                active_pool_loader=load_pool,
                source_probe_runner=probe,
            )

        self.assertFalse(report.should_stop)
        self.assertEqual(report.target_audits[0].valid_existing_count, 1)
        self.assertEqual(report.target_audits[0].invalid_existing_count, 0)
        self.assertGreater(report.target_audits[0].existing_row_count, 0)

    def test_cli_has_no_lake_or_event_write_path(self) -> None:
        cli_path = Path(__file__).parents[1] / "src/orchestrator/defs/bootstrap/index_mins_bootstrap_cli.py"
        source = cli_path.read_text(encoding="utf-8")
        self.assertNotIn("os.replace", source)
        self.assertNotIn("report_runless_asset_event", source)
        self.assertNotIn("confirm-lake-write", source)
        self.assertIn('subparsers.add_parser("dry-run")', source)


if __name__ == "__main__":
    unittest.main()
