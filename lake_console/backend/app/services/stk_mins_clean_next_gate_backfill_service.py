from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.stk_mins_clean_next_gate import CleanNextGateStatus, CleanNextPartitionGateService, clean_next_partition_key
from lake_console.backend.app.services.stk_mins_clean_service import FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH, StkMinsCleanService, _identity_by_latest
from lake_console.backend.app.sync.helpers.dates import load_open_trade_dates


class StkMinsCleanNextGateBackfillService:
    """Backfill gate records for existing clean_next partitions.

    This service only reads research/stk_mins_by_date_clean_next and writes:
    - manifest/stk_mins_quality/clean_next_partition_gate.parquet
    - manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet

    It never rewrites raw, clean_next, derived, research, or indicator data.
    """

    def __init__(self, *, lake_root: Path, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or (lambda message: print(message, flush=True))
        self.clean_service = StkMinsCleanService(lake_root=lake_root, progress=progress)
        self.gate_service = CleanNextPartitionGateService(lake_root=lake_root)

    def backfill(
        self,
        *,
        freqs: list[int],
        start_date: date,
        end_date: date,
        dry_run: bool,
        apply: bool,
        refresh_existing: bool = False,
        sample_limit: int = 20,
    ) -> dict[str, Any]:
        if dry_run == apply:
            raise ValueError("clean_next gate backfill 必须且只能指定 dry_run 或 apply。")
        if end_date < start_date:
            raise ValueError("end-date 不能早于 start-date。")
        if not freqs:
            raise ValueError("clean_next gate backfill 必须至少指定一个 freq。")
        if apply:
            LakeRootService(self.lake_root).require_ready_for_write()

        run_id = _run_id("backfill-stk-mins-clean-next-gate")
        started = time.monotonic()
        identity_by_source, identity_diagnostics = self.clean_service._load_or_build_identity_map()
        identity_by_latest = _identity_by_latest(identity_by_source.values())
        existing_gate_keys = {
            str(row.get("partition_key") or "")
            for row in self.gate_service.read_statuses()
            if str(row.get("partition_key") or "")
        }
        partitions = self.clean_service._discover_partitions(
            layer="formal_clean_next",
            freqs=freqs,
            start_date=start_date,
            end_date=end_date,
            include_metadata=True,
        )
        missing_partition_keys = _missing_partition_keys(
            lake_root=self.lake_root,
            freqs=freqs,
            start_date=start_date,
            end_date=end_date,
        )
        target_partitions = [
            partition
            for partition in partitions
            if refresh_existing or clean_next_partition_key(freq=partition.freq, trade_date=partition.trade_date) not in existing_gate_keys
        ]

        self.progress(
            f"[backfill_stk_mins_clean_next_gate] start run_id={run_id} mode={'apply' if apply else 'dry_run'} "
            f"freqs={','.join(str(item) for item in freqs)} start_date={start_date.isoformat()} "
            f"end_date={end_date.isoformat()} partitions={len(target_partitions)} refresh_existing={refresh_existing}"
        )

        issue_records: list[dict[str, Any]] = []
        gate_statuses: list[CleanNextGateStatus] = []
        status_counts: Counter[str] = Counter()
        issue_type_counts: Counter[str] = Counter()
        samples: list[dict[str, Any]] = []
        audited_partition_keys: list[str] = []

        for index, partition in enumerate(target_partitions, start=1):
            partition_key = clean_next_partition_key(freq=partition.freq, trade_date=partition.trade_date)
            audited_partition_keys.append(partition_key)
            basic_records = self.clean_service._audit_formal_clean_next_partition_basic(
                partition=partition,
                identity_by_latest=identity_by_latest,
            )
            completeness_records = self.clean_service._audit_formal_clean_next_partition_completeness(
                partition=partition,
                identity_by_latest=identity_by_latest,
            )
            partition_issues = basic_records + completeness_records
            issue_records.extend(partition_issues)
            for record in partition_issues:
                issue_type_counts[str(record.get("issue_type") or "")] += 1
                if len(samples) < sample_limit:
                    samples.append(record)

            partition_status = "passed" if not partition_issues else "blocked"
            status_counts[partition_status] += 1
            gate_statuses.append(
                CleanNextGateStatus(
                    freq=partition.freq,
                    trade_date=partition.trade_date,
                    clean_partition_path=str(partition.path.relative_to(self.lake_root)),
                    source_run_id=run_id,
                    clean_run_id=run_id,
                    write_revision=f"{run_id}:clean_next_gate_backfill:{partition_key}",
                    status=partition_status,
                    issue_count=len(partition_issues),
                    raw_rows=0,
                    clean_rows=partition.row_count,
                    ledger_path=str(self.lake_root / FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH),
                    message="backfilled from existing clean_next partition" if partition_status == "passed" else "blocked by clean_next backfill audit",
                )
            )
            if index == 1 or index == len(target_partitions) or index % 100 == 0 or partition_issues:
                self.progress(
                    f"[backfill_stk_mins_clean_next_gate] partition={index}/{len(target_partitions)} "
                    f"{partition_key} status={partition_status} issues={len(partition_issues)} rows={partition.row_count}"
                )

        ledger_summary = None
        gate_summary = None
        if apply:
            ledger_summary = self.clean_service._write_clean_issue_ledger_to_path(
                issue_records=issue_records,
                ledger_relative_path=FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH,
                run_label="stk-mins-clean-next-gate-backfill-ledger",
                audited_partition_keys=audited_partition_keys,
            )
            gate_summary = self.gate_service.write_statuses(gate_statuses, run_id=run_id)

        elapsed = time.monotonic() - started
        return {
            "operation": "backfill_stk_mins_clean_next_gate",
            "mode": "apply" if apply else "dry_run",
            "run_id": run_id,
            "lake_root": str(self.lake_root),
            "freqs": freqs,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "discovered_partitions": len(partitions),
            "skipped_existing_gate_partitions": len(partitions) - len(target_partitions),
            "audited_partitions": len(target_partitions),
            "missing_clean_next_partitions": len(missing_partition_keys),
            "missing_clean_next_samples": missing_partition_keys[:sample_limit],
            "passed_partitions": int(status_counts.get("passed", 0)),
            "blocked_partitions": int(status_counts.get("blocked", 0)),
            "issue_count": len(issue_records),
            "issue_type_counts": dict(sorted(issue_type_counts.items())),
            "identity_diagnostics": identity_diagnostics,
            "samples": samples,
            "ledger": ledger_summary,
            "gate": gate_summary,
            "write_intent": apply,
            "elapsed_seconds": round(elapsed, 3),
        }


def _missing_partition_keys(*, lake_root: Path, freqs: list[int], start_date: date, end_date: date) -> list[str]:
    missing: list[str] = []
    root = lake_root / "research" / "stk_mins_by_date_clean_next"
    try:
        trade_dates = load_open_trade_dates(lake_root=lake_root, start_date=start_date, end_date=end_date)
    except RuntimeError:
        return missing
    for current in trade_dates:
        for freq in freqs:
            partition = root / f"freq={freq}" / f"trade_date={current.isoformat()}"
            if not partition.exists():
                missing.append(clean_next_partition_key(freq=freq, trade_date=current))
    return missing


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
