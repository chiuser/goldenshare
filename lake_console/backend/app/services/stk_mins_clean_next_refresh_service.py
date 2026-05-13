from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.affected_partition import AffectedPartition
from lake_console.backend.app.services.indicators.indicator_recalc_queue import IndicatorRecalcQueueService
from lake_console.backend.app.services.stk_mins_clean_next_gate import (
    CLEAN_NEXT_GATE_RELATIVE_PATH,
    CleanNextGateStatus,
    CleanNextPartitionGateService,
)
from lake_console.backend.app.services.stk_mins_clean_service import FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH, StkMinsCleanService


@dataclass(frozen=True)
class CleanNextRefreshPartition:
    affected_partition: AffectedPartition
    freq: int
    trade_date: date


class CleanNextRefreshService:
    def __init__(self, *, lake_root: Path, progress: Any | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or (lambda message: print(message, flush=True))
        self.clean_service = StkMinsCleanService(lake_root=lake_root, progress=self.progress)
        self.gate_service = CleanNextPartitionGateService(lake_root=lake_root)

    def refresh(self, *, affected_partitions: list[dict[str, Any] | AffectedPartition], dry_run: bool, apply: bool) -> dict[str, Any]:
        if dry_run == apply:
            raise ValueError("clean_next refresh 必须且只能指定 dry_run 或 apply。")
        partitions = [_parse_refresh_partition(item) for item in affected_partitions]
        if dry_run:
            return {
                "operation": "refresh_stk_mins_clean_next",
                "mode": "dry_run",
                "status": "planned",
                "affected_partitions": [item.affected_partition.to_dict() for item in partitions],
                "write_intent": False,
            }

        partition_results: list[dict[str, Any]] = []
        gate_statuses: list[CleanNextGateStatus] = []
        overall_status = "passed"
        for index, partition in enumerate(partitions, start=1):
            self.progress(
                f"[stk_mins_clean_next] refresh partition={index}/{len(partitions)} "
                f"freq={partition.freq} trade_date={partition.trade_date.isoformat()}"
            )
            rebuild = self.clean_service.rebuild_formal_clean_next_from_raw(
                freqs=[partition.freq],
                start_date=partition.trade_date,
                end_date=partition.trade_date,
                dry_run=False,
                apply=True,
                replace_existing=True,
            )
            if int(rebuild.get("partitions") or 0) != 1:
                raise RuntimeError(
                    "clean_next refresh 期望每个 affected partition 精确对应一个 raw 分区："
                    f"freq={partition.freq} trade_date={partition.trade_date.isoformat()} partitions={rebuild.get('partitions')}"
                )
            basic_audit = self.clean_service.audit_formal_clean_next_layer(
                freqs=[partition.freq],
                start_date=partition.trade_date,
                end_date=partition.trade_date,
            )
            completeness_audit = self.clean_service.audit_formal_clean_next_completeness(
                freqs=[partition.freq],
                start_date=partition.trade_date,
                end_date=partition.trade_date,
                write_ledger=True,
            )
            issue_count = int(basic_audit.get("issue_count") or 0) + int(completeness_audit.get("issue_count") or 0)
            partition_status = "passed" if issue_count == 0 else "blocked"
            if partition_status != "passed":
                overall_status = "blocked"

            clean_partition_path = f"research/stk_mins_by_date_clean_next/freq={partition.freq}/trade_date={partition.trade_date.isoformat()}"
            gate_statuses.append(
                CleanNextGateStatus(
                    freq=partition.freq,
                    trade_date=partition.trade_date,
                    clean_partition_path=clean_partition_path,
                    source_run_id=partition.affected_partition.source_run_id,
                    clean_run_id=str(rebuild.get("run_id") or ""),
                    write_revision=partition.affected_partition.write_revision,
                    status=partition_status,
                    issue_count=issue_count,
                    raw_rows=int(rebuild.get("raw_rows") or 0),
                    clean_rows=int(rebuild.get("kept_rows") or 0),
                    ledger_path=str(self.lake_root / FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH),
                    message="passed" if partition_status == "passed" else "blocked by clean_next scoped audit",
                )
            )
            partition_results.append(
                {
                    "freq": partition.freq,
                    "trade_date": partition.trade_date.isoformat(),
                    "status": partition_status,
                    "raw_rows": int(rebuild.get("raw_rows") or 0),
                    "clean_rows": int(rebuild.get("kept_rows") or 0),
                    "filter_reasons": rebuild.get("filter_reasons") or {},
                    "issue_count": issue_count,
                    "basic_audit_status": basic_audit.get("status"),
                    "completeness_audit_status": completeness_audit.get("status"),
                    "ledger": completeness_audit.get("ledger"),
                }
            )

        gate_summary = self.gate_service.write_statuses(gate_statuses, run_id=f"clean-next-gate-{partitions[0].affected_partition.source_run_id}" if partitions else "clean-next-gate-empty")
        recalc_events = []
        queue_service = IndicatorRecalcQueueService(lake_root=self.lake_root)
        for status in gate_statuses:
            if status.status != "passed":
                continue
            recalc_events.append(
                queue_service.record_source_partition_replaced(
                    layer="research/stk_mins_by_date_clean_next",
                    freq=status.freq,
                    trade_date=status.trade_date,
                    run_id=status.clean_run_id,
                    written_rows=status.clean_rows,
                )
            )
        return {
            "operation": "refresh_stk_mins_clean_next",
            "mode": "apply",
            "status": overall_status,
            "partitions": len(partitions),
            "partition_results": partition_results,
            "gate": gate_summary,
            "indicator_recalc_events": len(recalc_events),
            "gate_path": str(self.lake_root / CLEAN_NEXT_GATE_RELATIVE_PATH),
            "ledger_path": str(self.lake_root / FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH),
            "write_intent": True,
        }


def _parse_refresh_partition(item: dict[str, Any] | AffectedPartition) -> CleanNextRefreshPartition:
    affected = item if isinstance(item, AffectedPartition) else _affected_partition_from_dict(item)
    if affected.dataset_key != "stk_mins" or affected.source_key != "tushare" or affected.layer != "raw_tushare":
        raise ValueError(
            "clean_next refresh 只接受 stk_mins/tushare/raw_tushare affected partition，"
            f"got dataset_key={affected.dataset_key} source_key={affected.source_key} layer={affected.layer}"
        )
    freq = int(affected.partition_values.get("freq") or 0)
    trade_date = date.fromisoformat(str(affected.partition_values.get("trade_date") or ""))
    return CleanNextRefreshPartition(affected_partition=affected, freq=freq, trade_date=trade_date)


def _affected_partition_from_dict(row: dict[str, Any]) -> AffectedPartition:
    return AffectedPartition(
        dataset_key=str(row.get("dataset_key") or ""),
        source_key=str(row.get("source_key") or ""),
        layer=str(row.get("layer") or ""),
        partition_grain=str(row.get("partition_grain") or ""),
        partition_values={str(key): str(value) for key, value in dict(row.get("partition_values") or {}).items()},
        partition_path=str(row.get("partition_path") or ""),
        source_run_id=str(row.get("source_run_id") or ""),
        write_revision=str(row.get("write_revision") or ""),
        rows_written=int(row.get("rows_written") or 0),
        bytes_written=int(row.get("bytes_written") or 0),
    )
