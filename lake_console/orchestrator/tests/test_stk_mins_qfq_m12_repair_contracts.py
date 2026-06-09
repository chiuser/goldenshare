import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import dagster as dg

from orchestrator.defs.jobs.gold_stk_mins_qfq_macd_kdj_repair import (
    gold_stk_mins_qfq_macd_kdj_repair_job,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_macd_kdj import (
    GoldStkMinsQfqMacdKdjDailyRepairGateStatus,
)
from orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair import (
    MACD_KDJ_REPAIR_EMPTY_STOCK_CODES_ERROR,
    MACD_KDJ_REPAIR_MISSING_SCOPE_ERROR,
    gold_stk_mins_qfq_macd_kdj_repair_op,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.stk_mins_qfq import GOLD_STK_MINS_QFQ_WRITER_POOL
from orchestrator.defs.stk_mins_qfq import (
    gold_stk_mins_qfq_factor_repair_codes_hash,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
    GoldStkMinsQfqMacdKdjStateWriteResult,
    GoldStkMinsQfqMacdKdjWriteResult,
)


START_DATE = "2026-06-04"
END_DATE = "2026-06-05"
QFQ_FACTOR_REPAIR_DATE = "2026-06-08"


def _indicator_result(freq: int) -> GoldStkMinsQfqMacdKdjWriteResult:
    return GoldStkMinsQfqMacdKdjWriteResult(
        path=Path(f"/private/tmp/m12-repair-{freq}.parquet"),
        ts_code="600000.SH",
        year="2026",
        row_count=20,
        replacement_row_count=10,
    )


def _state_result(freq: int) -> GoldStkMinsQfqMacdKdjStateWriteResult:
    return GoldStkMinsQfqMacdKdjStateWriteResult(
        path=Path(f"/private/tmp/m12-repair-state-{freq}.parquet"),
        freq=freq,
        trade_date=END_DATE,
        row_count=1,
    )


def _ready_qfq_factor_repair_status(
    *,
    stock_codes: tuple[str, ...] = ("600000.SH",),
) -> GoldStkMinsQfqMacdKdjDailyRepairGateStatus:
    return GoldStkMinsQfqMacdKdjDailyRepairGateStatus(
        ready=True,
        trade_date=QFQ_FACTOR_REPAIR_DATE,
        reason=(
            "qfq factor repair rewrote history; "
            "MACD/KDJ repair completion is required."
        ),
        requires_macd_kdj_repair=True,
        qfq_factor_repair_event_storage_ids=(101, 102),
        repair_start_trade_date=START_DATE,
        repair_end_trade_date=QFQ_FACTOR_REPAIR_DATE,
        selected_partition_count=2,
        repair_required_code_count=len(stock_codes),
        repair_required_codes=stock_codes,
        repair_required_codes_hash=gold_stk_mins_qfq_factor_repair_codes_hash(
            stock_codes
        ),
        repair_required_codes_truncated=False,
    )


class StkMinsQfqM12RepairContractTests(unittest.TestCase):
    def test_repair_op_uses_qfq_writer_pool(self) -> None:
        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_repair_op.pool,
            GOLD_STK_MINS_QFQ_WRITER_POOL,
        )

    def test_repair_op_requires_explicit_or_qfq_factor_repair_scope(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch(
                "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                "write_gold_stk_mins_qfq_macd_kdj_rows",
            ) as mocked_write_rows:
                result = gold_stk_mins_qfq_macd_kdj_repair_job.execute_in_process(
                    run_config={
                        "ops": {
                            "gold_stk_mins_qfq_macd_kdj_repair_op": {
                                "config": {}
                            }
                        }
                    },
                    raise_on_error=False,
                    resources={
                        "lake_root": LakeRootResource(root_path=temp_dir),
                    },
                )

        self.assertFalse(result.success)
        self.assertIn(
            MACD_KDJ_REPAIR_MISSING_SCOPE_ERROR,
            str(result.get_step_failure_events()[0].event_specific_data.error),
        )
        mocked_write_rows.assert_not_called()

    def test_repair_op_can_derive_scope_from_qfq_factor_repair_trade_date(self) -> None:
        with TemporaryDirectory() as temp_dir:
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                [START_DATE, END_DATE],
            )

            captured_write_calls: list[dict[str, object]] = []

            def fake_source_paths(lake_root, *, freq, trade_dates):
                return (Path(temp_dir) / f"source-{freq}.parquet",)

            def fake_write_rows(
                *,
                lake_root,
                freq,
                source_qfq_paths,
                target_trade_dates,
                previous_state_paths=(),
                stock_codes=(),
                fail_if_target_exists=False,
                allow_empty_replacement=False,
            ):
                captured_write_calls.append(
                    {
                        "freq": freq,
                        "target_trade_dates": target_trade_dates,
                        "stock_codes": stock_codes,
                    }
                )
                return ((_indicator_result(freq),), (_state_result(freq),), False)

            with (
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "gold_stk_mins_qfq_macd_kdj_qfq_factor_repair_status",
                    return_value=_ready_qfq_factor_repair_status(),
                ),
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "discover_gold_stk_mins_qfq_source_year_paths",
                    side_effect=fake_source_paths,
                ),
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "discover_latest_macd_kdj_state_path_before_trade_date",
                    return_value=Path(temp_dir) / "previous-state.parquet",
                ),
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "write_gold_stk_mins_qfq_macd_kdj_rows",
                    side_effect=fake_write_rows,
                ),
            ):
                result = gold_stk_mins_qfq_macd_kdj_repair_job.execute_in_process(
                    run_config={
                        "ops": {
                            "gold_stk_mins_qfq_macd_kdj_repair_op": {
                                "config": {
                                    "qfq_factor_repair_trade_date": (
                                        QFQ_FACTOR_REPAIR_DATE
                                    ),
                                    "stock_codes": [],
                                }
                            }
                        }
                    },
                    instance=instance,
                    resources={
                        "lake_root": LakeRootResource(root_path=temp_dir),
                    },
                )
            records = instance.get_event_records(
                dg.EventRecordsFilter(
                    event_type=dg.DagsterEventType.ASSET_CHECK_EVALUATION,
                ),
                limit=20,
            )

        self.assertTrue(result.success)
        self.assertEqual(len(captured_write_calls), 7)
        for write_call in captured_write_calls:
            self.assertEqual(write_call["target_trade_dates"], (START_DATE, END_DATE))
            self.assertEqual(write_call["stock_codes"], ("600000.SH",))
        completion_records = [
            record
            for record in records
            if (
                record.event_log_entry.dagster_event.event_specific_data.check_name
                == GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME
            )
        ]
        self.assertEqual(len(completion_records), 14)
        first_evaluation = completion_records[
            0
        ].event_log_entry.dagster_event.event_specific_data
        self.assertEqual(
            first_evaluation.metadata[
                "goldenshare/qfq_factor_repair_trade_date"
            ].text,
            QFQ_FACTOR_REPAIR_DATE,
        )
        self.assertEqual(
            first_evaluation.metadata["goldenshare/repair_required_codes_hash"].text,
            gold_stk_mins_qfq_factor_repair_codes_hash(["600000.SH"]),
        )
        self.assertEqual(
            first_evaluation.metadata[
                "goldenshare/source_qfq_factor_repair_event_storage_ids"
            ].value,
            [101, 102],
        )

    def test_repair_op_rejects_stock_codes_that_conflict_with_qfq_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "gold_stk_mins_qfq_macd_kdj_qfq_factor_repair_status",
                    return_value=_ready_qfq_factor_repair_status(),
                ),
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "write_gold_stk_mins_qfq_macd_kdj_rows",
                ) as mocked_write_rows,
            ):
                result = gold_stk_mins_qfq_macd_kdj_repair_job.execute_in_process(
                    run_config={
                        "ops": {
                            "gold_stk_mins_qfq_macd_kdj_repair_op": {
                                "config": {
                                    "qfq_factor_repair_trade_date": (
                                        QFQ_FACTOR_REPAIR_DATE
                                    ),
                                    "stock_codes": ["000001.SZ"],
                                }
                            }
                        }
                    },
                    raise_on_error=False,
                    resources={
                        "lake_root": LakeRootResource(root_path=temp_dir),
                    },
                )

        self.assertFalse(result.success)
        self.assertIn(
            "MACD/KDJ repair stock_codes do not match qfq factor repair metadata",
            str(result.get_step_failure_events()[0].event_specific_data.error),
        )
        mocked_write_rows.assert_not_called()

    def test_repair_op_rejects_empty_stock_codes_before_writing(self) -> None:
        for stock_codes in ([], ["", "   "]):
            with self.subTest(stock_codes=stock_codes):
                with TemporaryDirectory() as temp_dir:
                    with patch(
                        "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                        "write_gold_stk_mins_qfq_macd_kdj_rows",
                    ) as mocked_write_rows:
                        result = gold_stk_mins_qfq_macd_kdj_repair_job.execute_in_process(
                            run_config={
                                "ops": {
                                    "gold_stk_mins_qfq_macd_kdj_repair_op": {
                                        "config": {
                                            "start_trade_date": START_DATE,
                                            "stock_codes": stock_codes,
                                        }
                                    }
                                }
                            },
                            raise_on_error=False,
                            resources={
                                "lake_root": LakeRootResource(root_path=temp_dir),
                            },
                        )

                self.assertFalse(result.success)
                self.assertIn(
                    MACD_KDJ_REPAIR_EMPTY_STOCK_CODES_ERROR,
                    str(result.get_step_failure_events()[0].event_specific_data.error),
                )
                mocked_write_rows.assert_not_called()

    def test_successful_repair_emits_fourteen_completion_check_events(self) -> None:
        with TemporaryDirectory() as temp_dir:
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                [START_DATE, END_DATE],
            )

            def fake_source_paths(lake_root, *, freq, trade_dates):
                return (Path(temp_dir) / f"source-{freq}.parquet",)

            def fake_write_rows(
                *,
                lake_root,
                freq,
                source_qfq_paths,
                target_trade_dates,
                previous_state_paths=(),
                stock_codes=(),
                fail_if_target_exists=False,
                allow_empty_replacement=False,
            ):
                return ((_indicator_result(freq),), (_state_result(freq),), False)

            with (
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "discover_gold_stk_mins_qfq_source_year_paths",
                    side_effect=fake_source_paths,
                ),
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "discover_latest_macd_kdj_state_path_before_trade_date",
                    return_value=Path(temp_dir) / "previous-state.parquet",
                ),
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "write_gold_stk_mins_qfq_macd_kdj_rows",
                    side_effect=fake_write_rows,
                ),
            ):
                result = gold_stk_mins_qfq_macd_kdj_repair_job.execute_in_process(
                    run_config={
                        "ops": {
                            "gold_stk_mins_qfq_macd_kdj_repair_op": {
                                "config": {
                                    "start_trade_date": START_DATE,
                                    "stock_codes": ["600000.SH"],
                                    "reason": "qfq_factor_repair",
                                    "repair_required_codes_hash": (
                                        gold_stk_mins_qfq_factor_repair_codes_hash(
                                            ["600000.SH"]
                                        )
                                    ),
                                    "source_qfq_factor_repair_event_storage_ids": [
                                        101,
                                        102,
                                    ],
                                }
                            }
                        }
                    },
                    instance=instance,
                    resources={
                        "lake_root": LakeRootResource(root_path=temp_dir),
                    },
                )
            records = instance.get_event_records(
                dg.EventRecordsFilter(
                    event_type=dg.DagsterEventType.ASSET_CHECK_EVALUATION,
                ),
                limit=20,
            )

        self.assertTrue(result.success)
        completion_records = [
            record
            for record in records
            if (
                record.event_log_entry.dagster_event.event_specific_data.check_name
                == GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME
            )
        ]
        self.assertEqual(len(completion_records), 14)
        for record in completion_records:
            evaluation = record.event_log_entry.dagster_event.event_specific_data
            self.assertTrue(evaluation.passed)
            self.assertTrue(evaluation.blocking)
            self.assertEqual(evaluation.partition, START_DATE)
            self.assertEqual(
                evaluation.metadata["goldenshare/covered_start_trade_date"].text,
                START_DATE,
            )
            self.assertEqual(
                evaluation.metadata["goldenshare/covered_end_trade_date"].text,
                END_DATE,
            )
            self.assertEqual(
                evaluation.metadata["goldenshare/stock_code_scope"].text,
                "explicit",
            )
            self.assertEqual(
                evaluation.metadata["goldenshare/stock_code_count"].value,
                1,
            )
            self.assertEqual(
                evaluation.metadata["goldenshare/repair_required_code_count"].value,
                1,
            )
            self.assertEqual(
                evaluation.metadata["goldenshare/repair_required_codes_hash"].text,
                gold_stk_mins_qfq_factor_repair_codes_hash(["600000.SH"]),
            )
            self.assertEqual(
                evaluation.metadata[
                    "goldenshare/source_qfq_factor_repair_event_storage_ids"
                ].value,
                [101, 102],
            )
            self.assertEqual(
                evaluation.metadata["goldenshare/indicator_file_count"].value,
                7,
            )
            self.assertEqual(
                evaluation.metadata["goldenshare/state_file_count"].value,
                7,
            )


if __name__ == "__main__":
    unittest.main()
