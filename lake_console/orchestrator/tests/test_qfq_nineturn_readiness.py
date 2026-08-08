import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.asset_guards.qfq_nineturn_lake_readiness import (
    batch_gold_stock_daily_qfq_nineturn_readiness,
)
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_path,
)


TRADE_DATE = "2026-08-07"


def _write_source_and_target(connection, root: Path) -> None:
    source = gold_stock_daily_qfq_path(root, TRADE_DATE)
    target = gold_stock_daily_qfq_nineturn_path(root, TRADE_DATE)
    source.parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT '000001.SZ'::VARCHAR AS ts_code,
            DATE '{TRADE_DATE}' AS trade_date,
            10.0::DOUBLE AS close
        ) TO '{source}' (FORMAT PARQUET)
        """
    )
    connection.execute(
        f"""
        COPY (
          SELECT '000001.SZ'::VARCHAR AS ts_code,
            DATE '{TRADE_DATE}' AS trade_date,
            10.0::DOUBLE AS close_qfq,
            1::INTEGER AS up_count,
            0::INTEGER AS down_count,
            NULL::VARCHAR AS nine_up_turn,
            NULL::VARCHAR AS nine_down_turn
        ) TO '{target}' (FORMAT PARQUET)
        """
    )


class QfqNineturnReadinessTests(unittest.TestCase):
    def test_daily_batch_readiness_uses_file_and_source_key_facts(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            _write_source_and_target(connection, root)

            batch = batch_gold_stock_daily_qfq_nineturn_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=(TRADE_DATE,),
                registered_trade_days=(TRADE_DATE,),
            )

        self.assertTrue(batch.status_for_trade_date(TRADE_DATE).ready)
        self.assertEqual(batch.freq_count, 1)

    def test_unregistered_partition_fails_closed(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            _write_source_and_target(connection, root)

            batch = batch_gold_stock_daily_qfq_nineturn_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=(TRADE_DATE,),
                registered_trade_days=(),
            )

        status = batch.status_for_trade_date(TRADE_DATE)
        self.assertFalse(status.ready)
        self.assertIn("partition_not_registered", status.failed_check_names[0])

    def test_daily_window_is_bounded_to_ten_dates(self) -> None:
        dates = tuple(f"2026-08-{day:02d}" for day in range(1, 12))
        with duckdb.connect(":memory:") as connection:
            with self.assertRaisesRegex(ValueError, "at most 10"):
                batch_gold_stock_daily_qfq_nineturn_readiness(
                    connection=connection,
                    lake_root=Path("/tmp/not-used"),
                    expected_trade_dates=dates,
                    registered_trade_days=dates,
                )


if __name__ == "__main__":
    unittest.main()
