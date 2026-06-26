import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    silver_adj_factor_path,
    silver_stock_daily_path,
)
from orchestrator.defs.stock_daily_qfq import (
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED,
    build_gold_stock_daily_qfq_factor_repair_check_metadata,
    build_gold_stock_daily_qfq_factor_repair_plan,
    execute_gold_stock_daily_qfq_factor_repair,
    gold_stock_daily_qfq_factor_repair_codes_hash,
    write_gold_stock_daily_qfq_partition,
)
from tests.test_stock_daily_qfq_contracts import (
    EARLIER_DATE,
    PREVIOUS_DATE,
    TRADE_DATE,
    _adj_factor_row,
    _fetch_output_rows,
    _stock_daily_row,
    _write_adj_factor,
    _write_calendar,
    _write_stock_daily,
)


def _prepare_repair_lake(root: Path) -> None:
    _write_calendar(root)
    _write_stock_daily(
        root,
        EARLIER_DATE,
        [
            _stock_daily_row("000001.SZ", EARLIER_DATE, close=8.0),
            _stock_daily_row("600000.SH", EARLIER_DATE, close=16.0),
        ],
    )
    _write_stock_daily(
        root,
        PREVIOUS_DATE,
        [
            _stock_daily_row("000001.SZ", PREVIOUS_DATE, close=10.0),
            _stock_daily_row("600000.SH", PREVIOUS_DATE, close=20.0),
        ],
    )
    _write_stock_daily(
        root,
        TRADE_DATE,
        [
            _stock_daily_row("000001.SZ", TRADE_DATE, close=12.0),
            _stock_daily_row("600000.SH", TRADE_DATE, close=22.0),
        ],
    )
    _write_adj_factor(
        root,
        EARLIER_DATE,
        [
            _adj_factor_row("000001.SZ", EARLIER_DATE, 2.0),
            _adj_factor_row("600000.SH", EARLIER_DATE, 5.0),
        ],
    )
    _write_adj_factor(
        root,
        PREVIOUS_DATE,
        [
            _adj_factor_row("000001.SZ", PREVIOUS_DATE, 2.0),
            _adj_factor_row("600000.SH", PREVIOUS_DATE, 5.0),
        ],
    )
    _write_adj_factor(
        root,
        TRADE_DATE,
        [
            _adj_factor_row("000001.SZ", TRADE_DATE, 4.0),
            _adj_factor_row("600000.SH", TRADE_DATE, 5.0),
        ],
    )
    with duckdb.connect(database=":memory:") as connection:
        write_gold_stock_daily_qfq_partition(
            connection=connection,
            lake_root=root,
            trade_date=PREVIOUS_DATE,
            previous_lookup_trade_dates=(EARLIER_DATE,),
        )
        write_gold_stock_daily_qfq_partition(
            connection=connection,
            lake_root=root,
            trade_date=TRADE_DATE,
            previous_lookup_trade_dates=(EARLIER_DATE, PREVIOUS_DATE),
        )


class StockDailyQfqFactorRepairContractTests(unittest.TestCase):
    def test_factor_repair_hash_is_stable_and_order_insensitive(self) -> None:
        self.assertEqual(
            gold_stock_daily_qfq_factor_repair_codes_hash(
                ["600000.SH", "000001.SZ", "000001.SZ"]
            ),
            gold_stock_daily_qfq_factor_repair_codes_hash(
                ["000001.SZ", "600000.SH"]
            ),
        )
        self.assertEqual(
            len(gold_stock_daily_qfq_factor_repair_codes_hash(["000001.SZ"])),
            64,
        )

    def test_factor_changed_plan_uses_adj_factor_diff_only(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_repair_lake(root)

            with duckdb.connect(database=":memory:") as connection:
                plan = build_gold_stock_daily_qfq_factor_repair_plan(
                    connection=connection,
                    current_adj_factor_path=silver_adj_factor_path(root, TRADE_DATE),
                    previous_adj_factor_path=silver_adj_factor_path(root, PREVIOUS_DATE),
                    qfq_factor_trade_date=TRADE_DATE,
                    previous_trade_date=PREVIOUS_DATE,
                )

        self.assertTrue(plan.repair_required)
        self.assertEqual(plan.reason, GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED)
        self.assertEqual(plan.repair_required_codes, ("000001.SZ",))

    def test_execute_factor_repair_rewrites_only_affected_codes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_repair_lake(root)
            before_rows = _fetch_output_rows(
                gold_stock_daily_qfq_path(root, PREVIOUS_DATE)
            )
            affected_hash = gold_stock_daily_qfq_factor_repair_codes_hash(
                ("000001.SZ",)
            )

            with duckdb.connect(database=":memory:") as connection:
                result = execute_gold_stock_daily_qfq_factor_repair(
                    connection=connection,
                    lake_root=root,
                    qfq_factor_trade_date=TRADE_DATE,
                    expected_trade_dates=(EARLIER_DATE, PREVIOUS_DATE, TRADE_DATE),
                    repair_required_codes_hash=affected_hash,
                    upstream_batch_id="gold_stock_daily_qfq_update:2026-06-18:abc123",
                )

            after_rows = _fetch_output_rows(
                gold_stock_daily_qfq_path(root, PREVIOUS_DATE)
            )

        before_by_code = {row["ts_code"]: row for row in before_rows}
        after_by_code = {row["ts_code"]: row for row in after_rows}
        self.assertEqual(result.repair_start_trade_date, PREVIOUS_DATE)
        self.assertEqual(result.repair_end_trade_date, TRADE_DATE)
        self.assertEqual(result.selected_partition_count, 2)
        self.assertEqual(result.rewritten_partition_count, 2)
        self.assertEqual(result.plan.repair_required_codes, ("000001.SZ",))
        self.assertAlmostEqual(before_by_code["000001.SZ"]["close"], 10.0)
        self.assertAlmostEqual(after_by_code["000001.SZ"]["close"], 5.0)
        self.assertEqual(before_by_code["600000.SH"], after_by_code["600000.SH"])

    def test_factor_repair_rejects_hash_mismatch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_repair_lake(root)

            with duckdb.connect(database=":memory:") as connection:
                with self.assertRaisesRegex(
                    ValueError,
                    "repair_required_codes_hash does not match",
                ):
                    execute_gold_stock_daily_qfq_factor_repair(
                        connection=connection,
                        lake_root=root,
                        qfq_factor_trade_date=TRADE_DATE,
                        expected_trade_dates=(EARLIER_DATE, PREVIOUS_DATE, TRADE_DATE),
                        repair_required_codes_hash="0" * 64,
                        upstream_batch_id="gold_stock_daily_qfq_update:2026-06-18:abc123",
                    )

    def test_repair_check_metadata_records_hash_and_no_stock_codes_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_repair_lake(root)
            affected_hash = gold_stock_daily_qfq_factor_repair_codes_hash(
                ("000001.SZ",)
            )

            with duckdb.connect(database=":memory:") as connection:
                result = execute_gold_stock_daily_qfq_factor_repair(
                    connection=connection,
                    lake_root=root,
                    qfq_factor_trade_date=TRADE_DATE,
                    expected_trade_dates=(EARLIER_DATE, PREVIOUS_DATE, TRADE_DATE),
                    repair_required_codes_hash=affected_hash,
                    upstream_batch_id="gold_stock_daily_qfq_update:2026-06-18:abc123",
                )
            metadata = build_gold_stock_daily_qfq_factor_repair_check_metadata(
                result,
                producer_run_id="repair-run-id",
            )

        self.assertEqual(metadata["goldenshare/repair_required_codes_hash"], affected_hash)
        self.assertEqual(metadata["goldenshare/repair_required_codes"], ["000001.SZ"])
        self.assertEqual(metadata["goldenshare/upstream_batch_id"], result.upstream_batch_id)


if __name__ == "__main__":
    unittest.main()
