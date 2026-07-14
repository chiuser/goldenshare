from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json

import dagster as dg
from dagster._core.event_api import PartitionKeyFilter
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    asset_check_record_evaluation,
    asset_check_record_metadata,
    asset_check_record_partition,
    asset_check_record_succeeded,
    gold_stk_mins_qfq_factor_repair_status,
    latest_partition_check_records,
    metadata_int,
    metadata_int_tuple,
    metadata_str,
)
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_FREQS
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
)


MAX_REHYDRATION_TRADE_DATE_COUNT = 4
MAX_REHYDRATION_EVENT_COUNT = 56
DEFAULT_HISTORY_PAGE_LIMIT = 100
MAX_HISTORY_RECORDS_PER_CHECK_KEY = 1_000
REHYDRATION_METHOD = "repair_completion_identity_rehydration"
R5_P5_REHYDRATION_TRADE_DATES = (
    "2026-07-08",
    "2026-07-09",
    "2026-07-10",
    "2026-07-13",
)
_TERMINAL_CHECK_STATUSES = {
    AssetCheckExecutionRecordStatus.SUCCEEDED,
    AssetCheckExecutionRecordStatus.FAILED,
}


@dataclass(frozen=True, slots=True)
class MacdKdjRepairCompletionEvent:
    asset_key: dg.AssetKey
    qfq_factor_repair_trade_date: str
    source_event_storage_id: int
    source_repair_run_id: str
    source_metadata: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_key": self.asset_key.to_user_string(),
            "qfq_factor_repair_trade_date": self.qfq_factor_repair_trade_date,
            "source_event_storage_id": self.source_event_storage_id,
            "source_repair_run_id": self.source_repair_run_id,
        }

    def rehydrated_metadata(self) -> dict[str, object]:
        return {
            **dict(self.source_metadata),
            "goldenshare/bootstrap_method": REHYDRATION_METHOD,
            "goldenshare/bootstrap_event_backfill": True,
            "goldenshare/event_backfill_scope": "repair_completion_identity",
            "goldenshare/source_completion_event_storage_id": (
                self.source_event_storage_id
            ),
            "goldenshare/source_repair_run_id": self.source_repair_run_id,
        }


@dataclass(frozen=True, slots=True)
class MacdKdjRepairCompletionBatchPlan:
    qfq_factor_repair_trade_date: str
    repair_start_trade_date: str | None
    repair_end_trade_date: str | None
    upstream_batch_id: str | None
    repair_required_code_count: int
    repair_required_codes_hash: str | None
    producer_run_id: str | None
    source_completion_event_count: int
    existing_target_event_count: int
    planned_events: tuple[MacdKdjRepairCompletionEvent, ...]
    stop_reasons: tuple[str, ...]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "qfq_factor_repair_trade_date": self.qfq_factor_repair_trade_date,
            "repair_start_trade_date": self.repair_start_trade_date,
            "repair_end_trade_date": self.repair_end_trade_date,
            "upstream_batch_id": self.upstream_batch_id,
            "repair_required_code_count": self.repair_required_code_count,
            "repair_required_codes_hash": self.repair_required_codes_hash,
            "producer_run_id": self.producer_run_id,
            "source_completion_event_count": self.source_completion_event_count,
            "existing_target_event_count": self.existing_target_event_count,
            "planned_event_count": len(self.planned_events),
            "planned_events": [event.to_dict() for event in self.planned_events],
            "stop_reasons": list(self.stop_reasons),
        }


@dataclass(frozen=True, slots=True)
class MacdKdjRepairCompletionEventPlan:
    batches: tuple[MacdKdjRepairCompletionBatchPlan, ...]

    @property
    def should_stop(self) -> bool:
        return any(batch.should_stop for batch in self.batches)

    @property
    def planned_event_count(self) -> int:
        return sum(len(batch.planned_events) for batch in self.batches)

    @property
    def existing_target_event_count(self) -> int:
        return sum(batch.existing_target_event_count for batch in self.batches)

    @property
    def source_completion_event_count(self) -> int:
        return sum(batch.source_completion_event_count for batch in self.batches)

    @property
    def events(self) -> tuple[MacdKdjRepairCompletionEvent, ...]:
        return tuple(event for batch in self.batches for event in batch.planned_events)

    @property
    def fingerprint(self) -> str:
        payload = self.to_dict(include_fingerprint=False)
        serialized = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return sha256(serialized.encode("utf-8")).hexdigest()

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "rehydration_method": REHYDRATION_METHOD,
            "batch_count": len(self.batches),
            "source_completion_event_count": self.source_completion_event_count,
            "existing_target_event_count": self.existing_target_event_count,
            "planned_event_count": self.planned_event_count,
            "max_rehydration_event_count": MAX_REHYDRATION_EVENT_COUNT,
            "should_stop": self.should_stop,
            "batches": [batch.to_dict() for batch in self.batches],
        }
        if include_fingerprint:
            payload["plan_fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True, slots=True)
class MacdKdjRepairCompletionEventReport:
    plan: MacdKdjRepairCompletionEventPlan
    dry_run: bool
    reported_event_count: int
    post_apply_plan: MacdKdjRepairCompletionEventPlan | None

    def to_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "reported_event_count": self.reported_event_count,
            "plan": self.plan.to_dict(),
            "post_apply_plan": (
                self.post_apply_plan.to_dict() if self.post_apply_plan is not None else None
            ),
        }


def plan_stk_mins_qfq_macd_kdj_repair_completion_events(
    *,
    instance: dg.DagsterInstance,
    qfq_factor_repair_trade_dates: Sequence[str],
    history_page_limit: int = DEFAULT_HISTORY_PAGE_LIMIT,
    max_history_records_per_check_key: int = MAX_HISTORY_RECORDS_PER_CHECK_KEY,
) -> MacdKdjRepairCompletionEventPlan:
    trade_dates = _normalize_trade_dates(qfq_factor_repair_trade_dates)
    _validate_history_limits(
        history_page_limit=history_page_limit,
        max_history_records_per_check_key=max_history_records_per_check_key,
    )
    batches = tuple(
        _plan_repair_completion_batch(
            instance=instance,
            qfq_factor_repair_trade_date=trade_date,
            history_page_limit=history_page_limit,
            max_history_records_per_check_key=max_history_records_per_check_key,
        )
        for trade_date in trade_dates
    )
    plan = MacdKdjRepairCompletionEventPlan(batches=batches)
    if plan.planned_event_count > MAX_REHYDRATION_EVENT_COUNT:
        raise ValueError(
            "MACD/KDJ repair completion rehydration exceeds the bounded event budget: "
            f"{plan.planned_event_count} > {MAX_REHYDRATION_EVENT_COUNT}."
        )
    return plan


def report_stk_mins_qfq_macd_kdj_repair_completion_events(
    *,
    instance: dg.DagsterInstance,
    qfq_factor_repair_trade_dates: Sequence[str],
    dry_run: bool = True,
    expected_plan_fingerprint: str | None = None,
    history_page_limit: int = DEFAULT_HISTORY_PAGE_LIMIT,
    max_history_records_per_check_key: int = MAX_HISTORY_RECORDS_PER_CHECK_KEY,
) -> MacdKdjRepairCompletionEventReport:
    plan = plan_stk_mins_qfq_macd_kdj_repair_completion_events(
        instance=instance,
        qfq_factor_repair_trade_dates=qfq_factor_repair_trade_dates,
        history_page_limit=history_page_limit,
        max_history_records_per_check_key=max_history_records_per_check_key,
    )
    if dry_run:
        return MacdKdjRepairCompletionEventReport(
            plan=plan,
            dry_run=True,
            reported_event_count=0,
            post_apply_plan=None,
        )
    if plan.should_stop:
        raise ValueError(
            "MACD/KDJ repair completion event rehydration preflight failed: "
            + "; ".join(
                reason for batch in plan.batches for reason in batch.stop_reasons
            )
        )
    if expected_plan_fingerprint != plan.fingerprint:
        raise ValueError(
            "MACD/KDJ repair completion event plan fingerprint does not match the "
            "current Dagster state. Run plan-events again before apply."
        )

    reported_event_count = 0
    for event in plan.events:
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=event.asset_key,
                check_name=GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
                passed=True,
                metadata=event.rehydrated_metadata(),
                blocking=True,
                partition=event.qfq_factor_repair_trade_date,
            )
        )
        reported_event_count += 1

    post_apply_plan = plan_stk_mins_qfq_macd_kdj_repair_completion_events(
        instance=instance,
        qfq_factor_repair_trade_dates=qfq_factor_repair_trade_dates,
        history_page_limit=history_page_limit,
        max_history_records_per_check_key=max_history_records_per_check_key,
    )
    if post_apply_plan.should_stop or post_apply_plan.planned_event_count:
        raise RuntimeError(
            "MACD/KDJ repair completion event rehydration did not converge; rerun "
            "plan-events before any further action."
        )
    return MacdKdjRepairCompletionEventReport(
        plan=plan,
        dry_run=False,
        reported_event_count=reported_event_count,
        post_apply_plan=post_apply_plan,
    )


def _plan_repair_completion_batch(
    *,
    instance: dg.DagsterInstance,
    qfq_factor_repair_trade_date: str,
    history_page_limit: int,
    max_history_records_per_check_key: int,
) -> MacdKdjRepairCompletionBatchPlan:
    qfq_status = gold_stk_mins_qfq_factor_repair_status(
        instance,
        qfq_factor_repair_trade_date,
    )
    base = {
        "qfq_factor_repair_trade_date": qfq_factor_repair_trade_date,
        "repair_start_trade_date": qfq_status.repair_start_trade_date,
        "repair_end_trade_date": qfq_status.repair_end_trade_date,
        "upstream_batch_id": qfq_status.upstream_batch_id,
        "repair_required_code_count": qfq_status.repair_required_code_count,
        "repair_required_codes_hash": qfq_status.repair_required_codes_hash,
        "producer_run_id": qfq_status.producer_run_id,
    }
    stop_reasons = _qfq_status_stop_reasons(instance, qfq_status)
    if stop_reasons:
        return MacdKdjRepairCompletionBatchPlan(
            **base,
            source_completion_event_count=0,
            existing_target_event_count=0,
            planned_events=(),
            stop_reasons=stop_reasons,
        )

    source_records_by_asset = _source_records_by_asset(
        instance=instance,
        repair_start_trade_date=qfq_status.repair_start_trade_date or "",
        qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
        repair_end_trade_date=qfq_status.repair_end_trade_date or "",
        upstream_batch_id=qfq_status.upstream_batch_id or "",
        repair_required_code_count=qfq_status.repair_required_code_count,
        repair_required_codes_hash=qfq_status.repair_required_codes_hash or "",
        history_page_limit=history_page_limit,
        max_history_records_per_check_key=max_history_records_per_check_key,
    )
    source_stop_reasons = tuple(
        reason
        for asset_key, records in source_records_by_asset.items()
        for reason in _source_record_stop_reasons(asset_key, records)
    )
    if source_stop_reasons:
        return MacdKdjRepairCompletionBatchPlan(
            **base,
            source_completion_event_count=sum(
                len(records) for records in source_records_by_asset.values()
            ),
            existing_target_event_count=0,
            planned_events=(),
            stop_reasons=source_stop_reasons,
        )

    source_records = tuple(
        source_records_by_asset[asset_key][0]
        for asset_key in _repair_completion_asset_keys()
    )
    source_repair_run_ids = {
        _check_record_run_id(record) for record in source_records
    }
    if None in source_repair_run_ids or len(source_repair_run_ids) != 1:
        return MacdKdjRepairCompletionBatchPlan(
            **base,
            source_completion_event_count=len(source_records),
            existing_target_event_count=0,
            planned_events=(),
            stop_reasons=("source_completion_events_do_not_share_one_successful_run",),
        )
    source_repair_run_id = next(iter(source_repair_run_ids))
    if not isinstance(source_repair_run_id, str) or not _run_succeeded(
        instance,
        source_repair_run_id,
    ):
        return MacdKdjRepairCompletionBatchPlan(
            **base,
            source_completion_event_count=len(source_records),
            existing_target_event_count=0,
            planned_events=(),
            stop_reasons=("source_completion_run_is_not_successful",),
        )

    target_records = latest_partition_check_records(
        instance,
        _repair_completion_asset_keys(),
        GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
        partition_key=qfq_factor_repair_trade_date,
    )
    existing_target_event_count = 0
    planned_events: list[MacdKdjRepairCompletionEvent] = []
    target_stop_reasons: list[str] = []
    for asset_key, source_record in zip(
        _repair_completion_asset_keys(),
        source_records,
        strict=True,
    ):
        check_key = dg.AssetCheckKey(
            asset_key,
            GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
        )
        target_record = target_records.get(check_key)
        if target_record is not None:
            if not _completion_record_matches(
                target_record,
                qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
                repair_start_trade_date=qfq_status.repair_start_trade_date or "",
                repair_end_trade_date=qfq_status.repair_end_trade_date or "",
                upstream_batch_id=qfq_status.upstream_batch_id or "",
                repair_required_code_count=qfq_status.repair_required_code_count,
                repair_required_codes_hash=qfq_status.repair_required_codes_hash or "",
            ):
                target_stop_reasons.append(
                    "target_completion_event_conflicts:"
                    f"{asset_key.to_user_string()}"
                )
                continue
            existing_target_event_count += 1
            continue
        source_metadata = asset_check_record_metadata(
            asset_check_record_evaluation(source_record)
        )
        source_storage_id = _check_record_storage_id(source_record)
        if source_storage_id is None:
            target_stop_reasons.append(
                "source_completion_event_storage_id_missing:"
                f"{asset_key.to_user_string()}"
            )
            continue
        planned_events.append(
            MacdKdjRepairCompletionEvent(
                asset_key=asset_key,
                qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
                source_event_storage_id=source_storage_id,
                source_repair_run_id=source_repair_run_id,
                source_metadata=source_metadata,
            )
        )

    return MacdKdjRepairCompletionBatchPlan(
        **base,
        source_completion_event_count=len(source_records),
        existing_target_event_count=existing_target_event_count,
        planned_events=tuple(planned_events),
        stop_reasons=tuple(target_stop_reasons),
    )


def _qfq_status_stop_reasons(instance, qfq_status) -> tuple[str, ...]:
    reasons: list[str] = []
    if not qfq_status.ready:
        reasons.append("qfq_factor_repair_status_not_ready")
    if not qfq_status.rewrote_history:
        reasons.append("qfq_factor_repair_did_not_rewrite_history")
    if qfq_status.repair_start_trade_date is None:
        reasons.append("qfq_factor_repair_start_trade_date_missing")
    if qfq_status.repair_end_trade_date is None:
        reasons.append("qfq_factor_repair_end_trade_date_missing")
    if qfq_status.upstream_batch_id is None:
        reasons.append("qfq_factor_repair_upstream_batch_id_missing")
    if qfq_status.repair_required_codes_hash is None:
        reasons.append("qfq_factor_repair_codes_hash_missing")
    if qfq_status.repair_required_code_count <= 0:
        reasons.append("qfq_factor_repair_code_scope_missing")
    if qfq_status.producer_run_id is None or not _run_succeeded(
        instance,
        qfq_status.producer_run_id,
    ):
        reasons.append("qfq_factor_repair_producer_run_is_not_successful")
    return tuple(reasons)


def _source_records_by_asset(
    *,
    instance: dg.DagsterInstance,
    repair_start_trade_date: str,
    qfq_factor_repair_trade_date: str,
    repair_end_trade_date: str,
    upstream_batch_id: str,
    repair_required_code_count: int,
    repair_required_codes_hash: str,
    history_page_limit: int,
    max_history_records_per_check_key: int,
) -> dict[dg.AssetKey, tuple[object, ...]]:
    records_by_asset: dict[dg.AssetKey, tuple[object, ...]] = {}
    for asset_key in _repair_completion_asset_keys():
        check_key = dg.AssetCheckKey(
            asset_key,
            GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
        )
        history_records = _load_check_history(
            instance=instance,
            check_key=check_key,
            partition_key=repair_start_trade_date,
            history_page_limit=history_page_limit,
            max_history_records_per_check_key=max_history_records_per_check_key,
        )
        records_by_asset[asset_key] = tuple(
            record
            for record in history_records
            if _completion_record_matches(
                record,
                qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
                repair_start_trade_date=repair_start_trade_date,
                repair_end_trade_date=repair_end_trade_date,
                upstream_batch_id=upstream_batch_id,
                repair_required_code_count=repair_required_code_count,
                repair_required_codes_hash=repair_required_codes_hash,
            )
        )
    return records_by_asset


def _source_record_stop_reasons(
    asset_key: dg.AssetKey,
    records: Sequence[object],
) -> tuple[str, ...]:
    if not records:
        return (f"source_completion_event_missing:{asset_key.to_user_string()}",)
    if len(records) > 1:
        return (f"source_completion_event_ambiguous:{asset_key.to_user_string()}",)
    return ()


def _load_check_history(
    *,
    instance: dg.DagsterInstance,
    check_key: dg.AssetCheckKey,
    partition_key: str,
    history_page_limit: int,
    max_history_records_per_check_key: int,
) -> tuple[object, ...]:
    records: list[object] = []
    cursor: int | None = None
    while True:
        page = instance.event_log_storage.get_asset_check_execution_history(
            check_key,
            limit=history_page_limit,
            cursor=cursor,
            status=_TERMINAL_CHECK_STATUSES,
            partition_filter=PartitionKeyFilter(key=partition_key),
        )
        if not page:
            return tuple(records)
        records.extend(page)
        if len(records) >= max_history_records_per_check_key:
            raise ValueError(
                "MACD/KDJ repair completion history exceeds the bounded read limit: "
                f"{check_key.to_user_string()} >= {max_history_records_per_check_key}."
            )
        cursor = getattr(page[-1], "id", None)
        if cursor is None:
            raise ValueError(
                "MACD/KDJ repair completion history record is missing a pagination id: "
                f"{check_key.to_user_string()}."
            )


def _completion_record_matches(
    record: object,
    *,
    qfq_factor_repair_trade_date: str,
    repair_start_trade_date: str,
    repair_end_trade_date: str,
    upstream_batch_id: str,
    repair_required_code_count: int,
    repair_required_codes_hash: str,
) -> bool:
    evaluation = asset_check_record_evaluation(record)
    metadata = asset_check_record_metadata(evaluation)
    return _completion_record_metadata_matches(
        record=record,
        evaluation=evaluation,
        metadata=metadata,
        qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
        repair_start_trade_date=repair_start_trade_date,
        repair_end_trade_date=repair_end_trade_date,
        upstream_batch_id=upstream_batch_id,
        repair_required_code_count=repair_required_code_count,
        repair_required_codes_hash=repair_required_codes_hash,
    )


def _completion_record_metadata_matches(
    *,
    record: object,
    evaluation: object,
    metadata: Mapping[str, object],
    qfq_factor_repair_trade_date: str,
    repair_start_trade_date: str,
    repair_end_trade_date: str,
    upstream_batch_id: str,
    repair_required_code_count: int,
    repair_required_codes_hash: str,
) -> bool:
    partition = asset_check_record_partition(record, evaluation)
    return (
        asset_check_record_succeeded(record)
        and getattr(evaluation, "passed", None) is True
        and getattr(evaluation, "blocking", None) is True
        and partition
        in (repair_start_trade_date, qfq_factor_repair_trade_date)
        and metadata_str(metadata, "qfq_factor_repair_trade_date")
        == qfq_factor_repair_trade_date
        and metadata_str(metadata, "covered_start_trade_date") == repair_start_trade_date
        and metadata_str(metadata, "covered_end_trade_date") == repair_end_trade_date
        and metadata_str(metadata, "stock_code_scope") == "explicit"
        and metadata_int(metadata, "stock_code_count") == repair_required_code_count
        and metadata_int(metadata, "repair_required_code_count")
        == repair_required_code_count
        and metadata_str(metadata, "repair_required_codes_hash")
        == repair_required_codes_hash
        and metadata_str(metadata, "source_upstream_batch_id") == upstream_batch_id
        and metadata_int_tuple(metadata, "freqs") == tuple(STK_MINS_QFQ_FREQS)
    )


def _check_record_storage_id(record: object) -> int | None:
    for value in (
        getattr(record, "id", None),
        getattr(record, "storage_id", None),
        getattr(getattr(record, "event", None), "storage_id", None),
    ):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _check_record_run_id(record: object) -> str | None:
    event = getattr(record, "event", None) or getattr(record, "event_log_entry", None)
    run_id = getattr(event, "run_id", None)
    return run_id if isinstance(run_id, str) and run_id else None


def _run_succeeded(instance: dg.DagsterInstance, run_id: str | None) -> bool:
    if not run_id:
        return False
    run = instance.get_run_by_id(run_id)
    return getattr(run, "status", None) == dg.DagsterRunStatus.SUCCESS


def _repair_completion_asset_keys() -> tuple[dg.AssetKey, ...]:
    indicator_keys = tuple(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_{freq}m")
        for freq in STK_MINS_QFQ_FREQS
    )
    state_keys = tuple(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_state_{freq}m")
        for freq in STK_MINS_QFQ_FREQS
    )
    return indicator_keys + state_keys


def _normalize_trade_dates(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({_normalize_trade_date(value) for value in values}))
    if not normalized:
        raise ValueError("At least one qfq_factor_repair_trade_date is required.")
    if len(normalized) > MAX_REHYDRATION_TRADE_DATE_COUNT:
        raise ValueError(
            "MACD/KDJ repair completion rehydration exceeds the bounded date count: "
            f"{len(normalized)} > {MAX_REHYDRATION_TRADE_DATE_COUNT}."
        )
    unexpected_trade_dates = sorted(
        set(normalized).difference(R5_P5_REHYDRATION_TRADE_DATES)
    )
    if unexpected_trade_dates:
        raise ValueError(
            "MACD/KDJ repair completion rehydration only permits the approved "
            "R5-P5 QFQ repair dates: "
            + ", ".join(unexpected_trade_dates)
        )
    return normalized


def _normalize_trade_date(value: str) -> str:
    raw_value = str(value).strip()
    try:
        if len(raw_value) != 10:
            raise ValueError
        return date.fromisoformat(raw_value).isoformat()
    except ValueError as error:
        raise ValueError(
            f"qfq_factor_repair_trade_date must use YYYY-MM-DD: {value}"
        ) from error


def _validate_history_limits(
    *,
    history_page_limit: int,
    max_history_records_per_check_key: int,
) -> None:
    if history_page_limit <= 0:
        raise ValueError("history_page_limit must be positive.")
    if max_history_records_per_check_key < history_page_limit:
        raise ValueError(
            "max_history_records_per_check_key must be at least history_page_limit."
        )
