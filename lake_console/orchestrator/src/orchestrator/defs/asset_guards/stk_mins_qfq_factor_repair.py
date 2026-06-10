from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import dagster as dg
from dagster._core.event_api import PartitionKeyFilter
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_FREQS
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
    QFQ_FACTOR_REPAIR_AUTO_MACD_KDJ_CODE_LIMIT,
)


_QFQ_FACTOR_REPAIR_REWRITE_KEYS = (
    "repair_required",
    "rewritten_file_count",
    "rewritten_row_count",
    "derived_rewrite_required",
    "derived_rewritten_file_count",
    "derived_rewritten_row_count",
)
_QFQ_FACTOR_REPAIR_REQUIRED_METADATA_KEYS = (
    "repair_required",
    "repair_required_code_count",
    "repair_required_codes",
    "repair_required_codes_hash",
    "repair_required_codes_truncated",
    "repair_start_trade_date",
    "repair_end_trade_date",
    "selected_partition_count",
) + _QFQ_FACTOR_REPAIR_REWRITE_KEYS[1:]


@dataclass(frozen=True)
class GoldStkMinsQfqFactorRepairStatus:
    ready: bool
    trade_date: str
    reason: str
    repair_required: bool = False
    qfq_factor_repair_event_storage_ids: tuple[int, ...] = ()
    missing_qfq_asset_keys: tuple[str, ...] = ()
    failed_qfq_asset_keys: tuple[str, ...] = ()
    repair_start_trade_date: str | None = None
    repair_end_trade_date: str | None = None
    selected_partition_count: int = 0
    repair_required_code_count: int = 0
    repair_required_codes: tuple[str, ...] = ()
    repair_required_codes_hash: str | None = None
    repair_required_codes_truncated: bool = False
    rewritten_file_count: int = 0
    rewritten_row_count: int = 0
    derived_rewrite_required: bool = False
    derived_rewritten_file_count: int = 0
    derived_rewritten_row_count: int = 0

    @property
    def rewrote_history(self) -> bool:
        return self.repair_required and (
            self.rewritten_file_count > 0
            or self.rewritten_row_count > 0
            or self.derived_rewrite_required
            or self.derived_rewritten_file_count > 0
            or self.derived_rewritten_row_count > 0
        )

    @property
    def requires_derived_reconciliation(self) -> bool:
        return self.repair_required and (
            self.derived_rewrite_required
            or self.derived_rewritten_file_count > 0
            or self.derived_rewritten_row_count > 0
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "trade_date": self.trade_date,
            "reason": self.reason,
            "repair_required": self.repair_required,
            "rewrote_history": self.rewrote_history,
            "qfq_factor_repair_event_storage_ids": list(
                self.qfq_factor_repair_event_storage_ids
            ),
            "missing_qfq_asset_keys": list(self.missing_qfq_asset_keys),
            "failed_qfq_asset_keys": list(self.failed_qfq_asset_keys),
            "repair_start_trade_date": self.repair_start_trade_date,
            "repair_end_trade_date": self.repair_end_trade_date,
            "selected_partition_count": self.selected_partition_count,
            "repair_required_code_count": self.repair_required_code_count,
            "repair_required_codes": list(self.repair_required_codes),
            "repair_required_codes_hash": self.repair_required_codes_hash,
            "repair_required_codes_truncated": self.repair_required_codes_truncated,
            "rewritten_file_count": self.rewritten_file_count,
            "rewritten_row_count": self.rewritten_row_count,
            "derived_rewrite_required": self.derived_rewrite_required,
            "derived_rewritten_file_count": self.derived_rewritten_file_count,
            "derived_rewritten_row_count": self.derived_rewritten_row_count,
            "requires_derived_reconciliation": self.requires_derived_reconciliation,
        }


def gold_stk_mins_qfq_factor_repair_status(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> GoldStkMinsQfqFactorRepairStatus:
    normalized_trade_date = str(trade_date).strip()
    qfq_asset_keys = gold_stk_mins_qfq_factor_repair_asset_keys()
    qfq_check_records = latest_partition_check_records(
        instance,
        qfq_asset_keys,
        GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
        partition_key=normalized_trade_date,
    )
    return _evaluate_qfq_factor_repair_records(
        qfq_asset_keys,
        qfq_check_records,
        trade_date=normalized_trade_date,
    )


def gold_stk_mins_qfq_factor_repair_event_storage_ids_identity(
    event_storage_ids: Sequence[int],
) -> str:
    return ",".join(str(event_id) for event_id in sorted(event_storage_ids))


def gold_stk_mins_qfq_factor_repair_asset_keys() -> tuple[dg.AssetKey, ...]:
    return tuple(dg.AssetKey(f"gold_stk_mins_qfq_{freq}m") for freq in STK_MINS_QFQ_FREQS)


def latest_partition_check_records(
    instance: dg.DagsterInstance,
    asset_keys: Sequence[dg.AssetKey],
    check_name: str,
    *,
    partition_key: str,
) -> Mapping[dg.AssetCheckKey, object]:
    check_keys = tuple(
        dg.AssetCheckKey(asset_key, check_name) for asset_key in asset_keys
    )
    return instance.event_log_storage.get_latest_asset_check_execution_by_key(
        check_keys,
        partition_filter=PartitionKeyFilter(key=partition_key),
    )


def asset_check_record_succeeded(record: object) -> bool:
    status = getattr(record, "status", None)
    return status == AssetCheckExecutionRecordStatus.SUCCEEDED or status == "SUCCEEDED"


def asset_check_record_event(record: object) -> object | None:
    return getattr(record, "event", None) or getattr(record, "event_log_entry", None)


def asset_check_record_evaluation(record: object) -> object:
    event = asset_check_record_event(record)
    dagster_event = getattr(event, "dagster_event", None)
    evaluation = getattr(dagster_event, "event_specific_data", None)
    return evaluation if evaluation is not None else object()


def asset_check_record_partition(record: object, evaluation: object) -> str | None:
    partition = getattr(record, "partition", None)
    return partition if partition is not None else getattr(evaluation, "partition", None)


def asset_check_record_storage_id(record: object) -> int | None:
    candidates = (
        getattr(record, "storage_id", None),
        getattr(record, "id", None),
        getattr(asset_check_record_event(record), "storage_id", None),
    )
    for candidate in candidates:
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


def asset_check_record_metadata(evaluation: object) -> dict[str, object]:
    raw_metadata = getattr(evaluation, "metadata", None)
    if not isinstance(raw_metadata, Mapping):
        return {}
    return {
        str(key): unwrap_metadata_value(value)
        for key, value in raw_metadata.items()
    }


def unwrap_metadata_value(value: object) -> object:
    if hasattr(value, "value"):
        return getattr(value, "value")
    if hasattr(value, "data"):
        return getattr(value, "data")
    text_value = getattr(value, "text", None)
    if isinstance(text_value, str):
        return text_value
    return value


def metadata_value(metadata: Mapping[str, object], key: str) -> object | None:
    return metadata.get(f"goldenshare/{key}", metadata.get(key))


def metadata_has_keys(metadata: Mapping[str, object], keys: Sequence[str]) -> bool:
    return all(metadata_value(metadata, key) is not None for key in keys)


def metadata_bool(metadata: Mapping[str, object], key: str) -> bool | None:
    value = metadata_value(metadata, key)
    return value if isinstance(value, bool) else None


def metadata_int(metadata: Mapping[str, object], key: str) -> int | None:
    value = metadata_value(metadata, key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def metadata_str(metadata: Mapping[str, object], key: str) -> str | None:
    value = metadata_value(metadata, key)
    return value if isinstance(value, str) and value else None


def metadata_int_tuple(metadata: Mapping[str, object], key: str) -> tuple[int, ...]:
    value = metadata_value(metadata, key)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    int_values = []
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool):
            return ()
        int_values.append(item)
    return tuple(sorted(int_values))


def metadata_str_tuple(metadata: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = metadata_value(metadata, key)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    str_values = []
    for item in value:
        if not isinstance(item, str) or not item:
            return ()
        str_values.append(item)
    return tuple(sorted(str_values))


def _evaluate_qfq_factor_repair_records(
    asset_keys: Sequence[dg.AssetKey],
    records_by_key: Mapping[dg.AssetCheckKey, object],
    *,
    trade_date: str,
) -> GoldStkMinsQfqFactorRepairStatus:
    missing: list[str] = []
    failed: list[str] = []
    event_storage_ids: list[int] = []
    metadata_rows: list[dict[str, object]] = []

    for asset_key in asset_keys:
        check_key = dg.AssetCheckKey(
            asset_key,
            GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
        )
        record = records_by_key.get(check_key)
        asset_label = asset_key.to_user_string()
        if record is None:
            missing.append(asset_label)
            continue
        evaluation = asset_check_record_evaluation(record)
        storage_id = asset_check_record_storage_id(record)
        metadata = asset_check_record_metadata(evaluation)
        if (
            storage_id is None
            or not asset_check_record_succeeded(record)
            or getattr(evaluation, "passed", None) is not True
            or getattr(evaluation, "blocking", None) is not True
            or asset_check_record_partition(record, evaluation) != trade_date
            or not metadata_has_keys(metadata, _QFQ_FACTOR_REPAIR_REQUIRED_METADATA_KEYS)
        ):
            failed.append(asset_label)
            continue
        event_storage_ids.append(storage_id)
        metadata_rows.append(metadata)

    if missing or failed:
        return GoldStkMinsQfqFactorRepairStatus(
            ready=False,
            trade_date=trade_date,
            reason="qfq factor repair check is missing or not green for the target date.",
            missing_qfq_asset_keys=tuple(missing),
            failed_qfq_asset_keys=tuple(failed),
            qfq_factor_repair_event_storage_ids=tuple(sorted(event_storage_ids)),
        )

    first_metadata = metadata_rows[0]
    repair_start_trade_date = metadata_str(first_metadata, "repair_start_trade_date")
    repair_end_trade_date = metadata_str(first_metadata, "repair_end_trade_date")
    selected_partition_count = metadata_int(first_metadata, "selected_partition_count")
    repair_required_code_count = metadata_int(
        first_metadata,
        "repair_required_code_count",
    )
    repair_required_codes = metadata_str_tuple(
        first_metadata,
        "repair_required_codes",
    )
    repair_required_codes_hash = metadata_str(
        first_metadata,
        "repair_required_codes_hash",
    )
    repair_required_codes_truncated = metadata_bool(
        first_metadata,
        "repair_required_codes_truncated",
    )
    if (
        repair_start_trade_date is None
        or repair_end_trade_date is None
        or selected_partition_count is None
        or repair_required_code_count is None
        or repair_required_codes_hash is None
        or repair_required_codes_truncated is None
    ):
        return GoldStkMinsQfqFactorRepairStatus(
            ready=False,
            trade_date=trade_date,
            reason="qfq factor repair metadata is incomplete.",
            failed_qfq_asset_keys=tuple(asset_key.to_user_string() for asset_key in asset_keys),
            qfq_factor_repair_event_storage_ids=tuple(sorted(event_storage_ids)),
        )
    if not _qfq_repair_scope_metadata_is_consistent(
        metadata_rows,
        repair_required_code_count=repair_required_code_count,
        repair_required_codes=repair_required_codes,
        repair_required_codes_hash=repair_required_codes_hash,
        repair_required_codes_truncated=repair_required_codes_truncated,
    ):
        return GoldStkMinsQfqFactorRepairStatus(
            ready=False,
            trade_date=trade_date,
            reason="qfq factor repair code scope metadata is inconsistent.",
            failed_qfq_asset_keys=tuple(asset_key.to_user_string() for asset_key in asset_keys),
            qfq_factor_repair_event_storage_ids=tuple(sorted(event_storage_ids)),
        )

    rewrite_metadata = _build_qfq_factor_repair_rewrite_metadata(metadata_rows)
    return GoldStkMinsQfqFactorRepairStatus(
        ready=True,
        trade_date=trade_date,
        reason=(
            "qfq factor repair is ready and did not rewrite history."
            if not rewrite_metadata["rewrote_history"]
            else "qfq factor repair rewrote history; reconciliation is required."
        ),
        repair_required=bool(rewrite_metadata["repair_required"]),
        qfq_factor_repair_event_storage_ids=tuple(sorted(event_storage_ids)),
        repair_start_trade_date=repair_start_trade_date,
        repair_end_trade_date=repair_end_trade_date,
        selected_partition_count=selected_partition_count,
        repair_required_code_count=repair_required_code_count,
        repair_required_codes=repair_required_codes,
        repair_required_codes_hash=repair_required_codes_hash,
        repair_required_codes_truncated=repair_required_codes_truncated,
        rewritten_file_count=int(rewrite_metadata["rewritten_file_count"]),
        rewritten_row_count=int(rewrite_metadata["rewritten_row_count"]),
        derived_rewrite_required=bool(rewrite_metadata["derived_rewrite_required"]),
        derived_rewritten_file_count=int(
            rewrite_metadata["derived_rewritten_file_count"]
        ),
        derived_rewritten_row_count=int(rewrite_metadata["derived_rewritten_row_count"]),
    )


def _build_qfq_factor_repair_rewrite_metadata(
    metadata_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    repair_required = any(metadata_bool(row, "repair_required") is True for row in metadata_rows)
    rewritten_file_count = max(metadata_int(row, "rewritten_file_count") or 0 for row in metadata_rows)
    rewritten_row_count = max(metadata_int(row, "rewritten_row_count") or 0 for row in metadata_rows)
    derived_rewrite_required = any(
        metadata_bool(row, "derived_rewrite_required") is True for row in metadata_rows
    )
    derived_rewritten_file_count = max(
        metadata_int(row, "derived_rewritten_file_count") or 0 for row in metadata_rows
    )
    derived_rewritten_row_count = max(
        metadata_int(row, "derived_rewritten_row_count") or 0 for row in metadata_rows
    )
    rewrote_history = repair_required and (
        rewritten_file_count > 0
        or rewritten_row_count > 0
        or derived_rewrite_required
        or derived_rewritten_file_count > 0
        or derived_rewritten_row_count > 0
    )
    return {
        "repair_required": repair_required,
        "rewritten_file_count": rewritten_file_count,
        "rewritten_row_count": rewritten_row_count,
        "derived_rewrite_required": derived_rewrite_required,
        "derived_rewritten_file_count": derived_rewritten_file_count,
        "derived_rewritten_row_count": derived_rewritten_row_count,
        "rewrote_history": rewrote_history,
    }


def _qfq_repair_scope_metadata_is_consistent(
    metadata_rows: Sequence[Mapping[str, object]],
    *,
    repair_required_code_count: int,
    repair_required_codes: tuple[str, ...],
    repair_required_codes_hash: str,
    repair_required_codes_truncated: bool,
) -> bool:
    if repair_required_code_count < 0:
        return False
    if repair_required_code_count <= QFQ_FACTOR_REPAIR_AUTO_MACD_KDJ_CODE_LIMIT:
        if repair_required_codes_truncated:
            return False
        if len(repair_required_codes) != repair_required_code_count:
            return False
    elif not repair_required_codes_truncated:
        return False

    for metadata in metadata_rows:
        if metadata_int(metadata, "repair_required_code_count") != repair_required_code_count:
            return False
        if metadata_str(metadata, "repair_required_codes_hash") != repair_required_codes_hash:
            return False
        if (
            metadata_bool(metadata, "repair_required_codes_truncated")
            != repair_required_codes_truncated
        ):
            return False
        if metadata_str_tuple(metadata, "repair_required_codes") != repair_required_codes:
            return False
    return True
