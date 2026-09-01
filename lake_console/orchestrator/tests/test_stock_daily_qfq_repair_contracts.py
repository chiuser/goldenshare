import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.asset_guards.stock_daily_qfq_factor_repair import (
    _status_from_metadata,
)
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    silver_adj_factor_path,
    silver_stock_daily_path,
)
from orchestrator.defs.stock_daily_qfq import (
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_AUTO_CODE_LIMIT,
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_METADATA_SAMPLE_LIMIT,
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED,
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED,
    GoldStockDailyQfqFactorRepairPlan,
    GoldStockDailyQfqFactorRepairResult,
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


def _prepare_repair_lake(
    root: Path,
    *,
    current_000001_adj_factor: float = 4.0,
) -> None:
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
            _adj_factor_row(
                "000001.SZ",
                TRADE_DATE,
                current_000001_adj_factor,
            ),
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


def _repair_result_for_codes(
    repair_required_codes: tuple[str, ...],
) -> GoldStockDailyQfqFactorRepairResult:
    repair_required = bool(repair_required_codes)
    return GoldStockDailyQfqFactorRepairResult(
        plan=GoldStockDailyQfqFactorRepairPlan(
            qfq_factor_trade_date=TRADE_DATE,
            previous_trade_date=PREVIOUS_DATE,
            reason=(
                GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED
                if repair_required
                else GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED
            ),
            can_execute_repair=True,
            repair_required=repair_required,
            repair_required_codes=repair_required_codes,
            repair_required_codes_hash=(
                gold_stock_daily_qfq_factor_repair_codes_hash(repair_required_codes)
            ),
        ),
        repair_start_trade_date=PREVIOUS_DATE if repair_required else None,
        repair_end_trade_date=TRADE_DATE,
        selected_partition_count=1 if repair_required else 0,
        rewritten_partition_count=1 if repair_required else 0,
        rewritten_row_count=len(repair_required_codes),
        repaired_code_count=len(repair_required_codes),
        repaired_file_samples=(),
        upstream_batch_id="gold_stock_daily_qfq_update:2026-06-18:abc123",
    )


class StockDailyQfqFactorRepairContractTests(unittest.TestCase):
    def test_repair_metadata_preserves_full_scope_and_bounded_samples(self) -> None:
        for code_count in (0, 1, 20, 21, 500, 501):
            with self.subTest(code_count=code_count):
                codes = tuple(f"{index:06d}.SZ" for index in range(1, code_count + 1))
                metadata = build_gold_stock_daily_qfq_factor_repair_check_metadata(
                    _repair_result_for_codes(codes),
                    producer_run_id="repair-run-id",
                )

                truncated = (
                    code_count > GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_AUTO_CODE_LIMIT
                )
                self.assertEqual(
                    metadata["goldenshare/repair_required_codes"],
                    [] if truncated else list(codes),
                )
                self.assertEqual(
                    metadata["goldenshare/repair_required_code_samples"],
                    list(
                        codes[:GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_METADATA_SAMPLE_LIMIT]
                    ),
                )
                self.assertEqual(
                    metadata["goldenshare/repair_required_codes_truncated"],
                    truncated,
                )
                self.assertEqual(
                    metadata["goldenshare/repair_required_code_count"],
                    code_count,
                )
                self.assertEqual(
                    metadata["goldenshare/repair_required_codes_hash"],
                    gold_stock_daily_qfq_factor_repair_codes_hash(codes),
                )

                status = _status_from_metadata(TRADE_DATE, metadata)
                self.assertEqual(status.ready, not truncated)
                if not truncated:
                    self.assertEqual(status.repair_required_codes, codes)
                    self.assertEqual(
                        status.repair_required_code_samples,
                        codes[
                            :GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_METADATA_SAMPLE_LIMIT
                        ],
                    )

    def test_no_op_metadata_is_a_zero_write_durable_reconciliation(self) -> None:
        metadata = build_gold_stock_daily_qfq_factor_repair_check_metadata(
            _repair_result_for_codes(()),
            producer_run_id="repair-run-id",
        )

        self.assertFalse(metadata["goldenshare/repair_required"])
        self.assertEqual(metadata["goldenshare/selected_partition_count"], 0)
        self.assertEqual(metadata["goldenshare/rewritten_partition_count"], 0)
        self.assertEqual(metadata["goldenshare/rewritten_row_count"], 0)
        self.assertEqual(metadata["goldenshare/repair_required_codes"], [])
        self.assertEqual(metadata["goldenshare/repair_required_code_samples"], [])
        self.assertTrue(_status_from_metadata(TRADE_DATE, metadata).ready)

    def test_execute_no_factor_change_does_not_rewrite_qfq_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_repair_lake(root, current_000001_adj_factor=2.0)
            target_paths = (
                gold_stock_daily_qfq_path(root, PREVIOUS_DATE),
                gold_stock_daily_qfq_path(root, TRADE_DATE),
            )
            before_bytes = tuple(path.read_bytes() for path in target_paths)

            with duckdb.connect(database=":memory:") as connection:
                result = execute_gold_stock_daily_qfq_factor_repair(
                    connection=connection,
                    lake_root=root,
                    qfq_factor_trade_date=TRADE_DATE,
                    expected_trade_dates=(EARLIER_DATE, PREVIOUS_DATE, TRADE_DATE),
                    repair_required_codes_hash=(
                        gold_stock_daily_qfq_factor_repair_codes_hash(())
                    ),
                    upstream_batch_id=(
                        "gold_stock_daily_qfq_update:2026-06-18:no-op"
                    ),
                )

            after_bytes = tuple(path.read_bytes() for path in target_paths)

        self.assertFalse(result.plan.repair_required)
        self.assertEqual(result.selected_partition_count, 0)
        self.assertEqual(result.rewritten_partition_count, 0)
        self.assertEqual(result.rewritten_row_count, 0)
        self.assertEqual(before_bytes, after_bytes)

    def test_repair_status_rejects_inconsistent_code_scope_metadata(self) -> None:
        codes = tuple(f"{index:06d}.SZ" for index in range(1, 22))
        metadata = build_gold_stock_daily_qfq_factor_repair_check_metadata(
            _repair_result_for_codes(codes),
            producer_run_id="repair-run-id",
        )
        inconsistent_values = (
            (
                "unordered_codes",
                "goldenshare/repair_required_codes",
                list(reversed(codes)),
            ),
            (
                "duplicate_codes",
                "goldenshare/repair_required_codes",
                [*codes[:-1], codes[-2]],
            ),
            (
                "noncanonical_codes",
                "goldenshare/repair_required_codes",
                [codes[0].lower(), *codes[1:]],
            ),
            (
                "wrong_count",
                "goldenshare/repair_required_code_count",
                len(codes) - 1,
            ),
            (
                "wrong_hash",
                "goldenshare/repair_required_codes_hash",
                "0" * 64,
            ),
            (
                "wrong_samples",
                "goldenshare/repair_required_code_samples",
                list(codes[1:21]),
            ),
        )
        for label, key, value in inconsistent_values:
            with self.subTest(label=label):
                inconsistent_metadata = dict(metadata)
                inconsistent_metadata[key] = value
                self.assertFalse(
                    _status_from_metadata(
                        TRADE_DATE,
                        inconsistent_metadata,
                    ).ready
                )

        legacy_metadata = dict(metadata)
        legacy_metadata.pop("goldenshare/repair_required_code_samples")
        self.assertFalse(_status_from_metadata(TRADE_DATE, legacy_metadata).ready)

    def test_repair_metadata_rejects_noncanonical_declared_codes(self) -> None:
        with self.assertRaisesRegex(ValueError, "normalized, sorted and unique"):
            build_gold_stock_daily_qfq_factor_repair_check_metadata(
                _repair_result_for_codes(("600000.SH", "000001.SZ")),
                producer_run_id="repair-run-id",
            )

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
