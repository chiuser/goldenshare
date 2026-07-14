from __future__ import annotations

from dataclasses import dataclass

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
    asset_check_record_evaluation,
    asset_check_record_event_storage_id,
    asset_check_record_metadata,
    asset_check_record_partition,
    asset_check_record_succeeded,
    gold_stk_mins_qfq_factor_repair_status,
    latest_partition_check_records,
    metadata_has_keys,
    metadata_int,
    metadata_int_tuple,
    metadata_str,
)
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_FREQS
from orchestrator.defs.stk_mins_qfq import QFQ_FACTOR_REPAIR_AUTO_MACD_KDJ_CODE_LIMIT
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
)


_MACD_KDJ_REPAIR_COMMON_COMPLETION_REQUIRED_METADATA_KEYS = (
    "covered_start_trade_date",
    "covered_end_trade_date",
    "freqs",
    "stock_code_scope",
    "stock_code_count",
    "repair_required_code_count",
    "repair_required_codes_hash",
)
_MACD_KDJ_REPAIR_COMPLETION_REQUIRED_METADATA_KEYS = (
    *_MACD_KDJ_REPAIR_COMMON_COMPLETION_REQUIRED_METADATA_KEYS,
    "source_upstream_batch_id",
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
    source_upstream_batch_id: str | None = None
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
            "source_upstream_batch_id": self.source_upstream_batch_id,
            "freqs": list(self.freqs),
        }


@dataclass(frozen=True)
class GoldStkMinsQfqMacdKdjDailyRepairGateStatus:
    ready: bool
    trade_date: str
    reason: str
    requires_macd_kdj_repair: bool = False
    qfq_factor_repair_event_storage_ids: tuple[int, ...] = ()
    upstream_batch_id: str | None = None
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
            "upstream_batch_id": self.upstream_batch_id,
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
    qfq_status = gold_stk_mins_qfq_factor_repair_status(
        instance,
        trade_date,
    )
    qfq_result = _macd_kdj_gate_status_from_qfq_factor_repair_status(qfq_status)
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
            upstream_batch_id=qfq_result.upstream_batch_id,
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
        upstream_batch_id=qfq_result.upstream_batch_id,
        repair_start_trade_date=qfq_result.repair_start_trade_date,
        repair_end_trade_date=qfq_result.repair_end_trade_date,
        selected_partition_count=qfq_result.selected_partition_count,
        repair_required_code_count=qfq_result.repair_required_code_count,
        repair_required_codes=qfq_result.repair_required_codes,
        repair_required_codes_hash=qfq_result.repair_required_codes_hash,
        repair_required_codes_truncated=qfq_result.repair_required_codes_truncated,
        macd_kdj_repair_status=macd_kdj_repair_status,
    )


def gold_stk_mins_qfq_macd_kdj_repair_completion_status(
    instance: dg.DagsterInstance,
    *,
    qfq_factor_repair_status: GoldStkMinsQfqMacdKdjDailyRepairGateStatus,
) -> MacdKdjRepairCompletionGateStatus:
    return gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch(
        instance,
        qfq_factor_repair_trade_date=qfq_factor_repair_status.trade_date,
        repair_start_trade_date=qfq_factor_repair_status.repair_start_trade_date,
        repair_end_trade_date=qfq_factor_repair_status.repair_end_trade_date,
        upstream_batch_id=qfq_factor_repair_status.upstream_batch_id,
        repair_required_code_count=qfq_factor_repair_status.repair_required_code_count,
        repair_required_codes_hash=qfq_factor_repair_status.repair_required_codes_hash,
    )


def gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch(
    instance: dg.DagsterInstance,
    *,
    qfq_factor_repair_trade_date: str | None,
    repair_start_trade_date: str | None,
    repair_end_trade_date: str | None,
    upstream_batch_id: str | None,
    repair_required_code_count: int,
    repair_required_codes_hash: str | None,
) -> MacdKdjRepairCompletionGateStatus:
    return _macd_kdj_repair_completion_status(
        instance,
        qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
        repair_start_trade_date=repair_start_trade_date,
        repair_end_trade_date=repair_end_trade_date,
        upstream_batch_id=upstream_batch_id,
        repair_required_code_count=repair_required_code_count,
        repair_required_codes_hash=repair_required_codes_hash,
    )


def assert_gold_stk_mins_qfq_macd_kdj_daily_repair_gate(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> None:
    status = gold_stk_mins_qfq_factor_repair_status(
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


def _macd_kdj_gate_status_from_qfq_factor_repair_status(
    status: GoldStkMinsQfqFactorRepairStatus,
) -> GoldStkMinsQfqMacdKdjDailyRepairGateStatus:
    return GoldStkMinsQfqMacdKdjDailyRepairGateStatus(
        ready=status.ready,
        trade_date=status.trade_date,
        reason=status.reason,
        requires_macd_kdj_repair=status.rewrote_history,
        qfq_factor_repair_event_storage_ids=status.qfq_factor_repair_event_storage_ids,
        upstream_batch_id=status.upstream_batch_id,
        missing_qfq_asset_keys=status.missing_qfq_asset_keys,
        failed_qfq_asset_keys=status.failed_qfq_asset_keys,
        repair_start_trade_date=status.repair_start_trade_date,
        repair_end_trade_date=status.repair_end_trade_date,
        selected_partition_count=status.selected_partition_count,
        repair_required_code_count=status.repair_required_code_count,
        repair_required_codes=status.repair_required_codes,
        repair_required_codes_hash=status.repair_required_codes_hash,
        repair_required_codes_truncated=status.repair_required_codes_truncated,
    )


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


def _macd_kdj_repair_completion_status(
    instance: dg.DagsterInstance,
    *,
    qfq_factor_repair_trade_date: str | None,
    repair_start_trade_date: str | None,
    repair_end_trade_date: str | None,
    upstream_batch_id: str | None,
    repair_required_code_count: int,
    repair_required_codes_hash: str | None,
) -> MacdKdjRepairCompletionGateStatus:
    if (
        qfq_factor_repair_trade_date is None
        or
        repair_start_trade_date is None
        or repair_end_trade_date is None
        or upstream_batch_id is None
    ):
        return MacdKdjRepairCompletionGateStatus(
            ready=False,
            reason="qfq factor repair scope metadata is incomplete.",
        )
    records_by_key = latest_partition_check_records(
        instance,
        _macd_kdj_asset_keys(),
        GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
        partition_key=qfq_factor_repair_trade_date,
    )
    missing: list[str] = []
    failed: list[str] = []
    event_storage_ids: list[int] = []
    metadata_rows: list[dict[str, object]] = []

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
        evaluation = asset_check_record_evaluation(record)
        storage_id = asset_check_record_event_storage_id(
            instance,
            check_key,
            record,
            partition_key=qfq_factor_repair_trade_date,
        )
        metadata = asset_check_record_metadata(evaluation)
        if (
            not asset_check_record_succeeded(record)
            or getattr(evaluation, "passed", None) is not True
            or getattr(evaluation, "blocking", None) is not True
            or asset_check_record_partition(record, evaluation)
            != qfq_factor_repair_trade_date
            or not metadata_has_keys(
                metadata,
                _MACD_KDJ_REPAIR_COMPLETION_REQUIRED_METADATA_KEYS,
            )
        ):
            failed.append(asset_label)
            continue
        if storage_id is not None:
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
    covered_start_trade_date = metadata_str(
        first_metadata,
        "covered_start_trade_date",
    )
    covered_end_trade_date = metadata_str(first_metadata, "covered_end_trade_date")
    stock_code_scope = metadata_str(first_metadata, "stock_code_scope")
    stock_code_count = metadata_int(first_metadata, "stock_code_count")
    completed_repair_required_code_count = metadata_int(
        first_metadata,
        "repair_required_code_count",
    )
    completed_repair_required_codes_hash = metadata_str(
        first_metadata,
        "repair_required_codes_hash",
    )
    source_upstream_batch_id = metadata_str(
        first_metadata,
        "source_upstream_batch_id",
    )
    freqs = metadata_int_tuple(first_metadata, "freqs")
    all_freqs = tuple(STK_MINS_QFQ_FREQS)
    if (
        covered_start_trade_date is None
        or covered_end_trade_date is None
        or stock_code_scope is None
        or stock_code_count is None
        or completed_repair_required_code_count is None
        or completed_repair_required_codes_hash is None
        or source_upstream_batch_id is None
        or covered_start_trade_date > repair_start_trade_date
        or covered_end_trade_date < repair_end_trade_date
        or tuple(sorted(freqs)) != all_freqs
        or completed_repair_required_code_count != repair_required_code_count
        or completed_repair_required_codes_hash != repair_required_codes_hash
        or source_upstream_batch_id != upstream_batch_id
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
            source_upstream_batch_id=source_upstream_batch_id,
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
        source_upstream_batch_id=source_upstream_batch_id,
        freqs=freqs,
    )
