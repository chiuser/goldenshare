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
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
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
_MACD_KDJ_REPAIR_COMPLETION_REQUIRED_METADATA_KEYS = (
    "covered_start_trade_date",
    "covered_end_trade_date",
    "freqs",
    "stock_code_scope",
    "stock_code_count",
    "repair_required_code_count",
    "repair_required_codes_hash",
    "source_qfq_factor_repair_event_storage_ids",
)


@dataclass(frozen=True)
class MacdKdjRepairCompletionGateStatus:
    ready: bool
    reason: str
    event_storage_ids: tuple[int, ...] = ()
    missing_asset_keys: tuple[str, ...] = ()
    failed_asset_keys: tuple[str, ...] = ()
    covered_start_trade_date: str | None = None
    covered_end_trade_date: str | None = None
    stock_code_scope: str | None = None
    stock_code_count: int = 0
    repair_required_code_count: int = 0
    repair_required_codes_hash: str | None = None
    source_qfq_factor_repair_event_storage_ids: tuple[int, ...] = ()
    freqs: tuple[int, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "reason": self.reason,
            "event_storage_ids": list(self.event_storage_ids),
            "missing_asset_keys": list(self.missing_asset_keys),
            "failed_asset_keys": list(self.failed_asset_keys),
            "covered_start_trade_date": self.covered_start_trade_date,
            "covered_end_trade_date": self.covered_end_trade_date,
            "stock_code_scope": self.stock_code_scope,
            "stock_code_count": self.stock_code_count,
            "repair_required_code_count": self.repair_required_code_count,
            "repair_required_codes_hash": self.repair_required_codes_hash,
            "source_qfq_factor_repair_event_storage_ids": list(
                self.source_qfq_factor_repair_event_storage_ids
            ),
            "freqs": list(self.freqs),
        }


@dataclass(frozen=True)
class GoldStkMinsQfqMacdKdjDailyRepairGateStatus:
    ready: bool
    trade_date: str
    reason: str
    requires_macd_kdj_repair: bool = False
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
    macd_kdj_repair_status: MacdKdjRepairCompletionGateStatus | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "trade_date": self.trade_date,
            "reason": self.reason,
            "requires_macd_kdj_repair": self.requires_macd_kdj_repair,
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
            "automatic_macd_kdj_repair_allowed": (
                self.automatic_macd_kdj_repair_allowed
            ),
            "macd_kdj_repair_status": (
                self.macd_kdj_repair_status.to_payload()
                if self.macd_kdj_repair_status is not None
                else None
            ),
        }

    @property
    def macd_kdj_repair_event_storage_ids(self) -> tuple[int, ...]:
        if self.macd_kdj_repair_status is None:
            return ()
        return self.macd_kdj_repair_status.event_storage_ids

    @property
    def automatic_macd_kdj_repair_allowed(self) -> bool:
        return (
            self.requires_macd_kdj_repair
            and 0
            < self.repair_required_code_count
            <= QFQ_FACTOR_REPAIR_AUTO_MACD_KDJ_CODE_LIMIT
            and not self.repair_required_codes_truncated
            and len(self.repair_required_codes) == self.repair_required_code_count
            and self.repair_required_codes_hash is not None
        )


def gold_stk_mins_qfq_macd_kdj_daily_repair_gate_status(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> GoldStkMinsQfqMacdKdjDailyRepairGateStatus:
    qfq_result = gold_stk_mins_qfq_macd_kdj_qfq_factor_repair_status(
        instance,
        trade_date,
    )
    if not qfq_result.ready:
        return qfq_result
    if not qfq_result.requires_macd_kdj_repair:
        return qfq_result

    macd_kdj_repair_status = (
        gold_stk_mins_qfq_macd_kdj_repair_completion_status(
            instance,
            qfq_factor_repair_status=qfq_result,
        )
    )
    if not macd_kdj_repair_status.ready:
        return GoldStkMinsQfqMacdKdjDailyRepairGateStatus(
            ready=False,
            trade_date=qfq_result.trade_date,
            reason=macd_kdj_repair_status.reason,
            requires_macd_kdj_repair=True,
            qfq_factor_repair_event_storage_ids=(
                qfq_result.qfq_factor_repair_event_storage_ids
            ),
            repair_start_trade_date=qfq_result.repair_start_trade_date,
            repair_end_trade_date=qfq_result.repair_end_trade_date,
            selected_partition_count=qfq_result.selected_partition_count,
            repair_required_code_count=qfq_result.repair_required_code_count,
            repair_required_codes=qfq_result.repair_required_codes,
            repair_required_codes_hash=qfq_result.repair_required_codes_hash,
            repair_required_codes_truncated=qfq_result.repair_required_codes_truncated,
            macd_kdj_repair_status=macd_kdj_repair_status,
        )
    return GoldStkMinsQfqMacdKdjDailyRepairGateStatus(
        ready=True,
        trade_date=qfq_result.trade_date,
        reason=(
            "qfq factor repair and required MACD/KDJ repair completion are ready."
        ),
        requires_macd_kdj_repair=True,
        qfq_factor_repair_event_storage_ids=(
            qfq_result.qfq_factor_repair_event_storage_ids
        ),
        repair_start_trade_date=qfq_result.repair_start_trade_date,
        repair_end_trade_date=qfq_result.repair_end_trade_date,
        selected_partition_count=qfq_result.selected_partition_count,
        repair_required_code_count=qfq_result.repair_required_code_count,
        repair_required_codes=qfq_result.repair_required_codes,
        repair_required_codes_hash=qfq_result.repair_required_codes_hash,
        repair_required_codes_truncated=qfq_result.repair_required_codes_truncated,
        macd_kdj_repair_status=macd_kdj_repair_status,
    )


def gold_stk_mins_qfq_macd_kdj_qfq_factor_repair_status(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> GoldStkMinsQfqMacdKdjDailyRepairGateStatus:
    normalized_trade_date = str(trade_date).strip()
    qfq_asset_keys = _qfq_asset_keys()
    qfq_check_records = _latest_check_records(
        instance,
        qfq_asset_keys,
        GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
        partition_key=normalized_trade_date,
    )
    qfq_result = _evaluate_qfq_factor_repair_records(
        qfq_asset_keys,
        qfq_check_records,
        trade_date=normalized_trade_date,
    )
    return qfq_result


def gold_stk_mins_qfq_macd_kdj_repair_completion_status(
    instance: dg.DagsterInstance,
    *,
    qfq_factor_repair_status: GoldStkMinsQfqMacdKdjDailyRepairGateStatus,
) -> MacdKdjRepairCompletionGateStatus:
    return _macd_kdj_repair_completion_status(
        instance,
        repair_start_trade_date=qfq_factor_repair_status.repair_start_trade_date,
        repair_end_trade_date=qfq_factor_repair_status.repair_end_trade_date,
        qfq_factor_repair_event_storage_ids=(
            qfq_factor_repair_status.qfq_factor_repair_event_storage_ids
        ),
        repair_required_code_count=qfq_factor_repair_status.repair_required_code_count,
        repair_required_codes_hash=qfq_factor_repair_status.repair_required_codes_hash,
    )


def assert_gold_stk_mins_qfq_macd_kdj_daily_repair_gate(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> None:
    status = gold_stk_mins_qfq_macd_kdj_qfq_factor_repair_status(
        instance,
        trade_date,
    )
    if status.ready:
        return
    raise dg.Failure(
        description=(
            "gold_stk_mins_qfq_macd_kdj daily asset cannot be produced because "
            "the qfq factor repair sequencing gate is not ready."
        ),
        metadata={
            "trade_date": trade_date,
            "repair_gate_reason": status.reason,
            "repair_gate_status": dg.MetadataValue.json(status.to_payload()),
        },
    )


def _event_storage_ids_identity(event_storage_ids: Sequence[int]) -> str:
    return ",".join(str(event_id) for event_id in sorted(event_storage_ids))


def gold_stk_mins_qfq_macd_kdj_repair_event_storage_ids_identity(
    event_storage_ids: Sequence[int],
) -> str:
    return _event_storage_ids_identity(event_storage_ids)


def _qfq_asset_keys() -> tuple[dg.AssetKey, ...]:
    return tuple(dg.AssetKey(f"gold_stk_mins_qfq_{freq}m") for freq in STK_MINS_QFQ_FREQS)


def _macd_kdj_asset_keys() -> tuple[dg.AssetKey, ...]:
    indicator_keys = tuple(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_{freq}m")
        for freq in STK_MINS_QFQ_FREQS
    )
    state_keys = tuple(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_state_{freq}m")
        for freq in STK_MINS_QFQ_FREQS
    )
    return indicator_keys + state_keys


def _latest_check_records(
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


def _evaluate_qfq_factor_repair_records(
    asset_keys: Sequence[dg.AssetKey],
    records_by_key: Mapping[dg.AssetCheckKey, object],
    *,
    trade_date: str,
) -> GoldStkMinsQfqMacdKdjDailyRepairGateStatus:
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
        evaluation = _record_evaluation(record)
        storage_id = _record_storage_id(record)
        metadata = _record_metadata(evaluation)
        if (
            storage_id is None
            or not _record_succeeded(record)
            or getattr(evaluation, "passed", None) is not True
            or getattr(evaluation, "blocking", None) is not True
            or _record_partition(record, evaluation) != trade_date
            or not _metadata_has_keys(metadata, _QFQ_FACTOR_REPAIR_REQUIRED_METADATA_KEYS)
        ):
            failed.append(asset_label)
            continue
        event_storage_ids.append(storage_id)
        metadata_rows.append(metadata)

    if missing or failed:
        return GoldStkMinsQfqMacdKdjDailyRepairGateStatus(
            ready=False,
            trade_date=trade_date,
            reason="qfq factor repair check is missing or not green for the target date.",
            missing_qfq_asset_keys=tuple(missing),
            failed_qfq_asset_keys=tuple(failed),
            qfq_factor_repair_event_storage_ids=tuple(sorted(event_storage_ids)),
        )

    first_metadata = metadata_rows[0]
    repair_start_trade_date = _metadata_str(first_metadata, "repair_start_trade_date")
    repair_end_trade_date = _metadata_str(first_metadata, "repair_end_trade_date")
    selected_partition_count = _metadata_int(first_metadata, "selected_partition_count")
    repair_required_code_count = _metadata_int(
        first_metadata,
        "repair_required_code_count",
    )
    repair_required_codes = _metadata_str_tuple(
        first_metadata,
        "repair_required_codes",
    )
    repair_required_codes_hash = _metadata_str(
        first_metadata,
        "repair_required_codes_hash",
    )
    repair_required_codes_truncated = _metadata_bool(
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
        return GoldStkMinsQfqMacdKdjDailyRepairGateStatus(
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
        return GoldStkMinsQfqMacdKdjDailyRepairGateStatus(
            ready=False,
            trade_date=trade_date,
            reason="qfq factor repair code scope metadata is inconsistent.",
            failed_qfq_asset_keys=tuple(asset_key.to_user_string() for asset_key in asset_keys),
            qfq_factor_repair_event_storage_ids=tuple(sorted(event_storage_ids)),
        )
    requires_macd_kdj_repair = any(
        _qfq_metadata_requires_macd_kdj_repair(row) for row in metadata_rows
    )
    return GoldStkMinsQfqMacdKdjDailyRepairGateStatus(
        ready=True,
        trade_date=trade_date,
        reason=(
            "qfq factor repair is ready and did not rewrite history."
            if not requires_macd_kdj_repair
            else (
                "qfq factor repair rewrote history; "
                "MACD/KDJ repair completion is required."
            )
        ),
        requires_macd_kdj_repair=requires_macd_kdj_repair,
        qfq_factor_repair_event_storage_ids=tuple(sorted(event_storage_ids)),
        repair_start_trade_date=repair_start_trade_date,
        repair_end_trade_date=repair_end_trade_date,
        selected_partition_count=selected_partition_count,
        repair_required_code_count=repair_required_code_count,
        repair_required_codes=repair_required_codes,
        repair_required_codes_hash=repair_required_codes_hash,
        repair_required_codes_truncated=repair_required_codes_truncated,
    )


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
        if _metadata_int(metadata, "repair_required_code_count") != repair_required_code_count:
            return False
        if _metadata_str(metadata, "repair_required_codes_hash") != repair_required_codes_hash:
            return False
        if (
            _metadata_bool(metadata, "repair_required_codes_truncated")
            != repair_required_codes_truncated
        ):
            return False
        if _metadata_str_tuple(metadata, "repair_required_codes") != repair_required_codes:
            return False
    return True


def _macd_kdj_repair_completion_status(
    instance: dg.DagsterInstance,
    *,
    repair_start_trade_date: str | None,
    repair_end_trade_date: str | None,
    qfq_factor_repair_event_storage_ids: Sequence[int],
    repair_required_code_count: int,
    repair_required_codes_hash: str | None,
) -> MacdKdjRepairCompletionGateStatus:
    if repair_start_trade_date is None or repair_end_trade_date is None:
        return MacdKdjRepairCompletionGateStatus(
            ready=False,
            reason="qfq factor repair scope metadata is incomplete.",
        )
    expected_source_event_storage_ids = tuple(
        sorted(int(event_id) for event_id in qfq_factor_repair_event_storage_ids)
    )
    records_by_key = _latest_check_records(
        instance,
        _macd_kdj_asset_keys(),
        GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
        partition_key=repair_start_trade_date,
    )
    missing: list[str] = []
    failed: list[str] = []
    event_storage_ids: list[int] = []
    metadata_rows: list[dict[str, object]] = []
    max_qfq_storage_id = max(qfq_factor_repair_event_storage_ids)

    for asset_key in _macd_kdj_asset_keys():
        check_key = dg.AssetCheckKey(
            asset_key,
            GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
        )
        record = records_by_key.get(check_key)
        asset_label = asset_key.to_user_string()
        if record is None:
            missing.append(asset_label)
            continue
        evaluation = _record_evaluation(record)
        storage_id = _record_storage_id(record)
        metadata = _record_metadata(evaluation)
        if (
            storage_id is None
            or storage_id <= max_qfq_storage_id
            or not _record_succeeded(record)
            or getattr(evaluation, "passed", None) is not True
            or getattr(evaluation, "blocking", None) is not True
            or _record_partition(record, evaluation) != repair_start_trade_date
            or not _metadata_has_keys(
                metadata,
                _MACD_KDJ_REPAIR_COMPLETION_REQUIRED_METADATA_KEYS,
            )
        ):
            failed.append(asset_label)
            continue
        event_storage_ids.append(storage_id)
        metadata_rows.append(metadata)

    if missing or failed:
        return MacdKdjRepairCompletionGateStatus(
            ready=False,
            reason="MACD/KDJ repair completion check is missing or not green.",
            event_storage_ids=tuple(sorted(event_storage_ids)),
            missing_asset_keys=tuple(missing),
            failed_asset_keys=tuple(failed),
        )

    first_metadata = metadata_rows[0]
    covered_start_trade_date = _metadata_str(
        first_metadata,
        "covered_start_trade_date",
    )
    covered_end_trade_date = _metadata_str(first_metadata, "covered_end_trade_date")
    stock_code_scope = _metadata_str(first_metadata, "stock_code_scope")
    stock_code_count = _metadata_int(first_metadata, "stock_code_count")
    completed_repair_required_code_count = _metadata_int(
        first_metadata,
        "repair_required_code_count",
    )
    completed_repair_required_codes_hash = _metadata_str(
        first_metadata,
        "repair_required_codes_hash",
    )
    source_qfq_factor_repair_event_storage_ids = _metadata_int_tuple(
        first_metadata,
        "source_qfq_factor_repair_event_storage_ids",
    )
    freqs = _metadata_int_tuple(first_metadata, "freqs")
    all_freqs = tuple(STK_MINS_QFQ_FREQS)
    if (
        covered_start_trade_date is None
        or covered_end_trade_date is None
        or stock_code_scope is None
        or stock_code_count is None
        or completed_repair_required_code_count is None
        or completed_repair_required_codes_hash is None
        or covered_start_trade_date > repair_start_trade_date
        or covered_end_trade_date < repair_end_trade_date
        or tuple(sorted(freqs)) != all_freqs
        or completed_repair_required_code_count != repair_required_code_count
        or completed_repair_required_codes_hash != repair_required_codes_hash
        or source_qfq_factor_repair_event_storage_ids
        != expected_source_event_storage_ids
        or stock_code_scope != "explicit"
        or stock_code_count < repair_required_code_count
    ):
        return MacdKdjRepairCompletionGateStatus(
            ready=False,
            reason=(
                "MACD/KDJ repair completion metadata does not cover qfq repair scope."
            ),
            event_storage_ids=tuple(sorted(event_storage_ids)),
            covered_start_trade_date=covered_start_trade_date,
            covered_end_trade_date=covered_end_trade_date,
            stock_code_scope=stock_code_scope,
            stock_code_count=stock_code_count or 0,
            repair_required_code_count=completed_repair_required_code_count or 0,
            repair_required_codes_hash=completed_repair_required_codes_hash,
            source_qfq_factor_repair_event_storage_ids=(
                source_qfq_factor_repair_event_storage_ids
            ),
            freqs=freqs,
        )

    return MacdKdjRepairCompletionGateStatus(
        ready=True,
        reason="MACD/KDJ repair completion check covers qfq repair scope.",
        event_storage_ids=tuple(sorted(event_storage_ids)),
        covered_start_trade_date=covered_start_trade_date,
        covered_end_trade_date=covered_end_trade_date,
        stock_code_scope=stock_code_scope,
        stock_code_count=stock_code_count,
        repair_required_code_count=completed_repair_required_code_count,
        repair_required_codes_hash=completed_repair_required_codes_hash,
        source_qfq_factor_repair_event_storage_ids=(
            source_qfq_factor_repair_event_storage_ids
        ),
        freqs=freqs,
    )


def _record_succeeded(record: object) -> bool:
    status = getattr(record, "status", None)
    return status == AssetCheckExecutionRecordStatus.SUCCEEDED or status == "SUCCEEDED"


def _record_event(record: object) -> object | None:
    return getattr(record, "event", None) or getattr(record, "event_log_entry", None)


def _record_evaluation(record: object) -> object:
    event = _record_event(record)
    dagster_event = getattr(event, "dagster_event", None)
    evaluation = getattr(dagster_event, "event_specific_data", None)
    return evaluation if evaluation is not None else object()


def _record_partition(record: object, evaluation: object) -> str | None:
    partition = getattr(record, "partition", None)
    return partition if partition is not None else getattr(evaluation, "partition", None)


def _record_storage_id(record: object) -> int | None:
    candidates = (
        getattr(record, "storage_id", None),
        getattr(record, "id", None),
        getattr(_record_event(record), "storage_id", None),
    )
    for candidate in candidates:
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


def _record_metadata(evaluation: object) -> dict[str, object]:
    raw_metadata = getattr(evaluation, "metadata", None)
    if not isinstance(raw_metadata, Mapping):
        return {}
    return {
        str(key): _unwrap_metadata_value(value)
        for key, value in raw_metadata.items()
    }


def _unwrap_metadata_value(value: object) -> object:
    if hasattr(value, "value"):
        return getattr(value, "value")
    if hasattr(value, "data"):
        return getattr(value, "data")
    text_value = getattr(value, "text", None)
    if isinstance(text_value, str):
        return text_value
    return value


def _metadata_value(metadata: Mapping[str, object], key: str) -> object | None:
    return metadata.get(f"goldenshare/{key}", metadata.get(key))


def _metadata_has_keys(metadata: Mapping[str, object], keys: Sequence[str]) -> bool:
    return all(_metadata_value(metadata, key) is not None for key in keys)


def _metadata_bool(metadata: Mapping[str, object], key: str) -> bool | None:
    value = _metadata_value(metadata, key)
    return value if isinstance(value, bool) else None


def _metadata_int(metadata: Mapping[str, object], key: str) -> int | None:
    value = _metadata_value(metadata, key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _metadata_str(metadata: Mapping[str, object], key: str) -> str | None:
    value = _metadata_value(metadata, key)
    return value if isinstance(value, str) and value else None


def _metadata_int_tuple(metadata: Mapping[str, object], key: str) -> tuple[int, ...]:
    value = _metadata_value(metadata, key)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    int_values = []
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool):
            return ()
        int_values.append(item)
    return tuple(sorted(int_values))


def _metadata_str_tuple(metadata: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = _metadata_value(metadata, key)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    str_values = []
    for item in value:
        if not isinstance(item, str) or not item:
            return ()
        str_values.append(item)
    return tuple(sorted(str_values))


def _qfq_metadata_requires_macd_kdj_repair(metadata: Mapping[str, object]) -> bool:
    repair_required = _metadata_bool(metadata, "repair_required") is True
    rewrite_counts = (
        _metadata_int(metadata, "rewritten_file_count") or 0,
        _metadata_int(metadata, "rewritten_row_count") or 0,
        _metadata_int(metadata, "derived_rewritten_file_count") or 0,
        _metadata_int(metadata, "derived_rewritten_row_count") or 0,
    )
    derived_rewrite_required = (
        _metadata_bool(metadata, "derived_rewrite_required") is True
    )
    return repair_required and (derived_rewrite_required or any(count > 0 for count in rewrite_counts))
