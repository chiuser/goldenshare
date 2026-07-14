from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
import unittest

import dagster as dg
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.asset_guards.stk_mins_qfq_macd_kdj import (
    gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_macd_kdj_repair_completion_events import (
    plan_stk_mins_qfq_macd_kdj_repair_completion_events,
    report_stk_mins_qfq_macd_kdj_repair_completion_events,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.run_keys import build_batch_id
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_FREQS
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
    gold_stk_mins_qfq_factor_repair_codes_hash,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
)


REPAIR_START_DATE = "2014-01-02"
REPAIR_CODES = ("000001.SZ", "600000.SH")
REPAIR_CODES_HASH = gold_stk_mins_qfq_factor_repair_codes_hash(REPAIR_CODES)
TRADE_DATES = ("2026-07-08", "2026-07-09", "2026-07-10", "2026-07-13")


class _FakeEventLogStorage:
    def __init__(self) -> None:
        self.records_by_check_key: dict[dg.AssetCheckKey, list[object]] = {}

    def add(self, check_key: dg.AssetCheckKey, record: object) -> None:
        self.records_by_check_key.setdefault(check_key, []).append(record)

    def get_latest_asset_check_execution_by_key(
        self,
        check_keys,
        *,
        partition_filter=None,
    ):
        partition_key = getattr(partition_filter, "key", None)
        results = {}
        for check_key in check_keys:
            records = self.records_by_check_key.get(check_key, ())
            candidates = [
                record
                for record in records
                if partition_key is None or record.partition == partition_key
            ]
            if candidates:
                results[check_key] = max(candidates, key=lambda record: record.id)
        return results

    def get_asset_check_execution_history(
        self,
        check_key,
        *,
        limit,
        cursor=None,
        status=None,
        partition_filter=None,
    ):
        records = sorted(
            self.records_by_check_key.get(check_key, ()),
            key=lambda record: record.id,
            reverse=True,
        )
        if status is not None:
            records = [record for record in records if record.status in status]
        partition_key = getattr(partition_filter, "key", None)
        if partition_key is not None:
            records = [record for record in records if record.partition == partition_key]
        if cursor is not None:
            records = [record for record in records if record.id < cursor]
        return records[:limit]


class _FakeInstance:
    def __init__(self) -> None:
        self.event_log_storage = _FakeEventLogStorage()
        self.runs: dict[str, object] = {}
        self.reported_events: list[object] = []
        self._next_storage_id = 10_000

    def get_run_by_id(self, run_id: str):
        return self.runs.get(run_id)

    def report_runless_asset_event(self, event) -> None:
        self.reported_events.append(event)
        self._next_storage_id += 1
        evaluation = event
        self.event_log_storage.add(
            dg.AssetCheckKey(evaluation.asset_key, evaluation.check_name),
            _check_record(
                storage_id=self._next_storage_id,
                partition=evaluation.partition,
                metadata=evaluation.metadata,
                run_id=None,
                passed=evaluation.passed,
                blocking=evaluation.blocking,
            ),
        )


class StkMinsQfqMacdKdjRepairCompletionEventTests(unittest.TestCase):
    def test_plan_keeps_four_same_start_batches_independent(self) -> None:
        instance = _build_instance(TRADE_DATES)

        plan = plan_stk_mins_qfq_macd_kdj_repair_completion_events(
            instance=instance,
            qfq_factor_repair_trade_dates=TRADE_DATES,
        )

        self.assertFalse(plan.should_stop)
        self.assertEqual(plan.source_completion_event_count, 56)
        self.assertEqual(plan.existing_target_event_count, 0)
        self.assertEqual(plan.planned_event_count, 56)
        self.assertEqual(
            [batch.qfq_factor_repair_trade_date for batch in plan.batches],
            list(TRADE_DATES),
        )
        self.assertTrue(
            all(batch.repair_start_trade_date == REPAIR_START_DATE for batch in plan.batches)
        )

    def test_dry_run_writes_no_events(self) -> None:
        instance = _build_instance((TRADE_DATES[0],))

        report = report_stk_mins_qfq_macd_kdj_repair_completion_events(
            instance=instance,
            qfq_factor_repair_trade_dates=(TRADE_DATES[0],),
            dry_run=True,
        )

        self.assertTrue(report.dry_run)
        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(report.plan.planned_event_count, 14)
        self.assertEqual(instance.reported_events, [])

    def test_plan_rejects_unapproved_rehydration_trade_date(self) -> None:
        instance = _build_instance((TRADE_DATES[0],))

        with self.assertRaisesRegex(ValueError, "only permits the approved R5-P5"):
            plan_stk_mins_qfq_macd_kdj_repair_completion_events(
                instance=instance,
                qfq_factor_repair_trade_dates=("2026-07-14",),
            )

    def test_apply_writes_target_partition_and_converges_idempotently(self) -> None:
        trade_date = TRADE_DATES[0]
        instance = _build_instance((trade_date,))
        plan = plan_stk_mins_qfq_macd_kdj_repair_completion_events(
            instance=instance,
            qfq_factor_repair_trade_dates=(trade_date,),
        )

        report = report_stk_mins_qfq_macd_kdj_repair_completion_events(
            instance=instance,
            qfq_factor_repair_trade_dates=(trade_date,),
            dry_run=False,
            expected_plan_fingerprint=plan.fingerprint,
        )
        repeated_plan = plan_stk_mins_qfq_macd_kdj_repair_completion_events(
            instance=instance,
            qfq_factor_repair_trade_dates=(trade_date,),
        )

        self.assertFalse(report.dry_run)
        self.assertEqual(report.reported_event_count, 14)
        self.assertIsNotNone(report.post_apply_plan)
        self.assertEqual(report.post_apply_plan.planned_event_count, 0)
        self.assertEqual(repeated_plan.planned_event_count, 0)
        self.assertEqual(len(instance.reported_events), 14)
        self.assertTrue(
            all(event.partition == trade_date for event in instance.reported_events)
        )
        self.assertTrue(
            all(
                _metadata_value(event.metadata["goldenshare/bootstrap_method"])
                == "repair_completion_identity_rehydration"
                for event in instance.reported_events
            )
        )

    def test_conflicting_target_event_stops_without_planning_writes(self) -> None:
        trade_date = TRADE_DATES[0]
        instance = _build_instance((trade_date,))
        asset_key = _repair_completion_asset_keys()[0]
        instance.event_log_storage.add(
            dg.AssetCheckKey(
                asset_key,
                GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
            ),
            _check_record(
                storage_id=20_000,
                partition=trade_date,
                metadata=_completion_metadata(
                    trade_date=trade_date,
                    upstream_batch_id="qfq_factor_repair:conflict",
                ),
                run_id="conflict-run",
            ),
        )

        plan = plan_stk_mins_qfq_macd_kdj_repair_completion_events(
            instance=instance,
            qfq_factor_repair_trade_dates=(trade_date,),
        )

        self.assertTrue(plan.should_stop)
        self.assertEqual(plan.planned_event_count, 13)
        self.assertIn("target_completion_event_conflicts", plan.batches[0].stop_reasons[0])

    def test_missing_source_completion_event_stops_without_writes(self) -> None:
        trade_date = TRADE_DATES[0]
        instance = _build_instance((trade_date,))
        check_key = dg.AssetCheckKey(
            _repair_completion_asset_keys()[0],
            GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
        )
        instance.event_log_storage.records_by_check_key[check_key] = []

        plan = plan_stk_mins_qfq_macd_kdj_repair_completion_events(
            instance=instance,
            qfq_factor_repair_trade_dates=(trade_date,),
        )

        self.assertTrue(plan.should_stop)
        self.assertEqual(plan.planned_event_count, 0)
        self.assertIn("source_completion_event_missing", plan.batches[0].stop_reasons[0])

    def test_new_partition_completion_gate_rejects_a_different_upstream_batch(self) -> None:
        trade_date = TRADE_DATES[0]
        instance = _build_instance((trade_date,))
        plan = plan_stk_mins_qfq_macd_kdj_repair_completion_events(
            instance=instance,
            qfq_factor_repair_trade_dates=(trade_date,),
        )
        report_stk_mins_qfq_macd_kdj_repair_completion_events(
            instance=instance,
            qfq_factor_repair_trade_dates=(trade_date,),
            dry_run=False,
            expected_plan_fingerprint=plan.fingerprint,
        )
        upstream_batch_id = _upstream_batch_id(trade_date)

        status = gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch(
            instance,
            qfq_factor_repair_trade_date=trade_date,
            repair_start_trade_date=REPAIR_START_DATE,
            repair_end_trade_date=trade_date,
            upstream_batch_id=f"{upstream_batch_id}:different",
            repair_required_code_count=len(REPAIR_CODES),
            repair_required_codes_hash=REPAIR_CODES_HASH,
        )

        self.assertFalse(status.ready)


def _build_instance(trade_dates: tuple[str, ...]) -> _FakeInstance:
    instance = _FakeInstance()
    for index, trade_date in enumerate(trade_dates, start=1):
        producer_run_id = f"qfq-factor-repair-run-{index}"
        repair_run_id = f"macd-kdj-repair-run-{index}"
        instance.runs[producer_run_id] = SimpleNamespace(
            status=dg.DagsterRunStatus.SUCCESS
        )
        instance.runs[repair_run_id] = SimpleNamespace(status=dg.DagsterRunStatus.SUCCESS)
        upstream_batch_id = _upstream_batch_id(trade_date, producer_run_id=producer_run_id)
        for qfq_index, asset_key in enumerate(_qfq_asset_keys()):
            instance.event_log_storage.add(
                dg.AssetCheckKey(asset_key, GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME),
                _check_record(
                    storage_id=1_000 + index * 100 + qfq_index,
                    partition=trade_date,
                    metadata=_qfq_metadata(
                        trade_date=trade_date,
                        producer_run_id=producer_run_id,
                        upstream_batch_id=upstream_batch_id,
                    ),
                    run_id=producer_run_id,
                ),
            )
        for completion_index, asset_key in enumerate(_repair_completion_asset_keys()):
            instance.event_log_storage.add(
                dg.AssetCheckKey(
                    asset_key,
                    GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
                ),
                _check_record(
                    storage_id=2_000 + index * 100 + completion_index,
                    partition=REPAIR_START_DATE,
                    metadata=_completion_metadata(
                        trade_date=trade_date,
                        upstream_batch_id=upstream_batch_id,
                    ),
                    run_id=repair_run_id,
                ),
            )
    return instance


def _qfq_asset_keys() -> tuple[dg.AssetKey, ...]:
    return tuple(dg.AssetKey(f"gold_stk_mins_qfq_{freq}m") for freq in STK_MINS_QFQ_FREQS)


def _repair_completion_asset_keys() -> tuple[dg.AssetKey, ...]:
    return tuple(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_{freq}m")
        for freq in STK_MINS_QFQ_FREQS
    ) + tuple(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_state_{freq}m")
        for freq in STK_MINS_QFQ_FREQS
    )


def _qfq_metadata(
    *,
    trade_date: str,
    producer_run_id: str,
    upstream_batch_id: str,
) -> Mapping[str, object]:
    return build_check_metadata(
        check_scope=CheckScope.RECONCILIATION,
        checked_row_count=1,
        failed_row_count=0,
        extra_metadata={
            "producer_run_id": producer_run_id,
            "upstream_batch_id": upstream_batch_id,
            "repair_required": True,
            "repair_required_code_count": len(REPAIR_CODES),
            "repair_required_codes": list(REPAIR_CODES),
            "repair_required_codes_hash": REPAIR_CODES_HASH,
            "repair_required_codes_truncated": False,
            "repair_start_trade_date": REPAIR_START_DATE,
            "repair_end_trade_date": trade_date,
            "selected_partition_count": 1_000,
            "rewritten_file_count": 1,
            "rewritten_row_count": 1,
            "derived_rewrite_required": True,
            "derived_rewritten_file_count": 1,
            "derived_rewritten_row_count": 1,
        },
    )


def _completion_metadata(*, trade_date: str, upstream_batch_id: str) -> Mapping[str, object]:
    return build_check_metadata(
        check_scope=CheckScope.RECONCILIATION,
        checked_row_count=1,
        failed_row_count=0,
        extra_metadata={
            "qfq_factor_repair_trade_date": trade_date,
            "covered_start_trade_date": REPAIR_START_DATE,
            "covered_end_trade_date": trade_date,
            "freqs": list(STK_MINS_QFQ_FREQS),
            "stock_code_scope": "explicit",
            "stock_code_count": len(REPAIR_CODES),
            "repair_required_code_count": len(REPAIR_CODES),
            "repair_required_codes_hash": REPAIR_CODES_HASH,
            "source_upstream_batch_id": upstream_batch_id,
        },
    )


def _upstream_batch_id(
    trade_date: str,
    *,
    producer_run_id: str | None = None,
) -> str:
    return build_batch_id(
        producer="qfq_factor_repair",
        scope=trade_date,
        payload={
            "producer_run_id": producer_run_id or f"qfq-factor-repair-run-{trade_date}",
            "repair_required_codes_hash": REPAIR_CODES_HASH,
        },
    )


def _check_record(
    *,
    storage_id: int,
    partition: str,
    metadata: Mapping[str, object],
    run_id: str | None,
    passed: bool = True,
    blocking: bool = True,
):
    evaluation = SimpleNamespace(
        passed=passed,
        blocking=blocking,
        partition=partition,
        metadata=dict(metadata),
    )
    event = SimpleNamespace(
        storage_id=storage_id,
        run_id=run_id,
        dagster_event=SimpleNamespace(event_specific_data=evaluation),
    )
    return SimpleNamespace(
        id=storage_id,
        partition=partition,
        status=AssetCheckExecutionRecordStatus.SUCCEEDED,
        event=event,
    )


def _metadata_value(value: object) -> object:
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "text"):
        return value.text
    return value


if __name__ == "__main__":
    unittest.main()
