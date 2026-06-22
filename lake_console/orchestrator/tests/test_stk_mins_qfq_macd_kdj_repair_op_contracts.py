import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import dagster as dg
import duckdb

from orchestrator.defs.jobs.gold_stk_mins_qfq_macd_kdj_repair import (
    gold_stk_mins_qfq_macd_kdj_repair_job,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
)
from orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair import (
    MACD_KDJ_REPAIR_EMPTY_STOCK_CODES_ERROR,
    MACD_KDJ_REPAIR_MANUAL_UNSUPPORTED_ERROR,
    gold_stk_mins_qfq_macd_kdj_repair_op,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_FREQS
from orchestrator.defs.stk_mins_qfq import GOLD_STK_MINS_QFQ_WRITER_POOL
from orchestrator.defs.stk_mins_qfq import (
    gold_stk_mins_qfq_factor_repair_codes_hash,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
    GoldStkMinsQfqMacdKdjStateWriteResult,
    GoldStkMinsQfqMacdKdjWriteResult,
    gold_stk_mins_qfq_macd_kdj_state_path,
)


PREVIOUS_STATE_DATE = "2026-06-03"
START_DATE = "2026-06-04"
QFQ_FACTOR_REPAIR_DATE = "2026-06-08"
END_DATE = QFQ_FACTOR_REPAIR_DATE
REPAIR_CODES = ("600000.SH",)
REPAIR_CODES_HASH = gold_stk_mins_qfq_factor_repair_codes_hash(REPAIR_CODES)
PRODUCER_RUN_ID = "qfq-factor-repair-run-1"
UPSTREAM_BATCH_ID = f"qfq_factor_repair:{QFQ_FACTOR_REPAIR_DATE}:7f3a9c2d8b41"
DEFAULT_EXPECTED_TRADE_DATES = (
    PREVIOUS_STATE_DATE,
    START_DATE,
    "2026-06-05",
    END_DATE,
)
DEFAULT_TARGET_TRADE_DATES = (START_DATE, "2026-06-05", END_DATE)
FIRST_EXPECTED_TRADE_DATE = "2014-01-02"


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
    trade_date: str = QFQ_FACTOR_REPAIR_DATE,
    repair_start_trade_date: str = START_DATE,
    repair_end_trade_date: str = END_DATE,
    stock_codes: tuple[str, ...] = REPAIR_CODES,
    upstream_batch_id: str | None = UPSTREAM_BATCH_ID,
) -> GoldStkMinsQfqFactorRepairStatus:
    return GoldStkMinsQfqFactorRepairStatus(
        ready=True,
        trade_date=trade_date,
        reason=(
            "qfq factor repair rewrote history; "
            "MACD/KDJ repair completion is required."
        ),
        repair_required=True,
        producer_run_id=PRODUCER_RUN_ID,
        upstream_batch_id=upstream_batch_id,
        qfq_factor_repair_event_storage_ids=(101, 102),
        repair_start_trade_date=repair_start_trade_date,
        repair_end_trade_date=repair_end_trade_date,
        selected_partition_count=2,
        repair_required_code_count=len(stock_codes),
        repair_required_codes=stock_codes,
        repair_required_codes_hash=gold_stk_mins_qfq_factor_repair_codes_hash(
            stock_codes
        ),
        repair_required_codes_truncated=False,
        rewritten_file_count=1,
        rewritten_row_count=10,
    )


def _full_replay_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "qfq_factor_repair_trade_date": QFQ_FACTOR_REPAIR_DATE,
        "start_trade_date": START_DATE,
        "stock_codes": list(REPAIR_CODES),
        "reason": f"qfq_factor_repair:{QFQ_FACTOR_REPAIR_DATE}",
        "repair_required_codes_hash": REPAIR_CODES_HASH,
        "upstream_batch_id": UPSTREAM_BATCH_ID,
    }
    config.update(overrides)
    return config


def _resources(temp_dir: str) -> dict[str, object]:
    return {
        "lake_root": LakeRootResource(root_path=temp_dir),
        "duckdb": DuckDBResource(),
    }


def _write_calendar_rows(lake_root: Path, trade_dates: tuple[str, ...]) -> None:
    calendar_path = silver_trade_calendar_path(lake_root)
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        f"(DATE '{trade_date}', 'SSE', true)" for trade_date in trade_dates
    )
    query = f"""
        SELECT trade_date, exchange, is_open
        FROM (VALUES {values}) AS rows(trade_date, exchange, is_open)
        ORDER BY trade_date
    """
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(copy_query_to_parquet(query, calendar_path))


def _touch_previous_state_files(
    lake_root: Path,
    *,
    trade_date: str = PREVIOUS_STATE_DATE,
    freqs: tuple[int, ...] = STK_MINS_QFQ_FREQS,
) -> None:
    for freq in freqs:
        state_path = gold_stk_mins_qfq_macd_kdj_state_path(
            lake_root,
            freq,
            trade_date,
        )
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("previous-state", encoding="utf-8")


class StkMinsQfqMacdKdjRepairOpContractTests(unittest.TestCase):
    def test_repair_op_uses_qfq_writer_pool(self) -> None:
        self.assertEqual(
            gold_stk_mins_qfq_macd_kdj_repair_op.pool,
            GOLD_STK_MINS_QFQ_WRITER_POOL,
        )

    def test_repair_op_rejects_missing_qfq_factor_repair_trade_date(self) -> None:
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
                    resources=_resources(temp_dir),
                )

        self.assertFalse(result.success)
        self.assertIn(
            MACD_KDJ_REPAIR_MANUAL_UNSUPPORTED_ERROR,
            str(result.get_step_failure_events()[0].event_specific_data.error),
        )
        mocked_write_rows.assert_not_called()

    def test_repair_op_replays_qfq_factor_repair_batch_when_config_matches_metadata(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_calendar_rows(lake_root, DEFAULT_EXPECTED_TRADE_DATES)
            _touch_previous_state_files(lake_root)
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                list(DEFAULT_TARGET_TRADE_DATES),
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
                        "previous_state_paths": previous_state_paths,
                        "stock_codes": stock_codes,
                    }
                )
                return ((_indicator_result(freq),), (_state_result(freq),), False)

            with (
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "gold_stk_mins_qfq_factor_repair_status",
                    return_value=_ready_qfq_factor_repair_status(),
                ),
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "discover_gold_stk_mins_qfq_source_year_paths",
                    side_effect=fake_source_paths,
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
                                "config": _full_replay_config(),
                            }
                        }
                    },
                    instance=instance,
                    resources=_resources(temp_dir),
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
            expected_state_path = gold_stk_mins_qfq_macd_kdj_state_path(
                Path(temp_dir),
                write_call["freq"],
                PREVIOUS_STATE_DATE,
            )
            self.assertEqual(
                write_call["target_trade_dates"],
                DEFAULT_TARGET_TRADE_DATES,
            )
            self.assertEqual(write_call["previous_state_paths"], (expected_state_path,))
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
            REPAIR_CODES_HASH,
        )
        self.assertEqual(
            first_evaluation.metadata["goldenshare/source_upstream_batch_id"].text,
            UPSTREAM_BATCH_ID,
        )
        self.assertNotIn(
            "goldenshare/source_qfq_factor_repair_event_storage_ids",
            first_evaluation.metadata,
        )

    def test_repair_op_allows_first_expected_trade_date_without_previous_state(
        self,
    ) -> None:
        repair_end_trade_date = "2014-01-03"
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_calendar_rows(
                lake_root,
                (FIRST_EXPECTED_TRADE_DATE, repair_end_trade_date),
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                [FIRST_EXPECTED_TRADE_DATE, repair_end_trade_date],
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
                        "previous_state_paths": previous_state_paths,
                    }
                )
                return ((_indicator_result(freq),), (_state_result(freq),), True)

            with (
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "gold_stk_mins_qfq_factor_repair_status",
                    return_value=_ready_qfq_factor_repair_status(
                        trade_date=repair_end_trade_date,
                        repair_start_trade_date=FIRST_EXPECTED_TRADE_DATE,
                        repair_end_trade_date=repair_end_trade_date,
                    ),
                ),
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "discover_gold_stk_mins_qfq_source_year_paths",
                    side_effect=fake_source_paths,
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
                                "config": _full_replay_config(
                                    qfq_factor_repair_trade_date=repair_end_trade_date,
                                    start_trade_date=FIRST_EXPECTED_TRADE_DATE,
                                    reason=f"qfq_factor_repair:{repair_end_trade_date}",
                                )
                            }
                        }
                    },
                    instance=instance,
                    resources=_resources(temp_dir),
                )

        self.assertTrue(result.success)
        self.assertEqual(len(captured_write_calls), len(STK_MINS_QFQ_FREQS))
        for write_call in captured_write_calls:
            self.assertEqual(
                write_call["target_trade_dates"],
                (FIRST_EXPECTED_TRADE_DATE, repair_end_trade_date),
            )
            self.assertEqual(write_call["previous_state_paths"], ())

    def test_repair_op_fails_before_writing_when_expected_range_has_gap(
        self,
    ) -> None:
        qfq_repair_trade_date = "2026-06-16"
        repair_start_trade_date = "2026-06-13"
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_calendar_rows(
                lake_root,
                ("2026-06-13", "2026-06-15", "2026-06-16"),
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                ["2026-06-13", "2026-06-16"],
            )
            with (
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "gold_stk_mins_qfq_factor_repair_status",
                    return_value=_ready_qfq_factor_repair_status(
                        trade_date=qfq_repair_trade_date,
                        repair_start_trade_date=repair_start_trade_date,
                        repair_end_trade_date=qfq_repair_trade_date,
                    ),
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
                                "config": _full_replay_config(
                                    qfq_factor_repair_trade_date=qfq_repair_trade_date,
                                    start_trade_date=repair_start_trade_date,
                                )
                            }
                        }
                    },
                    instance=instance,
                    raise_on_error=False,
                    resources=_resources(temp_dir),
                )
            records = instance.get_event_records(
                dg.EventRecordsFilter(
                    event_type=dg.DagsterEventType.ASSET_CHECK_EVALUATION,
                ),
                limit=20,
            )

        self.assertFalse(result.success)
        self.assertIn(
            "first_missing_registered_date=2026-06-15",
            str(result.get_step_failure_events()[0].event_specific_data.error),
        )
        mocked_write_rows.assert_not_called()
        self.assertEqual(records, [])

    def test_repair_op_rejects_scope_outside_expected_calendar_before_writing(
        self,
    ) -> None:
        cases = (
            (
                ("2026-06-15", "2026-06-16"),
                "2026-06-13",
                "2026-06-16",
                "start_trade_date is not an expected stock minutes trade date",
            ),
            (
                ("2026-06-13", "2026-06-15"),
                "2026-06-13",
                "2026-06-16",
                "end_trade_date is not an expected stock minutes trade date",
            ),
        )
        for expected_dates, repair_start, repair_end, expected_message in cases:
            with self.subTest(
                expected_dates=expected_dates,
                repair_start=repair_start,
                repair_end=repair_end,
            ):
                with TemporaryDirectory() as temp_dir:
                    lake_root = Path(temp_dir)
                    _write_calendar_rows(lake_root, expected_dates)
                    instance = dg.DagsterInstance.ephemeral()
                    instance.add_dynamic_partitions(
                        cn_a_stock_mins_silver_trade_days.name,
                        list(expected_dates),
                    )
                    with (
                        patch(
                            "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                            "gold_stk_mins_qfq_factor_repair_status",
                            return_value=_ready_qfq_factor_repair_status(
                                trade_date=repair_end,
                                repair_start_trade_date=repair_start,
                                repair_end_trade_date=repair_end,
                            ),
                        ),
                        patch(
                            "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                            "write_gold_stk_mins_qfq_macd_kdj_rows",
                        ) as mocked_write_rows,
                    ):
                        result = (
                            gold_stk_mins_qfq_macd_kdj_repair_job.execute_in_process(
                                run_config={
                                    "ops": {
                                        "gold_stk_mins_qfq_macd_kdj_repair_op": {
                                            "config": _full_replay_config(
                                                qfq_factor_repair_trade_date=repair_end,
                                                start_trade_date=repair_start,
                                            )
                                        }
                                    }
                                },
                                instance=instance,
                                raise_on_error=False,
                                resources=_resources(temp_dir),
                            )
                        )

                self.assertFalse(result.success)
                self.assertIn(
                    expected_message,
                    str(result.get_step_failure_events()[0].event_specific_data.error),
                )
                mocked_write_rows.assert_not_called()

    def test_repair_op_requires_exact_previous_expected_state_before_writing(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_calendar_rows(
                lake_root,
                ("2026-06-13", "2026-06-15", "2026-06-16"),
            )
            _touch_previous_state_files(lake_root, trade_date="2026-06-13")
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                ["2026-06-16"],
            )

            def fake_source_paths(lake_root, *, freq, trade_dates):
                return (Path(temp_dir) / f"source-{freq}.parquet",)

            with (
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "gold_stk_mins_qfq_factor_repair_status",
                    return_value=_ready_qfq_factor_repair_status(
                        trade_date="2026-06-16",
                        repair_start_trade_date="2026-06-16",
                        repair_end_trade_date="2026-06-16",
                    ),
                ),
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "discover_gold_stk_mins_qfq_source_year_paths",
                    side_effect=fake_source_paths,
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
                                "config": _full_replay_config(
                                    qfq_factor_repair_trade_date="2026-06-16",
                                    start_trade_date="2026-06-16",
                                )
                            }
                        }
                    },
                    instance=instance,
                    raise_on_error=False,
                    resources=_resources(temp_dir),
                )

        self.assertFalse(result.success)
        self.assertIn(
            "previous expected state is missing",
            str(result.get_step_failure_events()[0].event_specific_data.error),
        )
        mocked_write_rows.assert_not_called()

    def test_repair_op_preflights_all_freqs_before_first_write(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_calendar_rows(lake_root, DEFAULT_EXPECTED_TRADE_DATES)
            _touch_previous_state_files(lake_root)
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                list(DEFAULT_TARGET_TRADE_DATES),
            )

            def fake_source_paths(lake_root, *, freq, trade_dates):
                if freq == 5:
                    return ()
                return (Path(temp_dir) / f"source-{freq}.parquet",)

            with (
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "gold_stk_mins_qfq_factor_repair_status",
                    return_value=_ready_qfq_factor_repair_status(),
                ),
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "discover_gold_stk_mins_qfq_source_year_paths",
                    side_effect=fake_source_paths,
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
                                "config": _full_replay_config(),
                            }
                        }
                    },
                    instance=instance,
                    raise_on_error=False,
                    resources=_resources(temp_dir),
                )

        self.assertFalse(result.success)
        self.assertIn(
            "Missing source gold qfq files for MACD/KDJ repair",
            str(result.get_step_failure_events()[0].event_specific_data.error),
        )
        mocked_write_rows.assert_not_called()

    def test_repair_op_rejects_stock_codes_that_conflict_with_qfq_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "gold_stk_mins_qfq_factor_repair_status",
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
                                    **_full_replay_config(
                                        stock_codes=["000001.SZ"],
                                    ),
                                }
                            }
                        }
                    },
                    raise_on_error=False,
                    resources=_resources(temp_dir),
                )

        self.assertFalse(result.success)
        self.assertIn(
            "MACD/KDJ repair stock_codes do not match qfq factor repair metadata",
            str(result.get_step_failure_events()[0].event_specific_data.error),
        )
        mocked_write_rows.assert_not_called()

    def test_repair_op_rejects_missing_upstream_batch_id(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch(
                "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                "write_gold_stk_mins_qfq_macd_kdj_rows",
            ) as mocked_write_rows:
                result = gold_stk_mins_qfq_macd_kdj_repair_job.execute_in_process(
                    run_config={
                        "ops": {
                            "gold_stk_mins_qfq_macd_kdj_repair_op": {
                                "config": _full_replay_config(upstream_batch_id="")
                            }
                        }
                    },
                    raise_on_error=False,
                    resources=_resources(temp_dir),
                )

        self.assertFalse(result.success)
        self.assertIn(
            MACD_KDJ_REPAIR_MANUAL_UNSUPPORTED_ERROR,
            str(result.get_step_failure_events()[0].event_specific_data.error),
        )
        mocked_write_rows.assert_not_called()

    def test_repair_op_rejects_scattered_manual_scope_before_writing(self) -> None:
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
                                    "stock_codes": list(REPAIR_CODES),
                                }
                            }
                        }
                    },
                    raise_on_error=False,
                    resources=_resources(temp_dir),
                )

        self.assertFalse(result.success)
        self.assertIn(
            MACD_KDJ_REPAIR_MANUAL_UNSUPPORTED_ERROR,
            str(result.get_step_failure_events()[0].event_specific_data.error),
        )
        mocked_write_rows.assert_not_called()

    def test_repair_op_rejects_empty_stock_codes_before_writing(self) -> None:
        for stock_codes in ([], ["", "   "]):
            with self.subTest(stock_codes=stock_codes):
                with TemporaryDirectory() as temp_dir:
                    with (
                        patch(
                            "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                            "gold_stk_mins_qfq_factor_repair_status",
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
                                        "config": _full_replay_config(
                                            stock_codes=stock_codes,
                                        )
                                    }
                                }
                            },
                            raise_on_error=False,
                            resources=_resources(temp_dir),
                        )

                self.assertFalse(result.success)
                self.assertIn(
                    MACD_KDJ_REPAIR_EMPTY_STOCK_CODES_ERROR,
                    str(result.get_step_failure_events()[0].event_specific_data.error),
                )
                mocked_write_rows.assert_not_called()

    def test_repair_op_rejects_upstream_batch_id_mismatch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "gold_stk_mins_qfq_factor_repair_status",
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
                                "config": _full_replay_config(
                                    upstream_batch_id=(
                                        f"qfq_factor_repair:{QFQ_FACTOR_REPAIR_DATE}:bad"
                                    )
                                )
                            }
                        }
                    },
                    raise_on_error=False,
                    resources=_resources(temp_dir),
                )

        self.assertFalse(result.success)
        self.assertIn(
            "MACD/KDJ repair upstream_batch_id does not match qfq factor repair metadata",
            str(result.get_step_failure_events()[0].event_specific_data.error),
        )
        mocked_write_rows.assert_not_called()

    def test_repair_op_rejects_explicit_scope_mismatch(self) -> None:
        mismatch_cases = (
            (
                {"start_trade_date": "2026-06-03"},
                "start_trade_date does not match qfq factor repair metadata",
            ),
            (
                {"repair_required_codes_hash": "c" * 64},
                "repair_required_codes_hash does not match qfq factor repair metadata",
            ),
        )
        for config_overrides, expected_message in mismatch_cases:
            with self.subTest(config_overrides=config_overrides):
                with TemporaryDirectory() as temp_dir:
                    with (
                        patch(
                            "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                            "gold_stk_mins_qfq_factor_repair_status",
                            return_value=_ready_qfq_factor_repair_status(),
                        ),
                        patch(
                            "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                            "write_gold_stk_mins_qfq_macd_kdj_rows",
                        ) as mocked_write_rows,
                    ):
                        result = (
                            gold_stk_mins_qfq_macd_kdj_repair_job.execute_in_process(
                                run_config={
                                    "ops": {
                                        "gold_stk_mins_qfq_macd_kdj_repair_op": {
                                            "config": _full_replay_config(
                                                **config_overrides,
                                            )
                                        }
                                    }
                                },
                                raise_on_error=False,
                                resources=_resources(temp_dir),
                            )
                        )

                self.assertFalse(result.success)
                self.assertIn(
                    expected_message,
                    str(result.get_step_failure_events()[0].event_specific_data.error),
                )
                mocked_write_rows.assert_not_called()

    def test_successful_replay_emits_fourteen_completion_check_events(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_calendar_rows(lake_root, DEFAULT_EXPECTED_TRADE_DATES)
            _touch_previous_state_files(lake_root)
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name,
                list(DEFAULT_TARGET_TRADE_DATES),
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
                    "gold_stk_mins_qfq_factor_repair_status",
                    return_value=_ready_qfq_factor_repair_status(),
                ),
                patch(
                    "orchestrator.defs.ops.gold_stk_mins_qfq_macd_kdj_repair."
                    "discover_gold_stk_mins_qfq_source_year_paths",
                    side_effect=fake_source_paths,
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
                                    **_full_replay_config(),
                                }
                            }
                        }
                    },
                    instance=instance,
                    resources=_resources(temp_dir),
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
                REPAIR_CODES_HASH,
            )
            self.assertEqual(
                evaluation.metadata["goldenshare/source_upstream_batch_id"].text,
                UPSTREAM_BATCH_ID,
            )
            self.assertNotIn(
                "goldenshare/source_qfq_factor_repair_event_storage_ids",
                evaluation.metadata,
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
