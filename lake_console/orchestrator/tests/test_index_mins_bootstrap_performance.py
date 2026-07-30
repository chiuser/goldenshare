from datetime import date, timedelta
from pathlib import Path
import tempfile
import time
import unittest

from orchestrator.defs.bootstrap.index_mins_bootstrap_plan import run_dry_run
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.prod_db.index_mins import (
    IndexMinsActivePool,
    ProdIndexMinsSourceRangeProbe,
)
from tests.test_index_mins_bootstrap_plan import (
    _FakeProd,
    _MemoryDuckDB,
    _readiness,
)


def _write_calendar(root: Path, dates: tuple[str, ...]) -> None:
    import duckdb

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


class IndexMinsBootstrapPerformanceTests(unittest.TestCase):
    def test_sixty_date_dry_run_stays_bounded_without_target_deep_scan(self) -> None:
        dates = tuple(
            (date(2025, 1, 2) + timedelta(days=index)).isoformat()
            for index in range(60)
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_calendar(root, dates)

            def load_pool(*, prod_postgres):
                return IndexMinsActivePool(
                    codes=("000001.SH", "399001.SZ"),
                    code_set_hash="a" * 64,
                )

            def probe(*, prod_postgres, trade_dates, effective_codes, **kwargs):
                return ProdIndexMinsSourceRangeProbe(
                    readiness_by_date=tuple(_readiness(value) for value in trade_dates),
                    query_count=1,
                    elapsed_ms=1,
                )

            started = time.perf_counter()
            report = run_dry_run(
                lake_root=root,
                prod_postgres=_FakeProd(),
                duckdb_resource=_MemoryDuckDB(),
                active_pool_loader=load_pool,
                source_probe_runner=probe,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000

        self.assertFalse(report.should_stop)
        self.assertEqual(report.source_probe.query_count, 1)
        self.assertEqual(report.expected_file_count, 60 * 12)
        self.assertLess(elapsed_ms, 5_000)


if __name__ == "__main__":
    unittest.main()
