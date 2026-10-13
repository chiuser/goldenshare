"""Current listing applies only to factor Silver, including old quote dates."""

import hashlib
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import duckdb

from orchestrator.defs.asset_guards.adj_factor_lake_readiness import (
    SILVER_ADJ_FACTOR_LISTED_STOCK_ONLY_CHECK,
    assess_silver_adj_factor_lifecycle_rebuildability,
    batch_silver_adj_factor_lake_readiness,
)
from orchestrator.defs.assets.adj_factor import write_silver_adj_factor_partition
from orchestrator.defs.checks.adj_factor_checks import audit_adj_factor_candidate_rules
from orchestrator.defs.duckdb_sql import (
    duckdb_string,
    silver_cny_stock_lifecycle_select,
)
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.resources import DuckDBResource
from tests.test_adj_factor_checks import (
    _write_raw_adj_factor_file,
    _write_silver_adj_factor_file,
    _write_silver_stock_lifecycle_file,
)
from tests.test_adj_factor_lifecycle_rebuildability import _readiness_status

DAY = "2026-06-05"
HISTORICAL_DAY = "2020-02-28"


class CurrentListedFactorPolicyTests(TestCase):
    def test_ten_day_full_market_readiness_stays_batched(self):
        class CountedConnection:
            def __init__(self, connection):
                self.connection = connection
                self.queries = []

            def execute(self, sql, *args):
                self.queries.append(sql)
                return self.connection.execute(sql, *args)

        with TemporaryDirectory() as directory, duckdb.connect(":memory:") as connection:
            root = Path(directory)
            life = silver_stock_lifecycle_path(root)
            life.parent.mkdir(parents=True)
            connection.execute(f"""COPY (
                SELECT printf('%06d.SZ',range)::VARCHAR ts_code,true is_cny_stock,
                    'L'::VARCHAR list_status,DATE '2010-01-01' list_date,NULL::DATE delist_date
                FROM range(1,5001)
                UNION ALL SELECT '600000.SH',true,'D',DATE '2010-01-01',DATE '2026-04-01'
            ) TO {duckdb_string(life)} (FORMAT PARQUET)""")
            days = tuple((date(2026, 6, 1) + timedelta(days=offset)).isoformat() for offset in range(10))
            for day in days:
                for raw in (True, False):
                    path = raw_adj_factor_path(root, day) if raw else silver_adj_factor_path(root, day)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    day_sql = duckdb_string(day.replace("-", "")) if raw else f"DATE {duckdb_string(day)}"
                    stock_sql = "SELECT ts_code FROM read_parquet(" + duckdb_string(life) + ")"
                    if not raw:
                        stock_sql += " WHERE list_status='L'"
                    connection.execute(f"""COPY (
                        SELECT ts_code,{day_sql} AS trade_date,1.12345678::DOUBLE adj_factor
                        FROM ({stock_sql})
                    ) TO {duckdb_string(path)} (FORMAT PARQUET)""")
            counted = CountedConnection(connection)
            batch = batch_silver_adj_factor_lake_readiness(
                connection=counted, lake_root=root, expected_trade_dates=days, registered_trade_days=days,
            )
        self.assertTrue(all(status.ready for status in batch.statuses_by_trade_date.values()))
        self.assertEqual(batch.scanned_file_count, 20)
        self.assertEqual(len(counted.queries), 42)
        self.assertLess(batch.elapsed_ms, 10_000)

    def test_generation_checks_and_readiness_exclude_all_non_current_stocks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            life = _write_silver_stock_lifecycle_file(root, (
                ("000001.SZ", "CNY", "L", "2010-01-01", None),
                ("000002.SZ", "CNY", "D", "2010-01-01", "2026-06-30"),
                ("000003.SZ", "CNY", "P", "2010-01-01", None),
                ("200001.SZ", "HKD", "L", "2010-01-01", None),
                ("000004.SZ", "CNY", "L", "2026-06-06", None),
            ))
            raw = _write_raw_adj_factor_file(root, HISTORICAL_DAY, (
                ("000001.SZ", "20200228", 1.12345678),
                ("000002.SZ", "20200228", 2.2),
                ("000003.SZ", "20200228", 3.3),
                ("200001.SZ", "20200228", 4.4),
                ("000004.SZ", "20200228", 5.5),
                ("999999.SZ", "20200228", 6.6),
            ))
            raw_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
            result = write_silver_adj_factor_partition(
                lake_root=root, duckdb=DuckDBResource(), partition_key=HISTORICAL_DAY,
            )
            with duckdb.connect(":memory:") as connection:
                rows = connection.execute(
                    "SELECT ts_code,adj_factor FROM read_parquet(?,hive_partitioning=false)",
                    [str(result.silver_file_path)],
                ).fetchall()
                rules = audit_adj_factor_candidate_rules(
                    connection, result.silver_file_path, HISTORICAL_DAY,
                    raw=False, lifecycle_path=life,
                )
                status = batch_silver_adj_factor_lake_readiness(
                    connection=connection, lake_root=root,
                    expected_trade_dates=(HISTORICAL_DAY,),
                    registered_trade_days=(HISTORICAL_DAY,),
                ).statuses_by_trade_date[HISTORICAL_DAY]
                history_codes = connection.execute(
                    f"SELECT ts_code FROM ({silver_cny_stock_lifecycle_select(life)})"
                ).fetchall()
            self.assertEqual(rows, [("000001.SZ", 1.12345678)])
            self.assertEqual(result.lifecycle_stock_count, 4)
            self.assertEqual(result.rejected_row_count, 5)
            self.assertTrue(status.ready, status)
            self.assertTrue(all(value == 0 for key, value in rules.items() if key != "rows"))
            self.assertIn(("000002.SZ",), history_codes)
            self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(), raw_hash)

    def test_listing_change_removes_earlier_history_and_missing_retired_raw_is_allowed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_raw_adj_factor_file(root, DAY, (("000001.SZ", "20260605", 1.5),))
            life = _write_silver_stock_lifecycle_file(root, (
                ("000001.SZ", "CNY", "L", "2010-01-01", None),
                ("000002.SZ", "CNY", "L", "2010-01-01", None),
            ))
            silver = _write_silver_adj_factor_file(root, DAY, (
                ("000001.SZ", DAY, 1.5), ("000002.SZ", DAY, 2.5),
            ))
            _write_silver_stock_lifecycle_file(root, (
                ("000001.SZ", "CNY", "L", "2010-01-01", None),
                ("000002.SZ", "CNY", "D", "2010-01-01", "2026-06-30"),
            ))
            with duckdb.connect(":memory:") as connection:
                old_rules = audit_adj_factor_candidate_rules(
                    connection, silver, DAY, raw=False, lifecycle_path=life,
                )
                assessment = assess_silver_adj_factor_lifecycle_rebuildability(
                    connection=connection, lake_root=root, trade_date=DAY,
                    raw_status=_readiness_status(ready=True),
                    silver_status=_readiness_status(
                        ready=False, failed_check_names=(SILVER_ADJ_FACTOR_LISTED_STOCK_ONLY_CHECK,),
                    ),
                )
            self.assertEqual(old_rules["lifecycle_invalid"], 1)
            self.assertEqual(old_rules["coverage_unexpected"], 1)
            self.assertTrue(assessment.eligible)
            self.assertEqual(assessment.expected_code_count, 1)
            write_silver_adj_factor_partition(
                lake_root=root, duckdb=DuckDBResource(), partition_key=DAY, overwrite=True,
            )
            with duckdb.connect(":memory:") as connection:
                rules = audit_adj_factor_candidate_rules(
                    connection, silver, DAY, raw=False, lifecycle_path=life,
                )
            self.assertEqual(rules["coverage_missing"], 0)
            self.assertEqual(rules["coverage_unexpected"], 0)

    def test_current_listed_missing_factor_still_fails(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            life = _write_silver_stock_lifecycle_file(root, (
                ("000001.SZ", "CNY", "L", "2010-01-01", None),
                ("000002.SZ", "CNY", "L", "2010-01-01", None),
                ("000003.SZ", "CNY", "D", "2010-01-01", "2026-06-30"),
            ))
            silver = _write_silver_adj_factor_file(root, DAY, (("000001.SZ", DAY, 1.5),))
            with duckdb.connect(":memory:") as connection:
                rules = audit_adj_factor_candidate_rules(
                    connection, silver, DAY, raw=False, lifecycle_path=life,
                )
            self.assertEqual(rules["coverage_missing"], 1)
