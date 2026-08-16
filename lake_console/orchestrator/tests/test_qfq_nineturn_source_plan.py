import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.paths import (
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_path,
)
from orchestrator.defs.qfq_nineturn import (
    plan_gold_stock_daily_qfq_nineturn_source,
)

TARGET_DATE = "2026-08-07"


def _write_daily_source(connection, root: Path, trade_date: str, ts_code: str) -> None:
    path = gold_stock_daily_qfq_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT '{ts_code}'::VARCHAR AS ts_code,
            DATE '{trade_date}' AS trade_date,
            10.0::DOUBLE AS close
        ) TO '{path}' (FORMAT PARQUET)
        """
    )


def _write_previous_seed(connection, root: Path, trade_date: str, ts_code: str) -> None:
    path = gold_stock_daily_qfq_nineturn_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT '{ts_code}'::VARCHAR AS ts_code,
            DATE '{trade_date}' AS trade_date,
            1::INTEGER AS up_count,
            0::INTEGER AS down_count,
            NULL::VARCHAR AS nine_up_turn,
            NULL::VARCHAR AS nine_down_turn
        ) TO '{path}' (FORMAT PARQUET)
        """
    )


class QfqNineturnSourcePlanTests(unittest.TestCase):
    def test_daily_plan_uses_seeded_bounded_context_without_fallback(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            dates = tuple(
                (date(2026, 8, 2) + timedelta(days=offset)).isoformat()
                for offset in range(6)
            )
            for trade_date in dates:
                _write_daily_source(connection, root, trade_date, "000001.SZ")
            _write_previous_seed(connection, root, dates[-2], "000001.SZ")

            plan = plan_gold_stock_daily_qfq_nineturn_source(
                connection,
                lake_root=root,
                partition_key=TARGET_DATE,
                previous_trade_date=dates[-2],
            )

        self.assertEqual(plan.source_row_count, 1)
        self.assertEqual(plan.fallback_codes, ())
        self.assertEqual(plan.fallback_source_paths, ())
        self.assertEqual(plan.previous_partition_path.name, "part-000.parquet")

    def test_daily_plan_selects_only_old_code_without_seed_for_fallback(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:") as connection,
        ):
            root = Path(directory)
            dates = tuple(
                (date(2026, 8, 2) + timedelta(days=offset)).isoformat()
                for offset in range(6)
            )
            for trade_date in dates:
                _write_daily_source(connection, root, trade_date, "000001.SZ")
            _write_previous_seed(connection, root, dates[-2], "000002.SZ")

            plan = plan_gold_stock_daily_qfq_nineturn_source(
                connection,
                lake_root=root,
                partition_key=TARGET_DATE,
                previous_trade_date=dates[-2],
            )

        self.assertEqual(plan.fallback_codes, ("000001.SZ",))
        self.assertEqual(len(plan.fallback_source_paths), 6)


if __name__ == "__main__":
    unittest.main()
