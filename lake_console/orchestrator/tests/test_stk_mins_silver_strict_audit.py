import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.audits.stk_mins_silver_strict_audit import (
    build_stk_mins_silver_audit_dry_run,
    run_stk_mins_silver_strict_audit,
)
from orchestrator.defs.paths import (
    raw_stk_mins_path,
    silver_namechange_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_suspend_daily_path,
)


PARTITION_KEY = "2026-05-29"


class StkMinsSilverStrictAuditTests(unittest.TestCase):
    def test_dry_run_counts_raw_partitions_and_dependencies(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory) / "lake"
            _write_complete_fixture(lake_root)

            plan = build_stk_mins_silver_audit_dry_run(
                lake_root=lake_root,
                output_dir=Path(directory) / "reports",
                partition_keys=(PARTITION_KEY,),
            )

            self.assertEqual(plan.raw_partition_counts[1], 1)
            self.assertEqual(plan.selected_partition_keys, (PARTITION_KEY,))
            self.assertEqual(plan.planned_asset_partition_count, 5)
            self.assertTrue(plan.dependency_status["silver_stock_basic"])
            self.assertTrue(plan.dependency_status["silver_stock_identity_map"])
            self.assertTrue(plan.dependency_status["silver_namechange"])

    def test_audit_writes_expected_csvs_and_anomalies(self) -> None:
        with TemporaryDirectory() as directory:
            lake_root = Path(directory) / "lake"
            output_dir = Path(directory) / "reports"
            _write_complete_fixture(lake_root)

            result = run_stk_mins_silver_strict_audit(
                lake_root=lake_root,
                output_dir=output_dir,
                partition_keys=(PARTITION_KEY,),
                sample_limit=5,
            )

            self.assertEqual(result["selected_partition_count"], 1)
            self.assertEqual(result["processed_asset_partition_count"], 5)
            expected_files = {
                "00_audit_summary.csv",
                "01_partition_coverage.csv",
                "02_time_grid_anomalies.csv",
                "03_exchange_anomalies.csv",
                "04_price_zero_null_anomalies.csv",
                "05_price_relation_anomalies.csv",
                "06_volume_amount_vwap_anomalies.csv",
                "07_identity_mapping_anomalies.csv",
                "08_mapped_duplicate_conflicts.csv",
                "09_stock_daily_suspend_universe_anomalies.csv",
                "10_name_timeline_coverage_anomalies.csv",
                "11_anomaly_samples.csv",
            }
            self.assertEqual(
                {path.name for path in output_dir.glob("*.csv")},
                expected_files,
            )

            time_row = _row_for_freq(output_dir / "02_time_grid_anomalies.csv", 1)
            self.assertEqual(time_row["failed_row_count"], "1")
            self.assertEqual(time_row["partition_date_mismatch_count"], "1")

            price_rows = _read_csv(output_dir / "04_price_zero_null_anomalies.csv")
            self.assertEqual(len(price_rows), 1)
            self.assertEqual(price_rows[0]["zero_price_fields"], "open")

            exchange_row = _row_for_freq(output_dir / "03_exchange_anomalies.csv", 1)
            self.assertEqual(exchange_row["suffix_unmapped_count"], "1")
            self.assertEqual(exchange_row["failed_row_count"], "1")

            identity_rows = _read_csv(output_dir / "07_identity_mapping_anomalies.csv")
            self.assertEqual(identity_rows, [])

            duplicate_row = _row_for_freq(output_dir / "08_mapped_duplicate_conflicts.csv", 1)
            self.assertEqual(duplicate_row["conflicting_duplicate_group_count"], "1")

            sample_text = (output_dir / "11_anomaly_samples.csv").read_text()
            self.assertIn("time_grid", sample_text)
            self.assertIn("mapped_duplicate_conflict", sample_text)


def _write_complete_fixture(lake_root: Path) -> None:
    _write_raw_fixture(raw_stk_mins_path(lake_root, 1, PARTITION_KEY))
    _write_empty_raw_files_for_other_freqs(lake_root)
    _write_stock_identity_map(silver_stock_identity_map_path(lake_root))
    _write_stock_basic(silver_stock_basic_path(lake_root))
    _write_namechange(silver_namechange_path(lake_root))
    _write_stock_daily(silver_stock_daily_path(lake_root, PARTITION_KEY))
    _write_suspend(silver_stock_suspend_daily_path(lake_root, PARTITION_KEY))


def _write_raw_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (
                VALUES
                  ('600000.SH', 1, TIMESTAMP '2026-05-29 09:30:00',
                   10.0, 10.0, 10.0, 10.0, 100::BIGINT, 1000.0, 'XSHG', 10.0),
                  ('600001.SH', 1, TIMESTAMP '2026-05-29 09:30:00',
                   10.0, 10.0, 10.0, 10.0, 100::BIGINT, 1000.0, 'XSHG', 10.0),
                  ('600002.SH', 1, TIMESTAMP '2026-05-29 09:30:00',
                   11.0, 11.0, 11.0, 11.0, 100::BIGINT, 1100.0, 'XSHG', 11.0),
                  ('000001.SZ', 1, TIMESTAMP '2026-05-30 12:00:00',
                   0.0, 10.0, 9.0, 10.0, 100::BIGINT, 1000.0, 'XSHG', 5.0),
                  ('999999.XX', 1, TIMESTAMP '2026-05-29 09:31:00',
                   10.0, 10.0, 10.0, 10.0, 100::BIGINT, 1000.0, 'XSHG', 10.0)
              ) AS raw(
                ts_code, freq, trade_time, open, close, high, low,
                vol, amount, exchange, vwap
              )
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _write_empty_raw_files_for_other_freqs(lake_root: Path) -> None:
    for freq in (5, 15, 30, 60):
        path = raw_stk_mins_path(lake_root, freq, PARTITION_KEY)
        path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(":memory:") as connection:
            connection.execute(
                f"""
                COPY (
                  SELECT
                    NULL::VARCHAR AS ts_code,
                    NULL::INTEGER AS freq,
                    NULL::TIMESTAMP AS trade_time,
                    NULL::DOUBLE AS open,
                    NULL::DOUBLE AS close,
                    NULL::DOUBLE AS high,
                    NULL::DOUBLE AS low,
                    NULL::BIGINT AS vol,
                    NULL::DOUBLE AS amount,
                    NULL::VARCHAR AS exchange,
                    NULL::DOUBLE AS vwap
                  WHERE false
                ) TO '{path.as_posix()}' (FORMAT PARQUET)
                """
            )


def _write_stock_identity_map(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (
                VALUES
                  ('600000.SH', '600000.SH', DATE '2000-01-01', NULL::DATE,
                   DATE '2000-01-01', NULL::DATE, 'stock_basic', 'confirmed',
                   'self', TIMESTAMPTZ '2026-05-29 00:00:00+08'),
                  ('600000.SH', '600001.SH', DATE '2000-01-01', NULL::DATE,
                   DATE '2000-01-01', NULL::DATE, 'namechange', 'inferred',
                   'duplicate', TIMESTAMPTZ '2026-05-29 00:00:00+08'),
                  ('600000.SH', '600002.SH', DATE '2000-01-01', NULL::DATE,
                   DATE '2000-01-01', NULL::DATE, 'namechange', 'inferred',
                   'duplicate', TIMESTAMPTZ '2026-05-29 00:00:00+08'),
                  ('000001.SZ', '000001.SZ', DATE '2000-01-01', NULL::DATE,
                   DATE '2000-01-01', NULL::DATE, 'stock_basic', 'confirmed',
                   'self', TIMESTAMPTZ '2026-05-29 00:00:00+08')
              ) AS identity_map(
                latest_ts_code, source_ts_code, valid_from, valid_to,
                effective_list_date, effective_delist_date, identity_source,
                confidence, reason, created_at
              )
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _write_stock_basic(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (
                VALUES
                  ('600000.SH', '600000', '浦发银行', '', '', '', 'SSE',
                   'L', DATE '2000-01-01', NULL, ''),
                  ('000001.SZ', '000001', '平安银行', '', '', '', 'SZSE',
                   'L', DATE '2000-01-01', NULL, '')
              ) AS stock_basic(
                ts_code, symbol, name, area, industry, market, exchange,
                list_status, list_date, delist_date, is_hs
              )
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _write_namechange(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (
                VALUES
                  ('600000.SH', '浦发银行', DATE '2000-01-01', NULL::DATE,
                   DATE '2000-01-01', 'self')
              ) AS namechange(
                ts_code, name, start_date, end_date, ann_date, change_reason
              )
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _write_stock_daily(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (
                VALUES
                  ('600000.SH', DATE '2026-05-29', 10.0, 10.0, 10.0, 10.0,
                   10.0, 0.0, 0.0, 100.0, 1000.0),
                  ('000001.SZ', DATE '2026-05-29', 10.0, 10.0, 10.0, 10.0,
                   10.0, 0.0, 0.0, 100.0, 1000.0)
              ) AS stock_daily(
                ts_code, trade_date, open, high, low, close, pre_close,
                change_amount, pct_chg, vol, amount
              )
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _write_suspend(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                NULL::VARCHAR AS ts_code,
                NULL::DATE AS trade_date,
                NULL::VARCHAR AS suspend_timing,
                NULL::VARCHAR AS suspend_type
              WHERE false
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _row_for_freq(path: Path, freq: int) -> dict[str, str]:
    for row in _read_csv(path):
        if row["freq"] == str(freq):
            return row
    raise AssertionError(f"Missing freq={freq} row in {path}")


if __name__ == "__main__":
    unittest.main()
