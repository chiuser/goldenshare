from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_bootstrap_events import (
    GOLD_STK_MINS_QFQ_EVENT_COUNT_PER_ASSET_PARTITION,
    StkMinsQfqBootstrapPartitionAudit,
    audit_stk_mins_qfq_bootstrap_batch,
    report_stk_mins_qfq_partition_events,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_derived_bootstrap_events import (
    GOLD_STK_MINS_QFQ_DERIVED_EVENT_COUNT_PER_ASSET_PARTITION,
    audit_stk_mins_qfq_derived_bootstrap_batch,
    report_stk_mins_qfq_derived_partition_events,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_derived_history import (
    StkMinsQfqDerivedHistoryBatch,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_history import StkMinsQfqHistoryBatch
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_QFQ_DERIVED_FREQS,
    STK_MINS_QFQ_NATIVE_FREQS,
    qfq_source_freq_for_derived_freq,
)


STK_MINS_QFQ_REPAIR_RECONCILIATION_SOURCE_METHOD = (
    "stk_mins_qfq_factor_repair_reconciliation"
)


@dataclass(frozen=True)
class StkMinsQfqRepairReconciliationPlan:
    trade_date: str
    repair_start_trade_date: str | None
    repair_end_trade_date: str | None
    selected_partition_keys: tuple[str, ...]
    native_batches: tuple[StkMinsQfqHistoryBatch, ...]
    derived_batches: tuple[StkMinsQfqDerivedHistoryBatch, ...]
    qfq_factor_repair_event_storage_ids: tuple[int, ...]
    repair_required_codes_hash: str | None
    reason: str

    @property
    def native_asset_partition_count(self) -> int:
        return sum(len(batch.partition_keys) for batch in self.native_batches)

    @property
    def derived_asset_partition_count(self) -> int:
        return sum(len(batch.partition_keys) for batch in self.derived_batches)

    @property
    def asset_partition_count(self) -> int:
        return self.native_asset_partition_count + self.derived_asset_partition_count

    @property
    def planned_event_count(self) -> int:
        native_events = (
            self.native_asset_partition_count
            * GOLD_STK_MINS_QFQ_EVENT_COUNT_PER_ASSET_PARTITION
        )
        derived_events = (
            self.derived_asset_partition_count
            * GOLD_STK_MINS_QFQ_DERIVED_EVENT_COUNT_PER_ASSET_PARTITION
        )
        return native_events + derived_events


@dataclass(frozen=True)
class StkMinsQfqRepairReconciliationReport:
    plan: StkMinsQfqRepairReconciliationPlan
    dry_run: bool
    partition_audits: tuple[StkMinsQfqBootstrapPartitionAudit, ...]
    reported_asset_partitions: tuple[tuple[int, str], ...]
    reported_event_count: int

    @property
    def failed_partition_count(self) -> int:
        return sum(1 for audit in self.partition_audits if not audit.passed)


def build_stk_mins_qfq_repair_reconciliation_plan(
    *,
    qfq_factor_repair_status: GoldStkMinsQfqFactorRepairStatus,
    registered_partition_keys: Sequence[str],
) -> StkMinsQfqRepairReconciliationPlan:
    if not qfq_factor_repair_status.ready:
        return StkMinsQfqRepairReconciliationPlan(
            trade_date=qfq_factor_repair_status.trade_date,
            repair_start_trade_date=qfq_factor_repair_status.repair_start_trade_date,
            repair_end_trade_date=qfq_factor_repair_status.repair_end_trade_date,
            selected_partition_keys=(),
            native_batches=(),
            derived_batches=(),
            qfq_factor_repair_event_storage_ids=(
                qfq_factor_repair_status.qfq_factor_repair_event_storage_ids
            ),
            repair_required_codes_hash=(
                qfq_factor_repair_status.repair_required_codes_hash
            ),
            reason=qfq_factor_repair_status.reason,
        )
    if not qfq_factor_repair_status.rewrote_history:
        return StkMinsQfqRepairReconciliationPlan(
            trade_date=qfq_factor_repair_status.trade_date,
            repair_start_trade_date=qfq_factor_repair_status.repair_start_trade_date,
            repair_end_trade_date=qfq_factor_repair_status.repair_end_trade_date,
            selected_partition_keys=(),
            native_batches=(),
            derived_batches=(),
            qfq_factor_repair_event_storage_ids=(
                qfq_factor_repair_status.qfq_factor_repair_event_storage_ids
            ),
            repair_required_codes_hash=(
                qfq_factor_repair_status.repair_required_codes_hash
            ),
            reason="qfq factor repair did not rewrite history; reconciliation is not required.",
        )

    start_trade_date = qfq_factor_repair_status.repair_start_trade_date
    end_trade_date = qfq_factor_repair_status.repair_end_trade_date
    if start_trade_date is None or end_trade_date is None:
        raise dg.Failure(
            "qfq repair reconciliation cannot determine repair start/end trade date: "
            f"trade_date={qfq_factor_repair_status.trade_date}."
        )
    selected_partition_keys = _select_reconciliation_partition_keys(
        registered_partition_keys,
        start_trade_date=start_trade_date,
        end_trade_date=end_trade_date,
    )
    native_batches = _build_native_reconciliation_batches(selected_partition_keys)
    derived_batches = (
        _build_derived_reconciliation_batches(selected_partition_keys)
        if qfq_factor_repair_status.requires_derived_reconciliation
        else ()
    )
    return StkMinsQfqRepairReconciliationPlan(
        trade_date=qfq_factor_repair_status.trade_date,
        repair_start_trade_date=start_trade_date,
        repair_end_trade_date=end_trade_date,
        selected_partition_keys=selected_partition_keys,
        native_batches=native_batches,
        derived_batches=derived_batches,
        qfq_factor_repair_event_storage_ids=(
            qfq_factor_repair_status.qfq_factor_repair_event_storage_ids
        ),
        repair_required_codes_hash=qfq_factor_repair_status.repair_required_codes_hash,
        reason="qfq factor repair rewrote history; ordinary qfq events require reconciliation.",
    )


def report_stk_mins_qfq_repair_reconciliation_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb: DuckDBResource,
    registered_partition_keys: Sequence[str],
    qfq_factor_repair_status: GoldStkMinsQfqFactorRepairStatus,
    dry_run: bool = False,
) -> StkMinsQfqRepairReconciliationReport:
    plan = build_stk_mins_qfq_repair_reconciliation_plan(
        qfq_factor_repair_status=qfq_factor_repair_status,
        registered_partition_keys=registered_partition_keys,
    )
    if not qfq_factor_repair_status.ready:
        raise dg.Failure(
            "qfq repair reconciliation requires green qfq factor repair checks: "
            f"trade_date={qfq_factor_repair_status.trade_date}, "
            f"reason={qfq_factor_repair_status.reason}."
        )
    if not qfq_factor_repair_status.rewrote_history:
        return StkMinsQfqRepairReconciliationReport(
            plan=plan,
            dry_run=dry_run,
            partition_audits=(),
            reported_asset_partitions=(),
            reported_event_count=0,
        )

    source_metadata = _source_reconciliation_metadata(plan)
    audits: list[StkMinsQfqBootstrapPartitionAudit] = []
    reported: list[tuple[int, str]] = []
    event_count = 0

    for batch in plan.native_batches:
        batch_audits = audit_stk_mins_qfq_bootstrap_batch(
            lake_root=lake_root,
            duckdb=duckdb,
            batch=batch,
            as_of_trade_date=plan.trade_date,
        )
        _raise_on_failed_audits(batch_audits, label="stk_mins qfq reconciliation")
        audits.extend(batch_audits)
        if not dry_run:
            for audit in batch_audits:
                event_count += report_stk_mins_qfq_partition_events(
                    instance=instance,
                    audit=audit,
                    source_method=STK_MINS_QFQ_REPAIR_RECONCILIATION_SOURCE_METHOD,
                    extra_metadata=source_metadata,
                )
                reported.append((audit.freq, audit.partition_key))

    for batch in plan.derived_batches:
        batch_audits = audit_stk_mins_qfq_derived_bootstrap_batch(
            lake_root=lake_root,
            duckdb=duckdb,
            batch=batch,
        )
        _raise_on_failed_audits(
            batch_audits,
            label="stk_mins qfq derived reconciliation",
        )
        audits.extend(batch_audits)
        if not dry_run:
            for audit in batch_audits:
                event_count += report_stk_mins_qfq_derived_partition_events(
                    instance=instance,
                    audit=audit,
                    source_method=STK_MINS_QFQ_REPAIR_RECONCILIATION_SOURCE_METHOD,
                    extra_metadata=source_metadata,
                )
                reported.append((audit.freq, audit.partition_key))

    return StkMinsQfqRepairReconciliationReport(
        plan=plan,
        dry_run=dry_run,
        partition_audits=tuple(audits),
        reported_asset_partitions=tuple(reported) if not dry_run else (),
        reported_event_count=event_count if not dry_run else 0,
    )


def _source_reconciliation_metadata(
    plan: StkMinsQfqRepairReconciliationPlan,
) -> dict[str, object]:
    return {
        "bootstrap_event_backfill": False,
        "qfq_factor_repair_event_reconciliation": True,
        "source_qfq_factor_repair_trade_date": plan.trade_date,
        "source_qfq_factor_repair_event_storage_ids": list(
            plan.qfq_factor_repair_event_storage_ids
        ),
        "repair_required_codes_hash": plan.repair_required_codes_hash,
        "repair_start_trade_date": plan.repair_start_trade_date,
        "repair_end_trade_date": plan.repair_end_trade_date,
    }


def _raise_on_failed_audits(
    audits: Sequence[StkMinsQfqBootstrapPartitionAudit],
    *,
    label: str,
) -> None:
    failed_audits = tuple(audit for audit in audits if not audit.passed)
    if not failed_audits:
        return
    samples = {
        f"{audit.freq}:{audit.partition_key}": audit.failed_check_names
        for audit in failed_audits[:10]
    }
    raise ValueError(f"{label} audit failed: {samples}")


def _select_reconciliation_partition_keys(
    registered_partition_keys: Sequence[str],
    *,
    start_trade_date: str,
    end_trade_date: str,
) -> tuple[str, ...]:
    selected_partition_keys = tuple(
        trade_date
        for trade_date in sorted({str(key).strip() for key in registered_partition_keys})
        if start_trade_date <= trade_date <= end_trade_date
    )
    if not selected_partition_keys:
        raise dg.Failure(
            "qfq repair reconciliation found no registered trade days in repair scope: "
            f"start_trade_date={start_trade_date}, end_trade_date={end_trade_date}."
        )
    return selected_partition_keys


def _build_native_reconciliation_batches(
    selected_partition_keys: Sequence[str],
) -> tuple[StkMinsQfqHistoryBatch, ...]:
    return tuple(
        StkMinsQfqHistoryBatch(
            freq=freq,
            year=year,
            partition_keys=year_partition_keys,
        )
        for freq in STK_MINS_QFQ_NATIVE_FREQS
        for year, year_partition_keys in _partition_keys_by_year(
            selected_partition_keys
        ).items()
    )


def _build_derived_reconciliation_batches(
    selected_partition_keys: Sequence[str],
) -> tuple[StkMinsQfqDerivedHistoryBatch, ...]:
    return tuple(
        StkMinsQfqDerivedHistoryBatch(
            target_freq=target_freq,
            source_freq=qfq_source_freq_for_derived_freq(target_freq),
            year=year,
            partition_keys=year_partition_keys,
        )
        for target_freq in STK_MINS_QFQ_DERIVED_FREQS
        for year, year_partition_keys in _partition_keys_by_year(
            selected_partition_keys
        ).items()
    )


def _partition_keys_by_year(
    partition_keys: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for partition_key in partition_keys:
        grouped.setdefault(partition_key[:4], []).append(partition_key)
    return {year: tuple(keys) for year, keys in grouped.items()}
