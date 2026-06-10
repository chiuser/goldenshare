from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_bootstrap_events import (
    GOLD_STK_MINS_QFQ_ASSET_KEYS,
    GOLD_STK_MINS_QFQ_CHECKS,
    StkMinsQfqBootstrapCheckAudit,
    StkMinsQfqBootstrapPartitionAudit,
    report_stk_mins_qfq_partition_events,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_derived_bootstrap_events import (
    GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS,
    GOLD_STK_MINS_QFQ_DERIVED_CHECKS,
    report_stk_mins_qfq_derived_partition_events,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_repair_reconciliation_events import (
    STK_MINS_QFQ_REPAIR_RECONCILIATION_SOURCE_METHOD,
    build_stk_mins_qfq_repair_reconciliation_plan,
    report_stk_mins_qfq_repair_reconciliation_events,
)
from orchestrator.defs.jobs.gold_stk_mins_qfq_repair_event_reconciliation import (
    GOLD_STK_MINS_QFQ_REPAIR_EVENT_RECONCILIATION_JOB_NAME,
)
from orchestrator.defs.ops.gold_stk_mins_qfq_repair_event_reconciliation import (
    _assert_reconciliation_source_matches_latest_repair,
)
from orchestrator.defs.sensors.gold_stk_mins_qfq_repair_event_reconciliation_job_sensor import (
    _run_request_for_reconciliation_decision,
    build_gold_stk_mins_qfq_repair_event_reconciliation_run_status_decision,
    gold_stk_mins_qfq_repair_event_reconciliation_job_sensor,
)


TRADE_DATE = "2026-06-05"
REPAIR_START_DATE = "2026-06-03"
REPAIR_CODES_HASH = "c" * 64
EVENT_IDS = (101, 102, 103, 104, 105, 106, 107)


def _qfq_factor_repair_status(
    *,
    ready: bool = True,
    rewrote_history: bool = True,
    derived_rewrite_required: bool = True,
) -> GoldStkMinsQfqFactorRepairStatus:
    return GoldStkMinsQfqFactorRepairStatus(
        ready=ready,
        trade_date=TRADE_DATE,
        reason="ready" if ready else "not ready",
        repair_required=rewrote_history,
        qfq_factor_repair_event_storage_ids=EVENT_IDS,
        repair_start_trade_date=REPAIR_START_DATE,
        repair_end_trade_date=TRADE_DATE,
        selected_partition_count=2,
        repair_required_code_count=1 if rewrote_history else 0,
        repair_required_codes=("600000.SH",) if rewrote_history else (),
        repair_required_codes_hash=REPAIR_CODES_HASH,
        repair_required_codes_truncated=False,
        rewritten_file_count=1 if rewrote_history else 0,
        rewritten_row_count=10 if rewrote_history else 0,
        derived_rewrite_required=derived_rewrite_required,
        derived_rewritten_file_count=1 if derived_rewrite_required else 0,
        derived_rewritten_row_count=10 if derived_rewrite_required else 0,
    )


def _audit(
    *,
    freq: int,
    asset_key: dg.AssetKey,
    check_name: str,
) -> StkMinsQfqBootstrapPartitionAudit:
    return StkMinsQfqBootstrapPartitionAudit(
        freq=freq,
        partition_key=TRADE_DATE,
        asset_key=asset_key,
        output_root_path=Path(f"/tmp/gold-qfq-{freq}m"),
        passed=True,
        row_count=1,
        observed_columns=("ts_code", "trade_date"),
        expected_file_count=1,
        existing_file_count=1,
        checks=(
            StkMinsQfqBootstrapCheckAudit(
                check_name=check_name,
                passed=True,
                metadata={"goldenshare/test_check": "ok"},
            ),
        ),
    )


def _latest_materialization_record(
    instance: dg.DagsterInstance,
    *,
    asset_key: dg.AssetKey,
):
    return instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=asset_key,
            asset_partitions=[TRADE_DATE],
        ),
        limit=1,
    ).records[0]


def _materialization_metadata(record) -> dict[str, object]:
    event_data = record.event_log_entry.dagster_event.event_specific_data
    return event_data.materialization.metadata


def _check_evaluations(instance: dg.DagsterInstance) -> tuple[object, ...]:
    records = instance.get_event_records(
        dg.EventRecordsFilter(
            event_type=dg.DagsterEventType.ASSET_CHECK_EVALUATION,
        ),
        limit=20,
    )
    return tuple(
        record.event_log_entry.dagster_event.event_specific_data
        for record in records
    )


class StkMinsQfqRepairReconciliationTests(unittest.TestCase):
    def test_native_and_derived_reporters_bind_checks_to_new_materialization(self) -> None:
        instance = dg.DagsterInstance.ephemeral()
        extra_metadata = {
            "bootstrap_event_backfill": False,
            "source_qfq_factor_repair_trade_date": TRADE_DATE,
            "source_qfq_factor_repair_event_storage_ids": list(EVENT_IDS),
            "repair_required_codes_hash": REPAIR_CODES_HASH,
            "repair_start_trade_date": REPAIR_START_DATE,
            "repair_end_trade_date": TRADE_DATE,
        }
        native_audit = _audit(
            freq=5,
            asset_key=GOLD_STK_MINS_QFQ_ASSET_KEYS[5],
            check_name=GOLD_STK_MINS_QFQ_CHECKS[0],
        )
        derived_audit = _audit(
            freq=90,
            asset_key=GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS[90],
            check_name=GOLD_STK_MINS_QFQ_DERIVED_CHECKS[0],
        )

        native_event_count = report_stk_mins_qfq_partition_events(
            instance=instance,
            audit=native_audit,
            source_method=STK_MINS_QFQ_REPAIR_RECONCILIATION_SOURCE_METHOD,
            extra_metadata=extra_metadata,
        )
        derived_event_count = report_stk_mins_qfq_derived_partition_events(
            instance=instance,
            audit=derived_audit,
            source_method=STK_MINS_QFQ_REPAIR_RECONCILIATION_SOURCE_METHOD,
            extra_metadata=extra_metadata,
        )
        native_materialization = _latest_materialization_record(
            instance,
            asset_key=GOLD_STK_MINS_QFQ_ASSET_KEYS[5],
        )
        derived_materialization = _latest_materialization_record(
            instance,
            asset_key=GOLD_STK_MINS_QFQ_DERIVED_ASSET_KEYS[90],
        )
        check_evaluations = _check_evaluations(instance)
        target_storage_ids = {
            evaluation.target_materialization_data.storage_id
            for evaluation in check_evaluations
        }

        self.assertEqual(native_event_count, 2)
        self.assertEqual(derived_event_count, 2)
        self.assertIn(native_materialization.storage_id, target_storage_ids)
        self.assertIn(derived_materialization.storage_id, target_storage_ids)
        native_metadata = _materialization_metadata(native_materialization)
        self.assertEqual(
            native_metadata["goldenshare/source_method"].text,
            STK_MINS_QFQ_REPAIR_RECONCILIATION_SOURCE_METHOD,
        )
        self.assertFalse(native_metadata["goldenshare/bootstrap_event_backfill"].value)
        self.assertEqual(
            native_metadata[
                "goldenshare/source_qfq_factor_repair_event_storage_ids"
            ].value,
            list(EVENT_IDS),
        )

    def test_reconciliation_plan_includes_derived_only_when_derived_was_rewritten(
        self,
    ) -> None:
        with_derived = build_stk_mins_qfq_repair_reconciliation_plan(
            qfq_factor_repair_status=_qfq_factor_repair_status(
                derived_rewrite_required=True
            ),
            registered_partition_keys=[
                "2026-06-02",
                REPAIR_START_DATE,
                TRADE_DATE,
                "2026-06-08",
            ],
        )
        without_derived = build_stk_mins_qfq_repair_reconciliation_plan(
            qfq_factor_repair_status=_qfq_factor_repair_status(
                derived_rewrite_required=False
            ),
            registered_partition_keys=[REPAIR_START_DATE, TRADE_DATE],
        )

        self.assertEqual(with_derived.selected_partition_keys, (REPAIR_START_DATE, TRADE_DATE))
        self.assertEqual(len(with_derived.native_batches), 5)
        self.assertEqual(len(with_derived.derived_batches), 2)
        self.assertEqual(with_derived.native_asset_partition_count, 10)
        self.assertEqual(with_derived.derived_asset_partition_count, 4)
        self.assertEqual(without_derived.derived_batches, ())

    def test_reconciliation_report_passes_repair_trade_date_as_native_as_of(self) -> None:
        with (
            patch(
                "orchestrator.defs.bootstrap."
                "stk_mins_qfq_repair_reconciliation_events."
                "audit_stk_mins_qfq_bootstrap_batch",
                return_value=(),
            ) as mocked_native_audit,
            patch(
                "orchestrator.defs.bootstrap."
                "stk_mins_qfq_repair_reconciliation_events."
                "audit_stk_mins_qfq_derived_bootstrap_batch",
                return_value=(),
            ) as mocked_derived_audit,
        ):
            report = report_stk_mins_qfq_repair_reconciliation_events(
                instance=dg.DagsterInstance.ephemeral(),
                duckdb=SimpleNamespace(),
                registered_partition_keys=[REPAIR_START_DATE, TRADE_DATE],
                qfq_factor_repair_status=_qfq_factor_repair_status(
                    derived_rewrite_required=False
                ),
                dry_run=True,
            )

        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(mocked_native_audit.call_count, 5)
        for call in mocked_native_audit.call_args_list:
            self.assertEqual(call.kwargs["as_of_trade_date"], TRADE_DATE)
        mocked_derived_audit.assert_not_called()

    def test_reconciliation_source_mismatch_fails_closed(self) -> None:
        with self.assertRaises(dg.Failure):
            _assert_reconciliation_source_matches_latest_repair(
                qfq_factor_repair_status=_qfq_factor_repair_status(),
                expected_event_ids=(999,),
                expected_codes_hash=REPAIR_CODES_HASH,
            )
        with self.assertRaises(dg.Failure):
            _assert_reconciliation_source_matches_latest_repair(
                qfq_factor_repair_status=_qfq_factor_repair_status(),
                expected_event_ids=EVENT_IDS,
                expected_codes_hash="bad-hash",
            )

    def test_reconciliation_sensor_definition_and_run_request_contract(self) -> None:
        status = _qfq_factor_repair_status()
        decision = (
            build_gold_stk_mins_qfq_repair_event_reconciliation_run_status_decision(
                target_trade_date=TRADE_DATE,
                qfq_factor_repair_status=status,
            )
        )
        request = _run_request_for_reconciliation_decision(decision)
        op_config = request.run_config["ops"][
            "gold_stk_mins_qfq_repair_event_reconciliation_op"
        ]["config"]

        self.assertEqual(
            gold_stk_mins_qfq_repair_event_reconciliation_job_sensor.name,
            f"{GOLD_STK_MINS_QFQ_REPAIR_EVENT_RECONCILIATION_JOB_NAME}_sensor",
        )
        self.assertEqual(
            gold_stk_mins_qfq_repair_event_reconciliation_job_sensor.default_status,
            dg.DefaultSensorStatus.STOPPED,
        )
        self.assertEqual(decision.selected_trade_date, TRADE_DATE)
        self.assertEqual(op_config["trade_date"], TRADE_DATE)
        self.assertEqual(
            op_config["source_qfq_factor_repair_event_storage_ids"],
            list(EVENT_IDS),
        )
        self.assertEqual(op_config["repair_required_codes_hash"], REPAIR_CODES_HASH)
        self.assertIn(TRADE_DATE, request.run_key)
        self.assertIn(REPAIR_CODES_HASH, request.run_key)
        self.assertIn(",".join(str(event_id) for event_id in EVENT_IDS), request.run_key)

    def test_reconciliation_sensor_skips_when_repair_not_ready_or_no_rewrite(self) -> None:
        not_ready = (
            build_gold_stk_mins_qfq_repair_event_reconciliation_run_status_decision(
                target_trade_date=TRADE_DATE,
                qfq_factor_repair_status=_qfq_factor_repair_status(ready=False),
            )
        )
        no_rewrite = (
            build_gold_stk_mins_qfq_repair_event_reconciliation_run_status_decision(
                target_trade_date=TRADE_DATE,
                qfq_factor_repair_status=_qfq_factor_repair_status(
                    rewrote_history=False,
                    derived_rewrite_required=False,
                ),
            )
        )

        self.assertIsNone(not_ready.selected_trade_date)
        self.assertIsNone(no_rewrite.selected_trade_date)


if __name__ == "__main__":
    unittest.main()
