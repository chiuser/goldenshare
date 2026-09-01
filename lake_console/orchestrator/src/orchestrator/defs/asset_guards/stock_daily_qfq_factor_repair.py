from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    asset_check_record_evaluation,
    asset_check_record_metadata,
    asset_check_record_partition,
    asset_check_record_succeeded,
    latest_partition_check_records,
    metadata_bool,
    metadata_has_keys,
    metadata_int,
    metadata_str,
    metadata_value,
)
from orchestrator.defs.stock_daily_qfq import (
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_AUTO_CODE_LIMIT,
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_METADATA_SAMPLE_LIMIT,
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
    gold_stock_daily_qfq_factor_repair_codes_hash,
)


_REQUIRED_METADATA_KEYS = (
    "qfq_factor_trade_date",
    "repair_end_trade_date",
    "selected_partition_count",
    "repair_required",
    "repair_required_code_count",
    "repair_required_codes",
    "repair_required_code_samples",
    "repair_required_codes_hash",
    "repair_required_codes_truncated",
    "upstream_batch_id",
    "producer_run_id",
    "rewritten_partition_count",
    "rewritten_row_count",
)


@dataclass(frozen=True)
class GoldStockDailyQfqFactorRepairStatus:
    ready: bool
    trade_date: str
    reason: str
    repair_required: bool = False
    producer_run_id: str | None = None
    upstream_batch_id: str | None = None
    repair_start_trade_date: str | None = None
    repair_end_trade_date: str | None = None
    selected_partition_count: int = 0
    repair_required_code_count: int = 0
    repair_required_codes: tuple[str, ...] = ()
    repair_required_code_samples: tuple[str, ...] = ()
    repair_required_codes_hash: str | None = None
    repair_required_codes_truncated: bool = False
    rewritten_partition_count: int = 0
    rewritten_row_count: int = 0

    @property
    def rewrote_history(self) -> bool:
        return self.repair_required and (
            self.rewritten_partition_count > 0 or self.rewritten_row_count > 0
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "trade_date": self.trade_date,
            "reason": self.reason,
            "repair_required": self.repair_required,
            "rewrote_history": self.rewrote_history,
            "producer_run_id": self.producer_run_id,
            "upstream_batch_id": self.upstream_batch_id,
            "repair_start_trade_date": self.repair_start_trade_date,
            "repair_end_trade_date": self.repair_end_trade_date,
            "selected_partition_count": self.selected_partition_count,
            "repair_required_code_count": self.repair_required_code_count,
            "repair_required_codes": list(self.repair_required_codes),
            "repair_required_code_samples": list(self.repair_required_code_samples),
            "repair_required_codes_hash": self.repair_required_codes_hash,
            "repair_required_codes_truncated": self.repair_required_codes_truncated,
            "rewritten_partition_count": self.rewritten_partition_count,
            "rewritten_row_count": self.rewritten_row_count,
        }


def gold_stock_daily_qfq_factor_repair_status(
    instance: dg.DagsterInstance,
    trade_date: str,
    *,
    upstream_batch_id: str | None = None,
) -> GoldStockDailyQfqFactorRepairStatus:
    normalized_trade_date = str(trade_date).strip()
    asset_key = dg.AssetKey("gold_stock_daily_qfq")
    check_key = dg.AssetCheckKey(
        asset_key,
        GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
    )
    records = latest_partition_check_records(
        instance,
        (asset_key,),
        GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
        partition_key=normalized_trade_date,
    )
    record = records.get(check_key)
    if record is None:
        return GoldStockDailyQfqFactorRepairStatus(
            ready=False,
            trade_date=normalized_trade_date,
            reason="stock daily qfq factor repair check is missing for target date.",
        )
    evaluation = asset_check_record_evaluation(record)
    metadata = asset_check_record_metadata(evaluation)
    if (
        not asset_check_record_succeeded(record)
        or getattr(evaluation, "passed", None) is not True
        or getattr(evaluation, "blocking", None) is not True
        or asset_check_record_partition(record, evaluation) != normalized_trade_date
        or not metadata_has_keys(metadata, _REQUIRED_METADATA_KEYS)
    ):
        return GoldStockDailyQfqFactorRepairStatus(
            ready=False,
            trade_date=normalized_trade_date,
            reason="stock daily qfq factor repair check is missing or not green.",
        )

    status = _status_from_metadata(normalized_trade_date, metadata)
    if upstream_batch_id is not None and status.upstream_batch_id != upstream_batch_id:
        return GoldStockDailyQfqFactorRepairStatus(
            ready=False,
            trade_date=normalized_trade_date,
            reason="stock daily qfq factor repair status belongs to a different upstream batch.",
        )
    return status


def _status_from_metadata(
    trade_date: str,
    metadata: Mapping[str, object],
) -> GoldStockDailyQfqFactorRepairStatus:
    producer_run_id = metadata_str(metadata, "producer_run_id")
    upstream_batch_id = metadata_str(metadata, "upstream_batch_id")
    repair_start_trade_date = metadata_str(metadata, "repair_start_trade_date")
    repair_end_trade_date = metadata_str(metadata, "repair_end_trade_date")
    selected_partition_count = metadata_int(metadata, "selected_partition_count")
    repair_required = metadata_bool(metadata, "repair_required")
    repair_required_code_count = metadata_int(metadata, "repair_required_code_count")
    repair_required_codes = _metadata_ordered_str_tuple(
        metadata,
        "repair_required_codes",
    )
    repair_required_code_samples = _metadata_ordered_str_tuple(
        metadata,
        "repair_required_code_samples",
    )
    repair_required_codes_hash = metadata_str(metadata, "repair_required_codes_hash")
    repair_required_codes_truncated = metadata_bool(
        metadata,
        "repair_required_codes_truncated",
    )
    rewritten_partition_count = metadata_int(metadata, "rewritten_partition_count")
    rewritten_row_count = metadata_int(metadata, "rewritten_row_count")
    if (
        producer_run_id is None
        or upstream_batch_id is None
        or repair_end_trade_date is None
        or selected_partition_count is None
        or repair_required is None
        or repair_required_code_count is None
        or repair_required_codes is None
        or repair_required_code_samples is None
        or repair_required_codes_hash is None
        or repair_required_codes_truncated is None
        or rewritten_partition_count is None
        or rewritten_row_count is None
    ):
        return GoldStockDailyQfqFactorRepairStatus(
            ready=False,
            trade_date=trade_date,
            reason="stock daily qfq factor repair metadata is incomplete.",
        )
    if repair_required and repair_start_trade_date is None:
        return GoldStockDailyQfqFactorRepairStatus(
            ready=False,
            trade_date=trade_date,
            reason="stock daily qfq factor repair metadata is missing repair start date.",
        )
    if not _code_scope_is_consistent(
        repair_required=repair_required,
        repair_required_code_count=repair_required_code_count,
        repair_required_codes=repair_required_codes,
        repair_required_code_samples=repair_required_code_samples,
        repair_required_codes_hash=repair_required_codes_hash,
        repair_required_codes_truncated=repair_required_codes_truncated,
    ):
        return GoldStockDailyQfqFactorRepairStatus(
            ready=False,
            trade_date=trade_date,
            reason="stock daily qfq factor repair code scope metadata is inconsistent.",
        )
    if not repair_required and (
        selected_partition_count != 0
        or rewritten_partition_count != 0
        or rewritten_row_count != 0
    ):
        return GoldStockDailyQfqFactorRepairStatus(
            ready=False,
            trade_date=trade_date,
            reason="stock daily qfq no-op reconciliation metadata is inconsistent.",
        )
    if (
        min(
            selected_partition_count,
            rewritten_partition_count,
            rewritten_row_count,
        )
        < 0
    ):
        return GoldStockDailyQfqFactorRepairStatus(
            ready=False,
            trade_date=trade_date,
            reason="stock daily qfq factor repair count metadata is inconsistent.",
        )
    return GoldStockDailyQfqFactorRepairStatus(
        ready=True,
        trade_date=trade_date,
        reason="stock daily qfq factor repair status is ready.",
        repair_required=repair_required,
        producer_run_id=producer_run_id,
        upstream_batch_id=upstream_batch_id,
        repair_start_trade_date=repair_start_trade_date,
        repair_end_trade_date=repair_end_trade_date,
        selected_partition_count=selected_partition_count,
        repair_required_code_count=repair_required_code_count,
        repair_required_codes=repair_required_codes,
        repair_required_code_samples=repair_required_code_samples,
        repair_required_codes_hash=repair_required_codes_hash,
        repair_required_codes_truncated=repair_required_codes_truncated,
        rewritten_partition_count=rewritten_partition_count,
        rewritten_row_count=rewritten_row_count,
    )


def _code_scope_is_consistent(
    *,
    repair_required: bool,
    repair_required_code_count: int,
    repair_required_codes: Sequence[str],
    repair_required_code_samples: Sequence[str],
    repair_required_codes_hash: str,
    repair_required_codes_truncated: bool,
) -> bool:
    if repair_required_code_count < 0:
        return False
    if repair_required != (repair_required_code_count > 0):
        return False
    if repair_required_code_count > GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_AUTO_CODE_LIMIT:
        return False

    codes = tuple(repair_required_codes)
    samples = tuple(repair_required_code_samples)
    if repair_required_codes_truncated:
        return False
    normalized_codes = tuple(
        sorted({code.strip().upper() for code in codes if code.strip()})
    )
    if codes != normalized_codes:
        return False
    if len(codes) != repair_required_code_count:
        return False
    if samples != codes[:GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_METADATA_SAMPLE_LIMIT]:
        return False
    return (
        gold_stock_daily_qfq_factor_repair_codes_hash(codes)
        == repair_required_codes_hash
    )


def _metadata_ordered_str_tuple(
    metadata: Mapping[str, object],
    key: str,
) -> tuple[str, ...] | None:
    value = metadata_value(metadata, key)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            return None
        result.append(item)
    return tuple(result)
