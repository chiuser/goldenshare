from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from lake_console.backend.app.services.duckdb_compute_plan_service import (
    _latest_partition_files,
    _normalize_freqs,
    _parse_date,
    _partition_file_map,
    _read_parquet_metadata,
    _relpath,
)
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.services.stk_mins_clean_next_gate import CleanNextPartitionGateService
from lake_console.backend.app.settings import LakeConsoleSettings


ACTIVE_RUN_STATUSES = {
    "planned",
    "running",
    "compute_completed",
    "audit_running",
    "prewrite_backup",
    "publishing",
}
REVIEW_RUN_STATUSES = {"blocked", "failed"}


class DuckDbComputeReadinessService:
    """Run read-only checks before expensive qfq candidate generation."""

    def __init__(self, *, settings: LakeConsoleSettings) -> None:
        self.settings = settings
        self.lake_root = settings.lake_root.resolve()

    def scan_stk_mins_qfq_readiness(
        self,
        *,
        start_date: str,
        end_date: str,
        freqs: Iterable[int],
    ) -> dict[str, Any]:
        range_start = _parse_date(start_date, label="start_date")
        range_end = _parse_date(end_date, label="end_date")
        if range_start > range_end:
            raise ValueError(f"start_date 不能晚于 end_date：{start_date} > {end_date}")
        selected_freqs = _normalize_freqs(freqs)

        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        clean_scan = self._scan_clean_next_partitions(start=range_start, end=range_end, freqs=selected_freqs, blockers=blockers)
        adj_scan = self._scan_adj_factor_partitions(start=range_start, end=range_end, clean_scan=clean_scan, blockers=blockers)
        latest_adj_scan = self._scan_latest_adj_factor(blockers=blockers)
        identity_scan = self._scan_identity_map(blockers=blockers, warnings=warnings)
        self._scan_latest_factor_identity_coverage(latest_adj_scan=latest_adj_scan, identity_scan=identity_scan, warnings=warnings)
        lock = self._scan_lock(blockers=blockers)
        run_scan = self._scan_existing_runs(blockers=blockers, warnings=warnings)
        gate_scan = self._scan_existing_gates(blockers=blockers, warnings=warnings)
        disk_scan = self._scan_disk(clean_scan=clean_scan, blockers=blockers, warnings=warnings)
        temp_scan = self._scan_duckdb_temp_directory(blockers=blockers)

        return {
            "operation": "readiness-stk-mins-qfq",
            "ready": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "range": {
                "start_date": range_start.isoformat(),
                "end_date": range_end.isoformat(),
                "freqs": selected_freqs,
            },
            "checks": {
                "clean_next": _public_clean_scan(clean_scan),
                "adj_factor": adj_scan,
                "latest_adj_factor": latest_adj_scan,
                "security_identity_map": identity_scan,
                "disk": disk_scan,
                "duckdb_temp_directory": temp_scan,
                "lock": lock,
                "existing_runs": run_scan,
                "formal_gate": gate_scan,
            },
            "notes": [
                "本命令只读，不创建 run manifest，不写 _tmp candidate，不替换正式 clean_next。",
                "本命令做分区级 adj_factor 覆盖检查；逐行 qfq factor coverage 仍由 compute unit 执行阶段强制拦截。",
            ],
        }

    def _scan_clean_next_partitions(
        self,
        *,
        start: date,
        end: date,
        freqs: list[int],
        blockers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        root = self.lake_root / "research" / "stk_mins_by_date_clean_next"
        by_freq: list[dict[str, Any]] = []
        total_partitions = 0
        total_files = 0
        total_rows = 0
        total_bytes = 0
        partition_key_samples: list[str] = []
        clean_dates_by_freq: dict[int, set[date]] = {}
        for freq in freqs:
            freq_root = root / f"freq={freq}"
            partitions = _partition_file_map(freq_root, "trade_date", start, end)
            clean_dates_by_freq[freq] = set(partitions)
            file_count = 0
            row_count = 0
            byte_count = 0
            metadata_errors: list[str] = []
            for trade_date, files in sorted(partitions.items()):
                if len(partition_key_samples) < 20:
                    partition_key_samples.append(f"freq={freq}/trade_date={trade_date.isoformat()}")
                file_count += len(files)
                for file in files:
                    try:
                        metadata = _read_parquet_metadata(file)
                    except Exception as exc:  # pragma: no cover - defensive branch for corrupted local files
                        metadata_errors.append(f"{_relpath(file, self.lake_root)}: {exc}")
                        continue
                    row_count += int(metadata["row_count"])
                    byte_count += file.stat().st_size
            if metadata_errors:
                blockers.append(
                    {
                        "code": "clean_next_metadata_unreadable",
                        "message": f"clean_next 分区存在不可读取的 Parquet metadata：freq={freq}",
                        "samples": metadata_errors[:5],
                    }
                )
            if not partitions:
                blockers.append(
                    {
                        "code": "missing_clean_next_partition",
                        "message": f"指定范围内没有 clean_next 分区：freq={freq}",
                        "path": _relpath(freq_root, self.lake_root),
                    }
                )
            by_freq.append(
                {
                    "freq": freq,
                    "partition_count": len(partitions),
                    "file_count": file_count,
                    "row_count": row_count,
                    "byte_count": byte_count,
                    "earliest_trade_date": min(partitions).isoformat() if partitions else None,
                    "latest_trade_date": max(partitions).isoformat() if partitions else None,
                }
            )
            total_partitions += len(partitions)
            total_files += file_count
            total_rows += row_count
            total_bytes += byte_count
        return {
            "root": _relpath(root, self.lake_root),
            "by_freq": by_freq,
            "partition_count": total_partitions,
            "file_count": total_files,
            "row_count": total_rows,
            "byte_count": total_bytes,
            "partition_key_samples": partition_key_samples,
            "_dates_by_freq": clean_dates_by_freq,
        }

    def _scan_adj_factor_partitions(
        self,
        *,
        start: date,
        end: date,
        clean_scan: dict[str, Any],
        blockers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        root = self.lake_root / "raw_tushare" / "adj_factor"
        adj_by_date = _partition_file_map(root, "trade_date", start, end)
        target_dates = sorted(set().union(*clean_scan["_dates_by_freq"].values())) if clean_scan["_dates_by_freq"] else []
        missing_dates = [item for item in target_dates if item not in adj_by_date]
        if missing_dates:
            blockers.append(
                {
                    "code": "missing_adj_factor_partition",
                    "message": "存在 clean_next 目标日期缺少同日 adj_factor 分区，不能进入 qfq candidate compute。",
                    "missing_count": len(missing_dates),
                    "samples": [item.isoformat() for item in missing_dates[:10]],
                }
            )
        file_count = sum(len(files) for files in adj_by_date.values())
        byte_count = sum(file.stat().st_size for files in adj_by_date.values() for file in files)
        return {
            "root": _relpath(root, self.lake_root),
            "partition_count": len(adj_by_date),
            "file_count": file_count,
            "byte_count": byte_count,
            "target_trade_date_count": len(target_dates),
            "missing_target_trade_date_count": len(missing_dates),
            "missing_target_trade_date_samples": [item.isoformat() for item in missing_dates[:20]],
        }

    def _scan_latest_adj_factor(self, *, blockers: list[dict[str, Any]]) -> dict[str, Any]:
        root = self.lake_root / "raw_tushare" / "adj_factor"
        latest_root, files = _latest_partition_files(root, "trade_date")
        if latest_root is None or not files:
            blockers.append(
                {
                    "code": "missing_latest_adj_factor_partition",
                    "message": "缺少 adj_factor 最新分区，无法计算前复权基准。",
                    "path": _relpath(root, self.lake_root),
                }
            )
            return {"root": _relpath(root, self.lake_root), "latest_trade_date": None, "file_count": 0, "row_count": 0}
        row_count = 0
        for file in files:
            row_count += int(_read_parquet_metadata(file)["row_count"])
        return {
            "root": _relpath(root, self.lake_root),
            "latest_partition": _relpath(latest_root, self.lake_root),
            "latest_trade_date": latest_root.name.removeprefix("trade_date="),
            "file_count": len(files),
            "row_count": row_count,
            "byte_count": sum(file.stat().st_size for file in files),
        }

    def _scan_identity_map(self, *, blockers: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
        path = self.lake_root / "manifest" / "security_identity" / "security_identity_map.parquet"
        if not path.exists():
            blockers.append(
                {
                    "code": "missing_security_identity_map",
                    "message": "缺少 security_identity_map，无法确认股票代码归一化账本。",
                    "path": _relpath(path, self.lake_root),
                }
            )
            return {"path": _relpath(path, self.lake_root), "exists": False, "row_count": 0, "latest_code_count": 0}
        rows = read_parquet_rows(path)
        latest_codes = _identity_latest_codes(rows)
        if not latest_codes:
            warnings.append(
                {
                    "code": "security_identity_map_no_latest_codes",
                    "message": "security_identity_map 可读，但未识别到 latest_ts_code/ts_code/source_ts_code 字段。",
                    "path": _relpath(path, self.lake_root),
                }
            )
        return {
            "path": _relpath(path, self.lake_root),
            "exists": True,
            "row_count": len(rows),
            "latest_code_count": len(latest_codes),
        }

    def _scan_latest_factor_identity_coverage(
        self,
        *,
        latest_adj_scan: dict[str, Any],
        identity_scan: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> None:
        if not latest_adj_scan.get("latest_partition") or not identity_scan.get("exists"):
            return
        latest_root = self.lake_root / str(latest_adj_scan["latest_partition"])
        identity_path = self.lake_root / str(identity_scan["path"])
        latest_rows: list[dict[str, Any]] = []
        for file in sorted(latest_root.glob("*.parquet")):
            latest_rows.extend(read_parquet_rows(file))
        latest_codes = {str(row.get("ts_code") or "") for row in latest_rows if row.get("ts_code")}
        identity_codes = _identity_latest_codes(read_parquet_rows(identity_path))
        missing = sorted(identity_codes - latest_codes)
        if missing:
            warnings.append(
                {
                    "code": "latest_adj_factor_missing_identity_codes",
                    "message": "最新 adj_factor 未覆盖部分 identity map 最新代码；compute 阶段会按实际行级 join 再强制拦截。",
                    "missing_count": len(missing),
                    "samples": missing[:20],
                }
            )

    def _scan_disk(
        self,
        *,
        clean_scan: dict[str, Any],
        blockers: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        usage = os.statvfs(self.lake_root)
        total_bytes = usage.f_blocks * usage.f_frsize
        free_bytes = usage.f_bavail * usage.f_frsize
        used_bytes = total_bytes - free_bytes
        clean_bytes = int(clean_scan["byte_count"])
        estimated_candidate_bytes = int(clean_bytes * 1.1)
        safety_margin_bytes = max(10 * 1024**3, int(estimated_candidate_bytes * 0.15))
        required_free_bytes = estimated_candidate_bytes + safety_margin_bytes
        if clean_bytes > 0 and free_bytes < required_free_bytes:
            blockers.append(
                {
                    "code": "insufficient_candidate_disk_space",
                    "message": "可用空间不足以安全生成 qfq candidate。",
                    "free_bytes": free_bytes,
                    "required_free_bytes": required_free_bytes,
                    "estimated_candidate_bytes": estimated_candidate_bytes,
                }
            )
        elif clean_bytes > 0 and free_bytes < int(required_free_bytes * 1.25):
            warnings.append(
                {
                    "code": "candidate_disk_space_low_margin",
                    "message": "可用空间能覆盖估算 candidate，但安全余量偏低。",
                    "free_bytes": free_bytes,
                    "required_free_bytes": required_free_bytes,
                    "estimated_candidate_bytes": estimated_candidate_bytes,
                }
            )
        return {
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "free_bytes": free_bytes,
            "clean_next_target_bytes": clean_bytes,
            "estimated_candidate_bytes": estimated_candidate_bytes,
            "safety_margin_bytes": safety_margin_bytes,
            "required_free_bytes": required_free_bytes,
        }

    def _scan_duckdb_temp_directory(self, *, blockers: list[dict[str, Any]]) -> dict[str, Any]:
        raw_path = Path(self.settings.duckdb_temp_directory).expanduser()
        resolved = raw_path.resolve() if raw_path.is_absolute() else (self.lake_root / raw_path).resolve()
        if resolved != self.lake_root and self.lake_root not in resolved.parents:
            blockers.append(
                {
                    "code": "duckdb_temp_directory_outside_lake",
                    "message": "DuckDB temp_directory 不在 Lake Root 内，可能把 spill 写到系统盘。",
                    "path": str(resolved),
                }
            )
        return {
            "configured": self.settings.duckdb_temp_directory,
            "resolved": str(resolved),
            "inside_lake_root": resolved == self.lake_root or self.lake_root in resolved.parents,
        }

    def _scan_lock(self, *, blockers: list[dict[str, Any]]) -> dict[str, Any]:
        lock = LakeJobLockService(
            LakeJobStateStore(self.lake_root),
            stale_after_seconds=self.settings.compute_stale_heartbeat_seconds,
        ).get_lock()
        if lock.get("status") in {"running", "stale"}:
            blockers.append(
                {
                    "code": "lake_write_lock_active",
                    "message": "当前存在 Lake 写入锁，不能启动 qfq candidate 全量计算。",
                    "lock": lock,
                }
            )
        return lock

    def _scan_existing_runs(self, *, blockers: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
        runs_root = self.lake_root / "manifest" / "duckdb_compute" / "runs"
        active: list[dict[str, Any]] = []
        needs_review: list[dict[str, Any]] = []
        if runs_root.exists():
            for run_file in sorted(runs_root.glob("*/run.json")):
                try:
                    payload = json.loads(run_file.read_text(encoding="utf-8"))
                except Exception as exc:  # pragma: no cover - defensive branch for corrupted local files
                    needs_review.append(
                        {
                            "run_path": _relpath(run_file, self.lake_root),
                            "status": "unreadable",
                            "message": str(exc),
                        }
                    )
                    continue
                if payload.get("job_type") != "stk_mins_qfq_clean_next":
                    continue
                item = {
                    "run_id": payload.get("run_id"),
                    "status": payload.get("status"),
                    "path": _relpath(run_file, self.lake_root),
                    "created_at": payload.get("created_at"),
                    "input_range": payload.get("input_range"),
                }
                status = str(payload.get("status") or "")
                if status in ACTIVE_RUN_STATUSES:
                    active.append(item)
                elif status in REVIEW_RUN_STATUSES:
                    needs_review.append(item)
        if active:
            blockers.append(
                {
                    "code": "active_qfq_compute_run_exists",
                    "message": "存在未完成的 qfq compute run，先处理或确认后再启动新的全量 candidate。",
                    "runs": active[:10],
                }
            )
        if needs_review:
            warnings.append(
                {
                    "code": "qfq_compute_runs_need_review",
                    "message": "存在 blocked/failed/unreadable 的历史 qfq run，建议人工确认后再全量跑数。",
                    "runs": needs_review[:10],
                }
            )
        return {
            "root": _relpath(runs_root, self.lake_root),
            "active_count": len(active),
            "needs_review_count": len(needs_review),
            "active_runs": active[:20],
            "needs_review_runs": needs_review[:20],
        }

    def _scan_existing_gates(self, *, blockers: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
        rows = CleanNextPartitionGateService(lake_root=self.lake_root).read_statuses()
        status_counts: dict[str, int] = {}
        publishing: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for row in rows:
            status = str(row.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            if status == "publishing":
                publishing.append(row)
            elif status == "blocked":
                blocked.append(row)
        if publishing:
            blockers.append(
                {
                    "code": "formal_gate_publishing_exists",
                    "message": "clean_next gate 中存在 publishing 分区，说明已有发布窗口未收口。",
                    "samples": [_gate_sample(row) for row in publishing[:10]],
                }
            )
        if blocked:
            warnings.append(
                {
                    "code": "formal_gate_blocked_exists",
                    "message": "clean_next gate 中存在 blocked 分区；不阻止 candidate 计算，但发布前需要确认。",
                    "samples": [_gate_sample(row) for row in blocked[:10]],
                }
            )
        return {
            "path": _relpath(CleanNextPartitionGateService(lake_root=self.lake_root).gate_file, self.lake_root),
            "row_count": len(rows),
            "status_counts": status_counts,
            "publishing_count": len(publishing),
            "blocked_count": len(blocked),
        }


def _identity_latest_codes(rows: list[dict[str, Any]]) -> set[str]:
    codes: set[str] = set()
    for row in rows:
        value = row.get("latest_ts_code") or row.get("ts_code") or row.get("source_ts_code")
        if value:
            codes.add(str(value))
    return codes


def _public_clean_scan(scan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in scan.items() if not key.startswith("_")}


def _gate_sample(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "partition_key": row.get("partition_key"),
        "status": row.get("status"),
        "write_revision": row.get("write_revision"),
        "message": row.get("message"),
    }
