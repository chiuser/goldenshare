import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb

import orchestrator.defs.asset_guards.qfq_nineturn_lake_readiness as readiness_module
from orchestrator.defs.asset_guards.qfq_nineturn_lake_readiness import (
    batch_gold_stk_mins_qfq_nineturn_readiness,
    batch_gold_stock_daily_qfq_nineturn_readiness,
)
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_nineturn_path,
    gold_stk_mins_qfq_path,
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_path,
)
from orchestrator.defs.run_contracts.qfq_nineturn import QFQ_NINETURN_MINUTE_FREQS

TRADE_DATE = "2026-08-07"
MINUTE_TRADE_DATES = ("2026-08-06", TRADE_DATE)


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


def _write_minute_sources_and_targets(connection, root: Path) -> None:
    for freq in QFQ_NINETURN_MINUTE_FREQS:
        source = gold_stk_mins_qfq_path(root, freq, "000001.SZ", 2026)
        source.parent.mkdir(parents=True, exist_ok=True)
        connection.execute(
            f"""
            COPY (
              SELECT '000001.SZ'::VARCHAR AS ts_code,
                {freq}::INTEGER AS freq,
                trade_date::DATE AS trade_date,
                (trade_date::DATE + TIME '15:00:00')::TIMESTAMP AS trade_time,
                10.0::DOUBLE AS close
              FROM (VALUES {", ".join(f"('{value}')" for value in MINUTE_TRADE_DATES)})
                AS dates(trade_date)
            ) TO '{source}' (FORMAT PARQUET)
            """
        )
        for trade_date in MINUTE_TRADE_DATES:
            target = gold_stk_mins_qfq_nineturn_path(root, freq, trade_date)
            target.parent.mkdir(parents=True, exist_ok=True)
            connection.execute(
                f"""
                COPY (
                  SELECT '000001.SZ'::VARCHAR AS ts_code,
                    {freq}::INTEGER AS freq,
                    DATE '{trade_date}' AS trade_date,
                    TIMESTAMP '{trade_date} 15:00:00' AS trade_time,
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
        with (
            duckdb.connect(":memory:") as connection,
            self.assertRaisesRegex(ValueError, "at most 10"),
        ):
            batch_gold_stock_daily_qfq_nineturn_readiness(
                connection=connection,
                lake_root=Path("/tmp/not-used"),
                expected_trade_dates=dates,
                registered_trade_days=dates,
            )

    def test_minute_batch_readiness_keeps_all_four_frequency_checks(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            _write_minute_sources_and_targets(connection, root)

            batch = batch_gold_stk_mins_qfq_nineturn_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=MINUTE_TRADE_DATES,
                registered_trade_days=MINUTE_TRADE_DATES,
            )

        self.assertEqual(batch.freq_count, 4)
        self.assertTrue(
            all(
                batch.status_for_trade_date(trade_date).ready
                for trade_date in MINUTE_TRADE_DATES
            )
        )

    def test_minute_source_paths_are_enumerated_once_per_frequency_and_year(
        self,
    ) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            _write_minute_sources_and_targets(connection, root)
            source_path_builder = (
                readiness_module.qfq_nineturn_source_paths_for_partition
            )
            with patch.object(
                readiness_module,
                "qfq_nineturn_source_paths_for_partition",
                wraps=source_path_builder,
            ) as mocked_source_paths:
                batch = batch_gold_stk_mins_qfq_nineturn_readiness(
                    connection=connection,
                    lake_root=root,
                    expected_trade_dates=MINUTE_TRADE_DATES,
                    registered_trade_days=MINUTE_TRADE_DATES,
                )

        self.assertTrue(batch.status_for_trade_date(TRADE_DATE).ready)
        self.assertEqual(mocked_source_paths.call_count, 4)

    def test_minute_missing_source_frequency_fails_closed(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            _write_minute_sources_and_targets(connection, root)
            gold_stk_mins_qfq_path(root, 120, "000001.SZ", 2026).unlink()

            batch = batch_gold_stk_mins_qfq_nineturn_readiness(
                connection=connection,
                lake_root=root,
                expected_trade_dates=MINUTE_TRADE_DATES,
                registered_trade_days=MINUTE_TRADE_DATES,
            )

        status = batch.status_for_trade_date(TRADE_DATE)
        self.assertFalse(status.ready)
        self.assertIn(
            "gold_stk_mins_qfq_nineturn_120m_integrity_check",
            status.failed_check_names,
        )

    def test_source_relations_are_materialized_for_the_bounded_window(self) -> None:
        source = Path(readiness_module.__file__).read_text(encoding="utf-8")

        self.assertIn("CREATE OR REPLACE TEMP TABLE", source)
        self.assertNotIn("CREATE OR REPLACE TEMP VIEW", source)
        self.assertIn("CAST(trade_date AS DATE) IN", source)


if __name__ == "__main__":
    unittest.main()
