from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    asset_check_record_evaluation,
    asset_check_record_event_storage_id,
    asset_check_record_metadata,
    asset_check_record_partition,
    asset_check_record_succeeded,
    latest_partition_check_records,
    metadata_has_keys,
    metadata_int,
    metadata_str,
)
from orchestrator.defs.stock_daily_trend_channel import FORMULA_VERSION

RESULT_ASSET_KEY = dg.AssetKey("gold_stock_daily_trend_channel")
STATE_ASSET_KEY = dg.AssetKey("gold_stock_daily_trend_channel_state")
RESULT_REPAIR_COMPLETION_CHECK_NAME = (
    "gold_stock_daily_trend_channel_factor_repair_completion_check"
)
STATE_REPAIR_COMPLETION_CHECK_NAME = (
    "gold_stock_daily_trend_channel_state_factor_repair_completion_check"
)

_REQUIRED_METADATA_KEYS = (
    "qfq_factor_repair_trade_date",
    "repair_start_trade_date",
    "repair_end_trade_date",
    "covered_start_trade_date",
    "covered_end_trade_date",
    "selected_partition_count",
    "repair_required_code_count",
    "repair_required_codes_hash",
    "source_upstream_batch_id",
    "formula_version",
    "rewritten_partition_count",
    "rewritten_indicator_partition_count",
    "rewritten_result_partition_count",
    "rewritten_state_partition_count",
    "rewritten_indicator_row_count",
    "rewritten_result_row_count",
    "rewritten_state_row_count",
    "producer_run_id",
)


@dataclass(frozen=True)
class StockDailyTrendChannelRepairCompletionStatus:
    ready: bool
    reason: str
    event_storage_ids: tuple[int, ...] = ()
    qfq_factor_repair_trade_date: str | None = None
    repair_start_trade_date: str | None = None
    repair_end_trade_date: str | None = None
    selected_partition_count: int = 0
    repair_required_code_count: int = 0
    repair_required_codes_hash: str | None = None
    source_upstream_batch_id: str | None = None
    formula_version: str | None = None
    rewritten_result_row_count: int = 0
    rewritten_state_row_count: int = 0

    def to_payload(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "reason": self.reason,
            "event_storage_ids": list(self.event_storage_ids),
            "qfq_factor_repair_trade_date": self.qfq_factor_repair_trade_date,
            "repair_start_trade_date": self.repair_start_trade_date,
            "repair_end_trade_date": self.repair_end_trade_date,
            "selected_partition_count": self.selected_partition_count,
            "repair_required_code_count": self.repair_required_code_count,
            "repair_required_codes_hash": self.repair_required_codes_hash,
            "source_upstream_batch_id": self.source_upstream_batch_id,
            "formula_version": self.formula_version,
            "rewritten_result_row_count": self.rewritten_result_row_count,
            "rewritten_state_row_count": self.rewritten_state_row_count,
        }


def gold_stock_daily_trend_channel_repair_completion_status(
    instance: dg.DagsterInstance,
    *,
    qfq_factor_repair_trade_date: str,
    repair_start_trade_date: str,
    repair_end_trade_date: str,
    selected_partition_count: int,
    repair_required_code_count: int,
    repair_required_codes_hash: str,
    source_upstream_batch_id: str,
    formula_version: str = FORMULA_VERSION,
) -> StockDailyTrendChannelRepairCompletionStatus:
    expected = {
        "qfq_factor_repair_trade_date": qfq_factor_repair_trade_date,
        "repair_start_trade_date": repair_start_trade_date,
        "repair_end_trade_date": repair_end_trade_date,
        "covered_start_trade_date": repair_start_trade_date,
        "covered_end_trade_date": repair_end_trade_date,
        "selected_partition_count": selected_partition_count,
        "repair_required_code_count": repair_required_code_count,
        "repair_required_codes_hash": repair_required_codes_hash,
        "source_upstream_batch_id": source_upstream_batch_id,
        "formula_version": formula_version,
        "rewritten_partition_count": selected_partition_count,
        "rewritten_indicator_partition_count": selected_partition_count,
        "rewritten_result_partition_count": selected_partition_count,
        "rewritten_state_partition_count": selected_partition_count,
    }
    check_specs = (
        (RESULT_ASSET_KEY, RESULT_REPAIR_COMPLETION_CHECK_NAME),
        (STATE_ASSET_KEY, STATE_REPAIR_COMPLETION_CHECK_NAME),
    )
    metadata_rows: list[Mapping[str, object]] = []
    event_storage_ids: list[int] = []
    for asset_key, check_name in check_specs:
        check_key = dg.AssetCheckKey(asset_key, check_name)
        records = latest_partition_check_records(
            instance,
            (asset_key,),
            check_name,
            partition_key=qfq_factor_repair_trade_date,
        )
        record = records.get(check_key)
        if record is None:
            return StockDailyTrendChannelRepairCompletionStatus(
                ready=False,
                reason="trend-channel repair completion check is missing.",
                event_storage_ids=tuple(sorted(event_storage_ids)),
            )
        evaluation = asset_check_record_evaluation(record)
        metadata = asset_check_record_metadata(evaluation)
        if (
            not asset_check_record_succeeded(record)
            or getattr(evaluation, "passed", None) is not True
            or getattr(evaluation, "blocking", None) is not True
            or asset_check_record_partition(record, evaluation)
            != qfq_factor_repair_trade_date
            or not metadata_has_keys(metadata, _REQUIRED_METADATA_KEYS)
        ):
            return StockDailyTrendChannelRepairCompletionStatus(
                ready=False,
                reason="trend-channel repair completion check is not green.",
                event_storage_ids=tuple(sorted(event_storage_ids)),
            )
        storage_id = asset_check_record_event_storage_id(
            instance,
            check_key,
            record,
            partition_key=qfq_factor_repair_trade_date,
        )
        if storage_id is not None:
            event_storage_ids.append(storage_id)
        metadata_rows.append(metadata)

    parsed_rows = tuple(_completion_metadata_values(row) for row in metadata_rows)
    if any(row is None for row in parsed_rows):
        return StockDailyTrendChannelRepairCompletionStatus(
            ready=False,
            reason="trend-channel repair completion metadata is incomplete.",
            event_storage_ids=tuple(sorted(event_storage_ids)),
        )
    first = parsed_rows[0]
    second = parsed_rows[1]
    assert first is not None and second is not None
    if first != second or any(
        first.get(key) != value for key, value in expected.items()
    ):
        return StockDailyTrendChannelRepairCompletionStatus(
            ready=False,
            reason=(
                "trend-channel repair completion metadata does not match the exact "
                "qfq repair scope."
            ),
            event_storage_ids=tuple(sorted(event_storage_ids)),
        )
    if (
        int(first["rewritten_indicator_row_count"])
        != int(first["rewritten_result_row_count"])
        or int(first["rewritten_result_row_count"]) < 0
        or int(first["rewritten_state_row_count"]) < 0
    ):
        return StockDailyTrendChannelRepairCompletionStatus(
            ready=False,
            reason="trend-channel repair completion row counts are invalid.",
            event_storage_ids=tuple(sorted(event_storage_ids)),
        )
    return StockDailyTrendChannelRepairCompletionStatus(
        ready=True,
        reason="trend-channel repair completion checks match the exact qfq batch.",
        event_storage_ids=tuple(sorted(event_storage_ids)),
        qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
        repair_start_trade_date=repair_start_trade_date,
        repair_end_trade_date=repair_end_trade_date,
        selected_partition_count=selected_partition_count,
        repair_required_code_count=repair_required_code_count,
        repair_required_codes_hash=repair_required_codes_hash,
        source_upstream_batch_id=source_upstream_batch_id,
        formula_version=formula_version,
        rewritten_result_row_count=int(first["rewritten_result_row_count"]),
        rewritten_state_row_count=int(first["rewritten_state_row_count"]),
    )


def _completion_metadata_values(
    metadata: Mapping[str, object],
) -> dict[str, object] | None:
    values: dict[str, object] = {}
    string_keys = (
        "qfq_factor_repair_trade_date",
        "repair_start_trade_date",
        "repair_end_trade_date",
        "covered_start_trade_date",
        "covered_end_trade_date",
        "repair_required_codes_hash",
        "source_upstream_batch_id",
        "formula_version",
        "producer_run_id",
    )
    integer_keys = (
        "selected_partition_count",
        "repair_required_code_count",
        "rewritten_partition_count",
        "rewritten_indicator_partition_count",
        "rewritten_result_partition_count",
        "rewritten_state_partition_count",
        "rewritten_indicator_row_count",
        "rewritten_result_row_count",
        "rewritten_state_row_count",
    )
    for key in string_keys:
        value = metadata_str(metadata, key)
        if value is None:
            return None
        values[key] = value
    for key in integer_keys:
        value = metadata_int(metadata, key)
        if value is None:
            return None
        values[key] = value
    return values
