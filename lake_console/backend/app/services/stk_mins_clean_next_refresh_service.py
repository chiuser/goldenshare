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
from lake_console.backend.app.services.stk_mins_clean_service import (
    FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH,
    FORMAL_CLEAN_RELATIVE_ROOT,
    StkMinsCleanService,
)


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
        recalc_events = []
        derived_rebuild_requirements: dict[int, dict[str, Any]] = {}
        queue_service = IndicatorRecalcQueueService(lake_root=self.lake_root)
        for index, partition in enumerate(partitions, start=1):
            self.progress(
                f"[stk_mins_clean_next] refresh partition={index}/{len(partitions)} "
                f"freq={partition.freq} trade_date={partition.trade_date.isoformat()}"
            )
            clean_partition_path = f"research/stk_mins_by_date_clean_next/freq={partition.freq}/trade_date={partition.trade_date.isoformat()}"
            self.gate_service.write_statuses(
                [
                    CleanNextGateStatus(
                        freq=partition.freq,
                        trade_date=partition.trade_date,
                        clean_partition_path=clean_partition_path,
                        source_run_id=partition.affected_partition.source_run_id,
                        clean_run_id="",
                        write_revision=partition.affected_partition.write_revision,
                        status="publishing",
                        issue_count=0,
                        raw_rows=partition.affected_partition.rows_written,
                        clean_rows=0,
                        ledger_path=str(self.lake_root / FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH),
                        message="publishing clean_next partition before scoped audit",
                    )
                ],
                run_id=_gate_run_id(prefix="clean-next-gate-publishing", partition=partition),
            )
            rebuild = self.clean_service._rebuild_formal_clean_next_from_raw(
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

            final_gate_status = CleanNextGateStatus(
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
            self.gate_service.write_statuses(
                [final_gate_status],
                run_id=_gate_run_id(prefix="clean-next-gate-final", partition=partition),
            )
            gate_statuses.append(final_gate_status)
            if final_gate_status.status == "passed":
                recalc_events.append(
                    queue_service.record_source_partition_replaced(
                        layer="research/stk_mins_by_date_clean_next",
                        freq=final_gate_status.freq,
                        trade_date=final_gate_status.trade_date,
                        run_id=final_gate_status.clean_run_id,
                        written_rows=final_gate_status.clean_rows,
                    )
                )
                _collect_derived_rebuild_requirement(
                    requirements=derived_rebuild_requirements,
                    source_freq=final_gate_status.freq,
                    trade_date=final_gate_status.trade_date,
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

        return {
            "operation": "refresh_stk_mins_clean_next",
            "mode": "apply",
            "status": overall_status,
            "partitions": len(partitions),
            "partition_results": partition_results,
            "gate": {
                "path": str(self.lake_root / CLEAN_NEXT_GATE_RELATIVE_PATH),
                "updated_partitions": len(gate_statuses),
                "written_rows": len(self.gate_service.read_statuses()),
            },
            "indicator_recalc_events": len(recalc_events),
            "derived_rebuild_required": bool(derived_rebuild_requirements),
            "derived_rebuild_requirements": _format_derived_rebuild_requirements(derived_rebuild_requirements),
            "gate_path": str(self.lake_root / CLEAN_NEXT_GATE_RELATIVE_PATH),
            "ledger_path": str(self.lake_root / FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH),
            "write_intent": True,
        }

    def refresh_raw_range(
        self,
        *,
        freqs: list[int],
        start_date: date | None,
        end_date: date | None,
        dry_run: bool,
        apply: bool,
        replace_existing: bool,
        sample_limit: int = 20,
    ) -> dict[str, Any]:
        if dry_run == apply:
            raise ValueError("clean_next range refresh 必须且只能指定 dry_run 或 apply。")
        if dry_run:
            return self.clean_service.plan_rebuild_formal_clean_next(
                freqs=freqs,
                start_date=start_date,
                end_date=end_date,
                sample_limit=sample_limit,
            )

        partitions = self.clean_service._discover_partitions(
            layer="raw_tushare",
            freqs=freqs,
            start_date=start_date,
            end_date=end_date,
            include_metadata=True,
        )
        existing_targets = [
            partition
            for partition in partitions
            if (self.lake_root / FORMAL_CLEAN_RELATIVE_ROOT / f"freq={partition.freq}" / f"trade_date={partition.trade_date.isoformat()}").exists()
        ]
        if existing_targets and not replace_existing:
            preview = ", ".join(
                f"freq={item.freq}/trade_date={item.trade_date.isoformat()}" for item in existing_targets[:10]
            )
            raise RuntimeError(
                "正式 clean_next 目标分区已存在，拒绝覆盖。"
                f" existing={len(existing_targets)} preview={preview}；"
                "如确认要重建并发布，请显式传 --replace-existing。"
            )

        run_id = _range_run_id()
        affected_partitions = [
            AffectedPartition(
                dataset_key="stk_mins",
                source_key="tushare",
                layer="raw_tushare",
                partition_grain="trade_date",
                partition_values={"freq": str(partition.freq), "trade_date": partition.trade_date.isoformat()},
                partition_path=str(partition.path.relative_to(self.lake_root)),
                source_run_id=run_id,
                write_revision=f"{run_id}:raw_tushare_existing:freq={partition.freq}:trade_date={partition.trade_date.isoformat()}",
                rows_written=partition.row_count,
                bytes_written=partition.byte_count,
            )
            for partition in partitions
        ]
        refresh = self.refresh(affected_partitions=affected_partitions, dry_run=False, apply=True)
        refresh.update(
            {
                "operation": "refresh_stk_mins_clean_next_from_existing_raw_range",
                "freqs": freqs,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "replace_existing": replace_existing,
                "raw_partitions": len(partitions),
            }
        )
        return refresh


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


def _collect_derived_rebuild_requirement(
    *,
    requirements: dict[int, dict[str, Any]],
    source_freq: int,
    trade_date: date,
) -> None:
    target_freq_by_source = {30: 90, 60: 120}
    target_freq = target_freq_by_source.get(source_freq)
    if target_freq is None:
        return
    item = requirements.setdefault(
        target_freq,
        {
            "source_freq": source_freq,
            "target_freq": target_freq,
            "start_date": trade_date,
            "end_date": trade_date,
        },
    )
    item["start_date"] = min(item["start_date"], trade_date)
    item["end_date"] = max(item["end_date"], trade_date)


def _format_derived_rebuild_requirements(requirements: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for target_freq in sorted(requirements):
        item = dict(requirements[target_freq])
        start_date = item["start_date"]
        end_date = item["end_date"]
        item["start_date"] = start_date.isoformat()
        item["end_date"] = end_date.isoformat()
        item["command"] = (
            "lake_console/.venv/bin/python -m lake_console.backend.app.cli "
            "rebuild-stk-mins-derived-from-clean-range "
            f"--target-freqs {target_freq} "
            f"--start-date {start_date.isoformat()} "
            f"--end-date {end_date.isoformat()}"
        )
        formatted.append(item)
    return formatted


def _range_run_id() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-refresh-stk-mins-clean-next-range"


def _gate_run_id(*, prefix: str, partition: CleanNextRefreshPartition) -> str:
    source_run_id = partition.affected_partition.source_run_id or "unknown-source-run"
    return f"{prefix}-{source_run_id}-freq-{partition.freq}-trade-date-{partition.trade_date.isoformat()}"
