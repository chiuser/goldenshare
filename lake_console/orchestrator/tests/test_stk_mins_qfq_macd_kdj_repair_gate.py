from types import SimpleNamespace
import unittest

import dagster as dg
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    gold_stk_mins_qfq_factor_repair_status,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_macd_kdj import (
    gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch,
    gold_stk_mins_qfq_macd_kdj_daily_repair_gate_status,
    legacy_gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_qfq_event_storage_ids,
)
from orchestrator.defs.run_contracts.run_keys import build_batch_id
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_FREQS
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
    gold_stk_mins_qfq_factor_repair_codes_hash,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
)


TRADE_DATE = "2026-06-05"
REPAIR_START_DATE = "2014-01-02"
REPAIR_CODES = ("000001.SZ", "600000.SH", "600001.SH")
REPAIR_CODES_HASH = gold_stk_mins_qfq_factor_repair_codes_hash(REPAIR_CODES)
QFQ_EVENT_STORAGE_IDS = tuple(100 + index for index in range(len(STK_MINS_QFQ_FREQS)))
PRODUCER_RUN_ID = "qfq-factor-repair-run-1"
UPSTREAM_BATCH_ID = build_batch_id(
    producer="qfq_factor_repair",
    scope=TRADE_DATE,
    payload={
        "producer_run_id": PRODUCER_RUN_ID,
        "repair_required_codes_hash": REPAIR_CODES_HASH,
    },
)


class _FakeEventLogStorage:
    def __init__(self, records_by_check_key):
        self.records_by_check_key = records_by_check_key
        self.latest_call_count = 0
        self.history_call_count = 0

    def get_latest_asset_check_execution_by_key(
        self,
        check_keys,
        *,
        partition_filter=None,
    ):
        self.latest_call_count += 1
        partition_key = getattr(partition_filter, "key", None)
        return {
            check_key: record
            for check_key, record in self.records_by_check_key.items()
            if check_key in check_keys
            and (partition_key is None or record.partition == partition_key)
        }

    def get_asset_check_execution_history(self, *args, **kwargs):
        self.history_call_count += 1
        raise AssertionError("MACD/KDJ repair gate must not scan check history")


class _FakeInstance:
    def __init__(self, records_by_check_key):
        self.event_log_storage = _FakeEventLogStorage(records_by_check_key)


def _qfq_asset_keys() -> tuple[dg.AssetKey, ...]:
    return tuple(dg.AssetKey(f"gold_stk_mins_qfq_{freq}m") for freq in STK_MINS_QFQ_FREQS)


def _macd_kdj_asset_keys() -> tuple[dg.AssetKey, ...]:
    return tuple(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_{freq}m")
        for freq in STK_MINS_QFQ_FREQS
    ) + tuple(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_state_{freq}m")
        for freq in STK_MINS_QFQ_FREQS
    )


def _check_key(asset_key: dg.AssetKey, check_name: str) -> dg.AssetCheckKey:
    return dg.AssetCheckKey(asset_key, check_name)


def _record(
    *,
    storage_id: int,
    partition: str,
    metadata: dict[str, object],
    passed: bool = True,
    blocking: bool = True,
    status: AssetCheckExecutionRecordStatus = AssetCheckExecutionRecordStatus.SUCCEEDED,
):
    evaluation = SimpleNamespace(
        passed=passed,
        blocking=blocking,
        partition=partition,
        metadata={f"goldenshare/{key}": value for key, value in metadata.items()},
    )
    event = SimpleNamespace(
        storage_id=storage_id,
        dagster_event=SimpleNamespace(event_specific_data=evaluation),
    )
    return SimpleNamespace(status=status, event=event, partition=partition)


def _qfq_metadata(*, rewrote_history: bool) -> dict[str, object]:
    repair_required_codes_hash = (
        REPAIR_CODES_HASH
        if rewrote_history
        else gold_stk_mins_qfq_factor_repair_codes_hash(())
    )
    return {
        "producer_run_id": PRODUCER_RUN_ID,
        "upstream_batch_id": (
            UPSTREAM_BATCH_ID
            if rewrote_history
            else build_batch_id(
                producer="qfq_factor_repair",
                scope=TRADE_DATE,
                payload={
                    "producer_run_id": PRODUCER_RUN_ID,
                    "repair_required_codes_hash": repair_required_codes_hash,
                },
            )
        ),
        "repair_required": rewrote_history,
        "repair_required_code_count": 3 if rewrote_history else 0,
        "repair_required_codes": list(REPAIR_CODES) if rewrote_history else [],
        "repair_required_codes_hash": repair_required_codes_hash,
        "repair_required_codes_truncated": False,
        "repair_start_trade_date": REPAIR_START_DATE,
        "repair_end_trade_date": TRADE_DATE,
        "selected_partition_count": 1800,
        "rewritten_file_count": 7 if rewrote_history else 0,
        "rewritten_row_count": 100 if rewrote_history else 0,
        "derived_rewrite_required": rewrote_history,
        "derived_rewritten_file_count": 2 if rewrote_history else 0,
        "derived_rewritten_row_count": 30 if rewrote_history else 0,
    }


def _macd_kdj_metadata(
    *,
    covered_start_trade_date: str = REPAIR_START_DATE,
    covered_end_trade_date: str = TRADE_DATE,
    freqs: tuple[int, ...] = STK_MINS_QFQ_FREQS,
    stock_code_scope: str = "explicit",
    stock_code_count: int = 3,
    repair_required_code_count: int = 3,
    repair_required_codes_hash: str = REPAIR_CODES_HASH,
    source_upstream_batch_id: str = UPSTREAM_BATCH_ID,
) -> dict[str, object]:
    return {
        "covered_start_trade_date": covered_start_trade_date,
        "covered_end_trade_date": covered_end_trade_date,
        "freqs": list(freqs),
        "stock_code_scope": stock_code_scope,
        "stock_code_count": stock_code_count,
        "repair_required_code_count": repair_required_code_count,
        "repair_required_codes_hash": repair_required_codes_hash,
        "source_upstream_batch_id": source_upstream_batch_id,
    }


def _legacy_macd_kdj_metadata(
    *,
    covered_start_trade_date: str = REPAIR_START_DATE,
    covered_end_trade_date: str = TRADE_DATE,
    freqs: tuple[int, ...] = STK_MINS_QFQ_FREQS,
    stock_code_scope: str = "explicit",
    stock_code_count: int = 3,
    repair_required_code_count: int = 3,
    repair_required_codes_hash: str = REPAIR_CODES_HASH,
    source_qfq_factor_repair_event_storage_ids: tuple[int, ...] = QFQ_EVENT_STORAGE_IDS,
) -> dict[str, object]:
    metadata = _macd_kdj_metadata(
        covered_start_trade_date=covered_start_trade_date,
        covered_end_trade_date=covered_end_trade_date,
        freqs=freqs,
        stock_code_scope=stock_code_scope,
        stock_code_count=stock_code_count,
        repair_required_code_count=repair_required_code_count,
        repair_required_codes_hash=repair_required_codes_hash,
    )
    metadata.pop("source_upstream_batch_id")
    metadata.update(
        {
            "source_qfq_factor_repair_event_storage_ids": list(
                source_qfq_factor_repair_event_storage_ids
            )
        }
    )
    return metadata


def _qfq_records(*, rewrote_history: bool, partition: str = TRADE_DATE):
    return {
        _check_key(asset_key, GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME): _record(
            storage_id=100 + index,
            partition=partition,
            metadata=_qfq_metadata(rewrote_history=rewrote_history),
        )
        for index, asset_key in enumerate(_qfq_asset_keys())
    }


def _macd_kdj_records(
    *,
    storage_start: int = 200,
    metadata: dict[str, object] | None = None,
):
    return {
        _check_key(
            asset_key,
            GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
        ): _record(
            storage_id=storage_start + index,
            partition=REPAIR_START_DATE,
            metadata=metadata or _macd_kdj_metadata(),
        )
        for index, asset_key in enumerate(_macd_kdj_asset_keys())
    }


class StkMinsQfqMacdKdjRepairGateTests(unittest.TestCase):
    def test_qfq_factor_repair_status_exposes_upstream_batch_identity(self):
        instance = _FakeInstance(_qfq_records(rewrote_history=True))

        status = gold_stk_mins_qfq_factor_repair_status(instance, TRADE_DATE)

        self.assertTrue(status.ready)
        self.assertEqual(status.producer_run_id, PRODUCER_RUN_ID)
        self.assertEqual(
            status.upstream_batch_id,
            UPSTREAM_BATCH_ID,
        )
        self.assertEqual(
            status.to_payload()["upstream_batch_id"],
            status.upstream_batch_id,
        )

    def test_qfq_factor_repair_status_rejects_inconsistent_batch_identity(self):
        for field, value in (
            ("producer_run_id", "qfq-factor-repair-run-2"),
            ("upstream_batch_id", "qfq_factor_repair:2026-06-05:badbadbadbad"),
        ):
            with self.subTest(field=field):
                records = dict(_qfq_records(rewrote_history=True))
                first_asset_key = _qfq_asset_keys()[0]
                inconsistent_metadata = _qfq_metadata(rewrote_history=True)
                inconsistent_metadata[field] = value
                records[
                    _check_key(
                        first_asset_key,
                        GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
                    )
                ] = _record(
                    storage_id=99,
                    partition=TRADE_DATE,
                    metadata=inconsistent_metadata,
                )
                instance = _FakeInstance(records)

                status = gold_stk_mins_qfq_factor_repair_status(instance, TRADE_DATE)

                self.assertFalse(status.ready)
                self.assertIn("batch or code scope", status.reason)

    def test_qfq_factor_repair_status_rejects_missing_batch_identity(self):
        records = dict(_qfq_records(rewrote_history=True))
        first_asset_key = _qfq_asset_keys()[0]
        incomplete_metadata = _qfq_metadata(rewrote_history=True)
        incomplete_metadata.pop("upstream_batch_id")
        records[
            _check_key(
                first_asset_key,
                GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
            )
        ] = _record(
            storage_id=99,
            partition=TRADE_DATE,
            metadata=incomplete_metadata,
        )
        instance = _FakeInstance(records)

        status = gold_stk_mins_qfq_factor_repair_status(instance, TRADE_DATE)

        self.assertFalse(status.ready)
        self.assertIn(first_asset_key.to_user_string(), status.failed_qfq_asset_keys)

    def test_qfq_repair_without_history_rewrite_is_ready_without_macd_kdj_completion(
        self,
    ):
        instance = _FakeInstance(_qfq_records(rewrote_history=False))

        status = gold_stk_mins_qfq_macd_kdj_daily_repair_gate_status(
            instance,
            TRADE_DATE,
        )

        self.assertTrue(status.ready)
        self.assertFalse(status.requires_macd_kdj_repair)
        self.assertEqual(status.repair_start_trade_date, REPAIR_START_DATE)
        self.assertEqual(instance.event_log_storage.latest_call_count, 1)
        self.assertEqual(instance.event_log_storage.history_call_count, 0)

    def test_missing_or_wrong_partition_qfq_repair_fails_closed(self):
        missing_instance = _FakeInstance({})
        wrong_partition_instance = _FakeInstance(
            _qfq_records(rewrote_history=False, partition="2026-06-04")
        )

        missing_status = gold_stk_mins_qfq_macd_kdj_daily_repair_gate_status(
            missing_instance,
            TRADE_DATE,
        )
        wrong_partition_status = gold_stk_mins_qfq_macd_kdj_daily_repair_gate_status(
            wrong_partition_instance,
            TRADE_DATE,
        )

        self.assertFalse(missing_status.ready)
        self.assertEqual(len(missing_status.missing_qfq_asset_keys), 7)
        self.assertFalse(wrong_partition_status.ready)
        self.assertEqual(len(wrong_partition_status.missing_qfq_asset_keys), 7)

    def test_failed_or_incomplete_qfq_repair_metadata_fails_closed(self):
        asset_key = _qfq_asset_keys()[0]
        records = dict(_qfq_records(rewrote_history=False))
        records[_check_key(asset_key, GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME)] = (
            _record(
                storage_id=99,
                partition=TRADE_DATE,
                metadata={"repair_required": False},
            )
        )
        instance = _FakeInstance(records)

        status = gold_stk_mins_qfq_macd_kdj_daily_repair_gate_status(
            instance,
            TRADE_DATE,
        )

        self.assertFalse(status.ready)
        self.assertIn(asset_key.to_user_string(), status.failed_qfq_asset_keys)

    def test_history_rewrite_requires_macd_kdj_completion(self):
        instance = _FakeInstance(_qfq_records(rewrote_history=True))

        status = gold_stk_mins_qfq_macd_kdj_daily_repair_gate_status(
            instance,
            TRADE_DATE,
        )

        self.assertFalse(status.ready)
        self.assertTrue(status.requires_macd_kdj_repair)
        self.assertIsNotNone(status.macd_kdj_repair_status)
        self.assertEqual(instance.event_log_storage.latest_call_count, 2)

    def test_history_rewrite_with_valid_macd_kdj_completion_is_ready(self):
        records = {
            **_qfq_records(rewrote_history=True),
            **_macd_kdj_records(),
        }
        instance = _FakeInstance(records)

        status = gold_stk_mins_qfq_macd_kdj_daily_repair_gate_status(
            instance,
            TRADE_DATE,
        )

        self.assertTrue(status.ready)
        self.assertTrue(status.requires_macd_kdj_repair)
        self.assertEqual(len(status.macd_kdj_repair_event_storage_ids), 14)
        self.assertEqual(
            status.macd_kdj_repair_status.source_upstream_batch_id,
            UPSTREAM_BATCH_ID,
        )

    def test_new_completion_gate_does_not_depend_on_event_storage_id_ordering(self):
        instance = _FakeInstance(
            {
                **_qfq_records(rewrote_history=True),
                **_macd_kdj_records(storage_start=50),
            }
        )

        status = gold_stk_mins_qfq_macd_kdj_daily_repair_gate_status(
            instance,
            TRADE_DATE,
        )

        self.assertTrue(status.ready)
        self.assertTrue(status.macd_kdj_repair_status.ready)

    def test_macd_kdj_completion_undercovered_fails_closed(self):
        undercovered_instance = _FakeInstance(
            {
                **_qfq_records(rewrote_history=True),
                **_macd_kdj_records(
                    metadata=_macd_kdj_metadata(
                        covered_start_trade_date="2015-01-05"
                    )
                ),
            }
        )

        undercovered_status = gold_stk_mins_qfq_macd_kdj_daily_repair_gate_status(
            undercovered_instance,
            TRADE_DATE,
        )

        self.assertFalse(undercovered_status.ready)

    def test_completion_gate_can_be_called_directly_by_upstream_batch_id(self):
        instance = _FakeInstance(_macd_kdj_records(storage_start=50))

        status = gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch(
            instance,
            repair_start_trade_date=REPAIR_START_DATE,
            repair_end_trade_date=TRADE_DATE,
            upstream_batch_id=UPSTREAM_BATCH_ID,
            repair_required_code_count=len(REPAIR_CODES),
            repair_required_codes_hash=REPAIR_CODES_HASH,
        )

        self.assertTrue(status.ready)
        self.assertEqual(status.source_upstream_batch_id, UPSTREAM_BATCH_ID)

    def test_legacy_bridge_keeps_old_event_storage_id_comparison(self):
        ready_instance = _FakeInstance(
            _macd_kdj_records(
                storage_start=200,
                metadata=_legacy_macd_kdj_metadata(),
            )
        )
        stale_instance = _FakeInstance(
            _macd_kdj_records(
                storage_start=50,
                metadata=_legacy_macd_kdj_metadata(),
            )
        )

        ready_status = (
            legacy_gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_qfq_event_storage_ids(
                ready_instance,
                repair_start_trade_date=REPAIR_START_DATE,
                repair_end_trade_date=TRADE_DATE,
                qfq_factor_repair_event_storage_ids=QFQ_EVENT_STORAGE_IDS,
                repair_required_code_count=len(REPAIR_CODES),
                repair_required_codes_hash=REPAIR_CODES_HASH,
            )
        )
        stale_status = (
            legacy_gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_qfq_event_storage_ids(
                stale_instance,
                repair_start_trade_date=REPAIR_START_DATE,
                repair_end_trade_date=TRADE_DATE,
                qfq_factor_repair_event_storage_ids=QFQ_EVENT_STORAGE_IDS,
                repair_required_code_count=len(REPAIR_CODES),
                repair_required_codes_hash=REPAIR_CODES_HASH,
            )
        )

        self.assertTrue(ready_status.ready)
        self.assertEqual(
            ready_status.legacy_source_qfq_factor_repair_event_storage_ids,
            QFQ_EVENT_STORAGE_IDS,
        )
        self.assertFalse(stale_status.ready)


if __name__ == "__main__":
    unittest.main()
