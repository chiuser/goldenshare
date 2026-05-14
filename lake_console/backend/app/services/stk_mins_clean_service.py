from __future__ import annotations

import shutil
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.tushare_stk_mins import STK_MINS_FIELDS
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    replace_directory_atomically,
    replace_file_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


RAW_FREQS = {1, 5, 15, 30, 60}
INTRADAY_EXPECTED_BAR_COUNT = {1: 241, 5: 49, 15: 17, 30: 9, 60: 5}
INTRADAY_AFTER_HOURS_BAR_COUNT = {1: 30, 5: 6, 15: 2, 30: 1, 60: 1}
FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH = Path("manifest") / "stk_mins_quality" / "clean_next_completeness_issue_ledger.parquet"
FORMAL_ISSUE_LEDGER_SCHEMA_VERSION = 2
ISSUE_LEDGER_FIELDS = (
    "issue_id",
    "gate",
    "issue_type",
    "status",
    "latest_ts_code",
    "freq",
    "trade_date",
    "trade_time",
    "expected_value",
    "actual_value",
    "evidence_dataset",
    "evidence_ref",
    "action",
    "reason",
    "created_at",
    "resolved_at",
)
FORMAL_ISSUE_LEDGER_FIELDS = (
    "ledger_schema_version",
    "issue_key",
    "issue_state",
    "severity",
    "dataset_key",
    "source_key",
    "layer",
    "partition_key",
    "freq",
    "trade_date",
    "trade_time",
    "latest_ts_code",
    "issue_type",
    "expected_value",
    "actual_value",
    "evidence_dataset",
    "evidence_ref",
    "action",
    "reason",
    "first_seen_run_id",
    "last_seen_run_id",
    "resolved_run_id",
    "first_seen_at",
    "last_seen_at",
    "resolved_at",
    "seen_count",
    "superseded_by_issue_key",
)
FORMAL_CLEAN_STK_MINS_FIELDS = STK_MINS_FIELDS
FORMAL_CLEAN_RELATIVE_ROOT = Path("research") / "stk_mins_by_date_clean_next"


@dataclass(frozen=True)
class StkMinsPartition:
    freq: int
    trade_date: date
    path: Path
    files: tuple[Path, ...]
    row_count: int
    byte_count: int


@dataclass(frozen=True)
class StkMinsCleanBuildResult:
    stats: dict[str, Any]
    frame: Any | None = None


class StkMinsCleanService:
    """Build and audit the formal clean_next stk_mins by_date fact layer."""

    def __init__(self, *, lake_root: Path, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or (lambda message: print(message, flush=True))

    def build_security_identity_map(self, *, dry_run: bool, apply: bool, sample_limit: int = 20) -> dict[str, Any]:
        if dry_run == apply:
            raise ValueError("security identity map 必须且只能指定 dry_run 或 apply。")
        rows, diagnostics = self._build_identity_rows()
        summary: dict[str, Any] = {
            "operation": "build_stk_mins_security_identity_map",
            "mode": "apply" if apply else "dry_run",
            "lake_root": str(self.lake_root),
            "identity_rows": len(rows),
            "source_ts_code_count": len({row["source_ts_code"] for row in rows}),
            "canonical_ts_code_count": len({row["latest_ts_code"] for row in rows}),
            "diagnostics": diagnostics,
            "samples": rows[:sample_limit],
            "write_intent": apply,
        }
        if dry_run:
            return summary
        LakeRootService(self.lake_root).require_ready_for_write()
        run_id = _run_id("security-identity-map")
        tmp_file = self.lake_root / "_tmp" / run_id / "manifest" / "security_identity" / "security_identity_map.parquet"
        final_file = self.lake_root / "manifest" / "security_identity" / "security_identity_map.parquet"
        backup_root = self.lake_root / "_tmp" / run_id / "_backup" / "security_identity"
        written = write_rows_to_parquet(rows, tmp_file)
        validated = read_parquet_row_count(tmp_file)
        if written != validated:
            raise RuntimeError(f"security_identity_map 校验失败：written={written} validated={validated}")
        replace_file_atomically(tmp_file=tmp_file, final_file=final_file, backup_root=backup_root)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        summary.update({"run_id": run_id, "written_rows": written, "output": str(final_file)})
        return summary

    def audit_formal_clean_next_layer(
        self,
        *,
        freqs: list[int],
        start_date: date | None = None,
        end_date: date | None = None,
        sample_limit: int = 20,
    ) -> dict[str, Any]:
        _validate_freqs(freqs)
        identity_by_source, diagnostics = self._load_or_build_identity_map()
        identity_by_latest = _identity_by_latest(identity_by_source.values())
        partitions = self._discover_partitions(
            layer="formal_clean_next",
            freqs=freqs,
            start_date=start_date,
            end_date=end_date,
            include_metadata=False,
        )
        issue_records: list[dict[str, Any]] = []
        issue_type_counts: Counter[str] = Counter()
        status_counts: Counter[str] = Counter()
        samples: list[dict[str, Any]] = []
        self.progress(f"[audit_stk_mins_clean_next] start partitions={len(partitions)}")
        for index, partition in enumerate(partitions, start=1):
            records = self._audit_formal_clean_next_partition_basic(
                partition=partition,
                identity_by_latest=identity_by_latest,
            )
            issue_records.extend(records)
            for record in records:
                issue_type_counts[str(record["issue_type"])] += 1
                status_counts[str(record["status"])] += 1
                if len(samples) < sample_limit:
                    samples.append(record)
            if index == 1 or index == len(partitions) or index % 250 == 0 or records:
                self.progress(
                    f"[audit_stk_mins_clean_next] partition={index}/{len(partitions)} "
                    f"freq={partition.freq} trade_date={partition.trade_date.isoformat()} issues={len(records)}"
                )

        return {
            "operation": "audit_stk_mins_by_date_clean_next",
            "mode": "read_only",
            "lake_root": str(self.lake_root),
            "dataset_layer": str(FORMAL_CLEAN_RELATIVE_ROOT),
            "freqs": freqs,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "partitions": len(partitions),
            "issue_count": len(issue_records),
            "issue_type_counts": dict(sorted(issue_type_counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
            "identity_diagnostics": diagnostics,
            "status": _global_audit_status(status_counts),
            "schema": list(FORMAL_CLEAN_STK_MINS_FIELDS),
            "samples": samples,
            "write_intent": False,
        }

    def audit_formal_clean_next_completeness(
        self,
        *,
        freqs: list[int],
        start_date: date | None = None,
        end_date: date | None = None,
        sample_limit: int = 20,
        write_ledger: bool = False,
    ) -> dict[str, Any]:
        _validate_freqs(freqs)
        identity_by_source, diagnostics = self._load_or_build_identity_map()
        identity_by_latest = _identity_by_latest(identity_by_source.values())
        partitions = self._discover_partitions(
            layer="formal_clean_next",
            freqs=freqs,
            start_date=start_date,
            end_date=end_date,
            include_metadata=False,
        )
        issue_records: list[dict[str, Any]] = []
        issue_type_counts: Counter[str] = Counter()
        status_counts: Counter[str] = Counter()
        samples: list[dict[str, Any]] = []
        self.progress(
            f"[audit_stk_mins_clean_next_completeness] start partitions={len(partitions)} write_ledger={write_ledger}"
        )
        for index, partition in enumerate(partitions, start=1):
            records = self._audit_formal_clean_next_partition_completeness(
                partition=partition,
                identity_by_latest=identity_by_latest,
            )
            issue_records.extend(records)
            for record in records:
                issue_type_counts[str(record["issue_type"])] += 1
                status_counts[str(record["status"])] += 1
                if len(samples) < sample_limit:
                    samples.append(record)
            if index == 1 or index == len(partitions) or index % 250 == 0 or records:
                self.progress(
                    f"[audit_stk_mins_clean_next_completeness] partition={index}/{len(partitions)} "
                    f"freq={partition.freq} trade_date={partition.trade_date.isoformat()} issues={len(records)}"
                )

        ledger_summary = None
        if write_ledger:
            ledger_summary = self._write_clean_issue_ledger_to_path(
                issue_records=issue_records,
                ledger_relative_path=FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH,
                run_label="stk-mins-clean-next-issue-ledger",
                audited_partition_keys=[_partition_key(partition.freq, partition.trade_date) for partition in partitions],
            )

        return {
            "operation": "audit_stk_mins_clean_next_completeness",
            "mode": "write_ledger" if write_ledger else "read_only",
            "lake_root": str(self.lake_root),
            "dataset_layer": str(FORMAL_CLEAN_RELATIVE_ROOT),
            "freqs": freqs,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "partitions": len(partitions),
            "issue_count": len(issue_records),
            "issue_type_counts": dict(sorted(issue_type_counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
            "identity_diagnostics": diagnostics,
            "status": _global_audit_status(status_counts),
            "samples": samples,
            "write_intent": write_ledger,
            "ledger": ledger_summary,
        }

    def plan_rebuild_formal_clean_next(
        self,
        *,
        freqs: list[int],
        start_date: date | None = None,
        end_date: date | None = None,
        sample_limit: int = 20,
    ) -> dict[str, Any]:
        _validate_freqs(freqs)
        identity_by_source, diagnostics = self._load_or_build_identity_map()
        partitions = self._discover_partitions(
            layer="raw_tushare",
            freqs=freqs,
            start_date=start_date,
            end_date=end_date,
            include_metadata=False,
        )
        return self._summarize_formal_clean_next_rules(
            operation="rebuild_stk_mins_by_date_clean_next",
            partitions=partitions,
            identity_by_source=identity_by_source,
            diagnostics=diagnostics,
            sample_limit=sample_limit,
        )

    def _rebuild_formal_clean_next_from_raw(
        self,
        *,
        freqs: list[int],
        start_date: date | None = None,
        end_date: date | None = None,
        dry_run: bool,
        apply: bool,
        replace_existing: bool = False,
        sample_limit: int = 20,
    ) -> dict[str, Any]:
        if dry_run == apply:
            raise ValueError("正式 clean rebuild 必须且只能指定 dry_run 或 apply。")
        if dry_run:
            return self.plan_rebuild_formal_clean_next(
                freqs=freqs,
                start_date=start_date,
                end_date=end_date,
                sample_limit=sample_limit,
            )

        _validate_freqs(freqs)
        LakeRootService(self.lake_root).require_ready_for_write()
        identity_by_source, diagnostics = self._load_or_build_identity_map()
        partitions = self._discover_partitions(
            layer="raw_tushare",
            freqs=freqs,
            start_date=start_date,
            end_date=end_date,
            include_metadata=False,
        )
        existing_targets = [
            partition
            for partition in partitions
            if self._formal_clean_next_partition(freq=partition.freq, trade_date=partition.trade_date).exists()
        ]
        if existing_targets and not replace_existing:
            preview = ", ".join(
                f"freq={item.freq}/trade_date={item.trade_date.isoformat()}" for item in existing_targets[:10]
            )
            raise RuntimeError(
                "正式 clean candidate 目标分区已存在，拒绝覆盖。"
                f" existing={len(existing_targets)} preview={preview}；"
                "如确认要重建该 candidate，请显式传 --replace-existing。"
            )

        run_id = _run_id("rebuild-stk-mins-clean-next")
        started = time.monotonic()
        total_raw_rows = 0
        total_kept_rows = 0
        reason_totals: Counter[str] = Counter()
        duplicate_totals: Counter[str] = Counter()
        samples: list[dict[str, Any]] = []

        self.progress(
            f"[rebuild_stk_mins_by_date_clean_next] start run_id={run_id} "
            f"partitions={len(partitions)} mode=apply"
        )
        for index, partition in enumerate(partitions, start=1):
            build = self._build_formal_clean_next_partition(
                partition=partition,
                identity_by_source=identity_by_source,
                include_frame=True,
            )
            stats = build.stats
            conflict_count = int(stats["duplicate_reasons"].get("duplicate_conflict_payload", 0))
            if conflict_count:
                raise RuntimeError(
                    "正式 clean candidate 遇到同键不同内容冲突，已停止。"
                    f" freq={partition.freq} trade_date={partition.trade_date.isoformat()} conflicts={conflict_count}"
                )
            self._write_formal_clean_next_partition(
                run_id=run_id,
                partition=partition,
                frame=build.frame,
                expected_rows=int(stats["kept_rows"]),
            )

            total_raw_rows += int(stats["raw_rows"])
            total_kept_rows += int(stats["kept_rows"])
            reason_totals.update(stats["filter_reasons"])
            duplicate_totals.update(stats["duplicate_reasons"])
            if len(samples) < sample_limit:
                samples.append(stats)
            duplicate_rows = sum(int(value) for value in stats["duplicate_reasons"].values())
            if index == 1 or index == len(partitions) or index % 250 == 0 or stats["filtered_rows"] or duplicate_rows:
                self.progress(
                    f"[rebuild_stk_mins_by_date_clean_next] partition={index}/{len(partitions)} "
                    f"freq={partition.freq} trade_date={partition.trade_date.isoformat()} "
                    f"raw={stats['raw_rows']} written={stats['kept_rows']} filtered={stats['filtered_rows']}"
                )

        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        elapsed = time.monotonic() - started
        return {
            "operation": "rebuild_stk_mins_by_date_clean_next",
            "mode": "apply",
            "run_id": run_id,
            "lake_root": str(self.lake_root),
            "output_layer": str(FORMAL_CLEAN_RELATIVE_ROOT),
            "partitions": len(partitions),
            "raw_rows": total_raw_rows,
            "kept_rows": total_kept_rows,
            "filtered_rows": total_raw_rows - total_kept_rows,
            "filter_reasons": dict(sorted(reason_totals.items())),
            "duplicate_reasons": dict(sorted(duplicate_totals.items())),
            "identity_diagnostics": diagnostics,
            "status": "success",
            "schema": list(FORMAL_CLEAN_STK_MINS_FIELDS),
            "samples": samples,
            "write_intent": True,
            "elapsed_seconds": round(elapsed, 3),
        }

    def _summarize_formal_clean_next_rules(
        self,
        *,
        operation: str,
        partitions: list[StkMinsPartition],
        identity_by_source: dict[str, dict[str, Any]],
        diagnostics: dict[str, Any],
        sample_limit: int,
    ) -> dict[str, Any]:
        total_raw_rows = 0
        total_kept_rows = 0
        reason_totals: Counter[str] = Counter()
        duplicate_totals: Counter[str] = Counter()
        samples: list[dict[str, Any]] = []
        self.progress(f"[{operation}] start partitions={len(partitions)} output_layer={FORMAL_CLEAN_RELATIVE_ROOT}")
        for index, partition in enumerate(partitions, start=1):
            stats = self._build_formal_clean_next_partition(
                partition=partition,
                identity_by_source=identity_by_source,
                include_frame=False,
            ).stats
            total_raw_rows += int(stats["raw_rows"])
            total_kept_rows += int(stats["kept_rows"])
            reason_totals.update(stats["filter_reasons"])
            duplicate_totals.update(stats["duplicate_reasons"])
            if len(samples) < sample_limit:
                samples.append(stats)
            duplicate_rows = sum(int(value) for value in stats["duplicate_reasons"].values())
            if index == 1 or index == len(partitions) or index % 250 == 0 or stats["filtered_rows"] or duplicate_rows:
                self.progress(
                    f"[{operation}] partition={index}/{len(partitions)} freq={partition.freq} "
                    f"trade_date={partition.trade_date.isoformat()} raw={stats['raw_rows']} kept={stats['kept_rows']} "
                    f"filtered={stats['filtered_rows']}"
                )
        return {
            "operation": operation,
            "mode": "dry_run",
            "lake_root": str(self.lake_root),
            "output_layer": str(FORMAL_CLEAN_RELATIVE_ROOT),
            "partitions": len(partitions),
            "raw_rows": total_raw_rows,
            "kept_rows": total_kept_rows,
            "filtered_rows": total_raw_rows - total_kept_rows,
            "filter_reasons": dict(sorted(reason_totals.items())),
            "duplicate_reasons": dict(sorted(duplicate_totals.items())),
            "identity_diagnostics": diagnostics,
            "status": "planned",
            "schema": list(FORMAL_CLEAN_STK_MINS_FIELDS),
            "samples": samples,
            "write_intent": False,
        }

    def _build_formal_clean_next_partition(
        self,
        *,
        partition: StkMinsPartition,
        identity_by_source: dict[str, dict[str, Any]],
        include_frame: bool,
    ) -> StkMinsCleanBuildResult:
        pd = _require_pandas()
        frames = [pd.read_parquet(path, engine="pyarrow") for path in partition.files]
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(STK_MINS_FIELDS))
        if frame.empty:
            stats = {
                "freq": partition.freq,
                "trade_date": partition.trade_date.isoformat(),
                "raw_rows": 0,
                "kept_rows": 0,
                "filtered_rows": 0,
                "filter_reasons": {},
                "duplicate_reasons": {},
                "schema": list(FORMAL_CLEAN_STK_MINS_FIELDS),
            }
            return StkMinsCleanBuildResult(stats=stats, frame=_empty_formal_clean_frame(pd) if include_frame else None)

        source_ts_codes = frame["ts_code"].fillna("").astype(str).str.strip() if "ts_code" in frame.columns else pd.Series("", index=frame.index)
        latest_ts_codes = source_ts_codes.map({key: value.get("latest_ts_code") for key, value in identity_by_source.items()})
        list_dates = pd.to_datetime(
            source_ts_codes.map({key: value.get("effective_list_date") for key, value in identity_by_source.items()}),
            errors="coerce",
        )
        delist_dates = pd.to_datetime(
            source_ts_codes.map({key: value.get("effective_delist_date") for key, value in identity_by_source.items()}),
            errors="coerce",
        )

        reasons = pd.Series("", index=frame.index, dtype="object")
        reasons.loc[latest_ts_codes.isna()] = "identity_missing"

        if "trade_time" in frame.columns:
            trade_time_values = pd.to_datetime(frame["trade_time"], errors="coerce")
        else:
            trade_time_values = pd.Series(pd.NaT, index=frame.index)
        reasons.loc[reasons.eq("") & trade_time_values.isna()] = "invalid_trade_time"

        open_values = _numeric_series(frame, "open", pd)
        close_values = _numeric_series(frame, "close", pd)
        high_values = _numeric_series(frame, "high", pd)
        low_values = _numeric_series(frame, "low", pd)
        invalid_price_structure = (
            open_values.isna()
            | close_values.isna()
            | high_values.isna()
            | low_values.isna()
            | (high_values < low_values)
        )
        reasons.loc[reasons.eq("") & invalid_price_structure] = "invalid_price_structure"

        vol_values = _numeric_series(frame, "vol", pd).fillna(0)
        amount_values = _numeric_series(frame, "amount", pd).fillna(0)
        invalid_volume_amount = (vol_values < 0) | (amount_values < 0)
        reasons.loc[reasons.eq("") & invalid_volume_amount] = "invalid_volume_amount"

        trade_date_value = pd.Timestamp(partition.trade_date)
        reasons.loc[reasons.eq("") & delist_dates.notna()] = "delisted_security"
        reasons.loc[reasons.eq("") & list_dates.notna() & (trade_date_value < list_dates)] = "before_list_date"

        reason_counts = Counter({str(reason): int(count) for reason, count in reasons[reasons.ne("")].value_counts().items()})
        kept = frame.loc[reasons.eq("")].copy()
        if kept.empty:
            duplicate_counts = Counter()
            kept_rows = 0
            clean_frame = _empty_formal_clean_frame(pd) if include_frame else None
        else:
            kept["__latest_ts_code"] = latest_ts_codes.loc[kept.index].astype(str)
            key_cols = ["__latest_ts_code", "freq", "trade_time"]
            duplicated_key_mask = kept.duplicated(subset=key_cols, keep=False)
            if duplicated_key_mask.any():
                duplicated_rows = kept.loc[duplicated_key_mask].copy()
                payload_cols = [
                    field
                    for field in ("open", "close", "high", "low", "vol", "amount", "exchange", "vwap")
                    if field in duplicated_rows.columns
                ]
                key_counts = duplicated_rows.groupby(key_cols, dropna=False).size().rename("key_count")
                payload_distinct_counts = (
                    duplicated_rows.drop_duplicates(subset=key_cols + payload_cols)
                    .groupby(key_cols, dropna=False)
                    .size()
                    .rename("payload_distinct_count")
                )
                duplicate_frame = key_counts.to_frame().join(payload_distinct_counts, how="left").fillna({"payload_distinct_count": 0})
                same_payload = duplicate_frame[
                    (duplicate_frame["key_count"] > 1) & (duplicate_frame["payload_distinct_count"] == 1)
                ]["key_count"].sum() - len(
                    duplicate_frame[(duplicate_frame["key_count"] > 1) & (duplicate_frame["payload_distinct_count"] == 1)]
                )
                conflict_payload = duplicate_frame[duplicate_frame["payload_distinct_count"] > 1]["payload_distinct_count"].sum() - len(
                    duplicate_frame[duplicate_frame["payload_distinct_count"] > 1]
                )
                duplicate_counts = Counter(
                    {
                        key: value
                        for key, value in {
                            "duplicate_same_payload": int(same_payload),
                            "duplicate_conflict_payload": int(conflict_payload),
                        }.items()
                        if value
                    }
                )
            else:
                duplicate_counts = Counter()
            if duplicate_counts["duplicate_conflict_payload"]:
                clean_frame = None
                kept_rows = len(kept) - duplicate_counts["duplicate_same_payload"] - duplicate_counts["duplicate_conflict_payload"]
            else:
                clean_source = kept.drop_duplicates(subset=key_cols, keep="first") if duplicate_counts["duplicate_same_payload"] else kept
                kept_rows = len(clean_source)
                clean_frame = self._to_formal_clean_next_frame(
                    frame=clean_source,
                    pd=pd,
                    partition=partition,
                    open_values=open_values,
                    close_values=close_values,
                    high_values=high_values,
                    low_values=low_values,
                    vol_values=vol_values,
                    amount_values=amount_values,
                ) if include_frame else None
        stats = {
            "freq": partition.freq,
            "trade_date": partition.trade_date.isoformat(),
            "raw_rows": int(len(frame)),
            "kept_rows": max(kept_rows, 0),
            "filtered_rows": int(len(frame)) - max(kept_rows, 0),
            "filter_reasons": dict(sorted(reason_counts.items())),
            "duplicate_reasons": dict(sorted(duplicate_counts.items())),
            "schema": list(FORMAL_CLEAN_STK_MINS_FIELDS),
        }
        return StkMinsCleanBuildResult(stats=stats, frame=clean_frame)

    def _audit_formal_clean_next_partition_basic(
        self,
        *,
        partition: StkMinsPartition,
        identity_by_latest: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        pd = _require_pandas()
        frames = [pd.read_parquet(path, engine="pyarrow") for path in partition.files]
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(FORMAL_CLEAN_STK_MINS_FIELDS))
        records: list[dict[str, Any]] = []
        evidence_ref = str(partition.path.relative_to(self.lake_root)) if partition.path.is_relative_to(self.lake_root) else str(partition.path)

        if list(frame.columns) != list(FORMAL_CLEAN_STK_MINS_FIELDS):
            records.append(
                _issue_record(
                    gate="M4",
                    issue_type="schema_violation",
                    status="failed",
                    latest_ts_code="__partition__",
                    freq=partition.freq,
                    trade_date=partition.trade_date,
                    expected_value=",".join(FORMAL_CLEAN_STK_MINS_FIELDS),
                    actual_value=",".join(str(column) for column in frame.columns),
                    evidence_dataset="research.stk_mins_by_date_clean_next",
                    evidence_ref=evidence_ref,
                    action="block",
                    reason="clean_next 分区物理字段不等于正式 11 列 schema。",
                )
            )

        if frame.empty:
            return records

        ts_codes = frame["ts_code"].fillna("").astype(str).str.strip() if "ts_code" in frame.columns else pd.Series("", index=frame.index)
        trade_time_values = (
            pd.to_datetime(frame["trade_time"], errors="coerce") if "trade_time" in frame.columns else pd.Series(pd.NaT, index=frame.index)
        )
        open_values = _numeric_series(frame, "open", pd)
        close_values = _numeric_series(frame, "close", pd)
        high_values = _numeric_series(frame, "high", pd)
        low_values = _numeric_series(frame, "low", pd)
        vol_values = _numeric_series(frame, "vol", pd).fillna(0)
        amount_values = _numeric_series(frame, "amount", pd).fillna(0)

        invalid_trade_time_count = int(trade_time_values.isna().sum())
        if invalid_trade_time_count:
            records.append(
                _issue_record(
                    gate="M4",
                    issue_type="invalid_trade_time",
                    status="failed",
                    latest_ts_code="__partition__",
                    freq=partition.freq,
                    trade_date=partition.trade_date,
                    expected_value="trade_time parseable",
                    actual_value=f"invalid_rows={invalid_trade_time_count}",
                    evidence_dataset="research.stk_mins_by_date_clean_next",
                    evidence_ref=evidence_ref,
                    action="block",
                    reason="clean_next 分区存在无法解析的 trade_time。",
                )
            )

        invalid_price_structure = (
            open_values.isna()
            | close_values.isna()
            | high_values.isna()
            | low_values.isna()
            | (high_values < low_values)
        )
        invalid_price_count = int(invalid_price_structure.sum())
        if invalid_price_count:
            records.append(
                _issue_record(
                    gate="M4",
                    issue_type="invalid_price_structure",
                    status="failed",
                    latest_ts_code="__partition__",
                    freq=partition.freq,
                    trade_date=partition.trade_date,
                    expected_value="open/close/high/low parseable and high >= low",
                    actual_value=f"invalid_rows={invalid_price_count}",
                    evidence_dataset="research.stk_mins_by_date_clean_next",
                    evidence_ref=evidence_ref,
                    action="block",
                    reason="clean_next 分区存在结构性非法价格；OHLC 等于 0 不在本规则中判错。",
                )
            )

        invalid_volume_amount_count = int(((vol_values < 0) | (amount_values < 0)).sum())
        if invalid_volume_amount_count:
            records.append(
                _issue_record(
                    gate="M4",
                    issue_type="invalid_volume_amount",
                    status="failed",
                    latest_ts_code="__partition__",
                    freq=partition.freq,
                    trade_date=partition.trade_date,
                    expected_value="vol >= 0 and amount >= 0",
                    actual_value=f"invalid_rows={invalid_volume_amount_count}",
                    evidence_dataset="research.stk_mins_by_date_clean_next",
                    evidence_ref=evidence_ref,
                    action="block",
                    reason="clean_next 分区存在负数成交量或成交额。",
                )
            )

        known_latest_codes = set(identity_by_latest)
        identity_missing_count = int((ts_codes.ne("") & ~ts_codes.isin(known_latest_codes)).sum())
        if identity_missing_count:
            records.append(
                _issue_record(
                    gate="M4",
                    issue_type="identity_missing",
                    status="failed",
                    latest_ts_code="__partition__",
                    freq=partition.freq,
                    trade_date=partition.trade_date,
                    expected_value="ts_code in security_identity_map.latest_ts_code",
                    actual_value=f"missing_rows={identity_missing_count}",
                    evidence_dataset="manifest.security_identity.security_identity_map",
                    evidence_ref=evidence_ref,
                    action="block",
                    reason="clean_next 中存在身份账本无法解释的 ts_code。",
                )
            )

        identity_list_dates = pd.to_datetime(
            ts_codes.map({key: value.get("effective_list_date") for key, value in identity_by_latest.items()}),
            errors="coerce",
        )
        identity_delist_dates = pd.to_datetime(
            ts_codes.map({key: value.get("effective_delist_date") for key, value in identity_by_latest.items()}),
            errors="coerce",
        )
        delisted_mask = identity_delist_dates.notna()
        delisted_codes = sorted(set(ts_codes.loc[delisted_mask].tolist()))
        for ts_code in delisted_codes:
            row_count = int((delisted_mask & (ts_codes == ts_code)).sum())
            records.append(
                _issue_record(
                    gate="M4",
                    issue_type="delisted_security",
                    status="failed",
                    latest_ts_code=ts_code,
                    freq=partition.freq,
                    trade_date=partition.trade_date,
                    expected_value="delisted security excluded from clean_next",
                    actual_value=f"rows={row_count}",
                    evidence_dataset="manifest.security_identity.security_identity_map",
                    evidence_ref=evidence_ref,
                    action="block",
                    reason="已退市股票不允许进入正式 clean candidate。",
                )
            )

        trade_date_value = pd.Timestamp(partition.trade_date)
        before_list_mask = identity_list_dates.notna() & (trade_date_value < identity_list_dates)
        before_list_codes = sorted(set(ts_codes.loc[before_list_mask].tolist()))
        for ts_code in before_list_codes:
            row_count = int((before_list_mask & (ts_codes == ts_code)).sum())
            records.append(
                _issue_record(
                    gate="M4",
                    issue_type="before_list_date",
                    status="failed",
                    latest_ts_code=ts_code,
                    freq=partition.freq,
                    trade_date=partition.trade_date,
                    expected_value="trade_date >= effective_list_date",
                    actual_value=f"rows={row_count}",
                    evidence_dataset="manifest.security_identity.security_identity_map",
                    evidence_ref=evidence_ref,
                    action="block",
                    reason="上市日前数据不允许进入正式 clean candidate。",
                )
            )

        if {"ts_code", "freq", "trade_time"}.issubset(frame.columns):
            duplicate_rows = frame.loc[frame.duplicated(subset=["ts_code", "freq", "trade_time"], keep=False)].copy()
            if not duplicate_rows.empty:
                payload_cols = [
                    field
                    for field in ("open", "close", "high", "low", "vol", "amount", "exchange", "vwap")
                    if field in duplicate_rows.columns
                ]
                grouped = duplicate_rows.groupby(["ts_code", "freq", "trade_time"], dropna=False)
                for (ts_code, _freq, trade_time), group in grouped:
                    payload_distinct_count = int(group.drop_duplicates(subset=payload_cols).shape[0]) if payload_cols else int(len(group))
                    issue_type = "duplicate_conflict_payload" if payload_distinct_count > 1 else "duplicate_same_payload"
                    records.append(
                        _issue_record(
                            gate="M4",
                            issue_type=issue_type,
                            status="failed",
                            latest_ts_code=str(ts_code),
                            freq=partition.freq,
                            trade_date=partition.trade_date,
                            trade_time=trade_time,
                            expected_value="unique ts_code+freq+trade_time",
                            actual_value=f"rows={len(group)} payload_distinct={payload_distinct_count}",
                            evidence_dataset="research.stk_mins_by_date_clean_next",
                            evidence_ref=evidence_ref,
                            action="block",
                            reason="clean_next 分区存在重复 key。",
                        )
                    )
        return records

    def _audit_formal_clean_next_partition_completeness(
        self,
        *,
        partition: StkMinsPartition,
        identity_by_latest: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        pd = _require_pandas()
        frames = [pd.read_parquet(path, engine="pyarrow") for path in partition.files]
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(FORMAL_CLEAN_STK_MINS_FIELDS))
        records: list[dict[str, Any]] = []
        evidence_ref = str(partition.path.relative_to(self.lake_root)) if partition.path.is_relative_to(self.lake_root) else str(partition.path)
        if list(frame.columns) != list(FORMAL_CLEAN_STK_MINS_FIELDS) or frame.empty:
            return records
        if not {"ts_code", "trade_time"}.issubset(frame.columns):
            return records

        ts_codes = frame["ts_code"].fillna("").astype(str).str.strip()
        trade_time_values = pd.to_datetime(frame["trade_time"], errors="coerce")
        open_values = _numeric_series(frame, "open", pd)
        close_values = _numeric_series(frame, "close", pd)
        high_values = _numeric_series(frame, "high", pd)
        low_values = _numeric_series(frame, "low", pd)
        vol_values = _numeric_series(frame, "vol", pd).fillna(0)
        amount_values = _numeric_series(frame, "amount", pd).fillna(0)
        known_latest_codes = set(identity_by_latest)
        identity_list_dates = pd.to_datetime(
            ts_codes.map({key: value.get("effective_list_date") for key, value in identity_by_latest.items()}),
            errors="coerce",
        )
        identity_delist_dates = pd.to_datetime(
            ts_codes.map({key: value.get("effective_delist_date") for key, value in identity_by_latest.items()}),
            errors="coerce",
        )
        trade_date_value = pd.Timestamp(partition.trade_date)
        before_list_mask = identity_list_dates.notna() & (trade_date_value < identity_list_dates)
        invalid_price_structure = (
            open_values.isna()
            | close_values.isna()
            | high_values.isna()
            | low_values.isna()
            | (high_values < low_values)
        )
        invalid_volume_amount = (vol_values < 0) | (amount_values < 0)
        valid_time_mask = (
            trade_time_values.notna()
            & ~invalid_price_structure
            & ~invalid_volume_amount
            & ts_codes.isin(known_latest_codes)
            & identity_delist_dates.isna()
            & ~before_list_mask
        )
        valid_time_frame = frame.loc[valid_time_mask].copy()
        if valid_time_frame.empty:
            return records

        expected_bar_count = INTRADAY_EXPECTED_BAR_COUNT.get(partition.freq)
        if not expected_bar_count:
            return records
        after_hours_count = INTRADAY_AFTER_HOURS_BAR_COUNT.get(partition.freq, 0)
        max_explainable_count = expected_bar_count + after_hours_count
        bar_counts = valid_time_frame.groupby("ts_code", dropna=False).size()
        for ts_code, bar_count_value in bar_counts.items():
            bar_count = int(bar_count_value)
            if expected_bar_count <= bar_count <= max_explainable_count:
                continue
            if bar_count < expected_bar_count:
                issue_type = "missing_intraday_bar"
                status = "needs_review"
                expected_value = f"bar_count>={expected_bar_count}"
                action = "review_or_repair_required"
                reason = "clean_next 分区日内 bar 数不足，需要结合停牌、源站缺失或专项修复判断。"
            else:
                issue_type = "extra_intraday_bar"
                status = "failed"
                expected_value = f"bar_count<={max_explainable_count}"
                action = "block"
                reason = "clean_next 分区日内 bar 数超过常规日盘加盘后可解释范围。"
            records.append(
                _issue_record(
                    gate="M5",
                    issue_type=issue_type,
                    status=status,
                    latest_ts_code=str(ts_code),
                    freq=partition.freq,
                    trade_date=partition.trade_date,
                    expected_value=expected_value,
                    actual_value=f"bar_count={bar_count}",
                    evidence_dataset="research.stk_mins_by_date_clean_next",
                    evidence_ref=evidence_ref,
                    action=action,
                    reason=reason,
                )
            )
        return records

    def _to_formal_clean_next_frame(
        self,
        *,
        frame: Any,
        pd: Any,
        partition: StkMinsPartition,
        open_values: Any,
        close_values: Any,
        high_values: Any,
        low_values: Any,
        vol_values: Any,
        amount_values: Any,
    ) -> Any:
        clean = pd.DataFrame(index=frame.index)
        clean["ts_code"] = frame["__latest_ts_code"].astype(str)
        clean["freq"] = partition.freq
        clean["trade_time"] = pd.to_datetime(frame["trade_time"], errors="coerce")
        clean["open"] = open_values.loc[frame.index].astype("float64")
        clean["close"] = close_values.loc[frame.index].astype("float64")
        clean["high"] = high_values.loc[frame.index].astype("float64")
        clean["low"] = low_values.loc[frame.index].astype("float64")
        clean["vol"] = vol_values.loc[frame.index].astype("int64")
        clean["amount"] = amount_values.loc[frame.index].astype("float64")
        clean["exchange"] = frame["exchange"].where(frame["exchange"].notna(), None) if "exchange" in frame.columns else None
        clean["vwap"] = _numeric_series(frame, "vwap", pd).loc[frame.index] if "vwap" in frame.columns else None
        return clean.loc[:, list(FORMAL_CLEAN_STK_MINS_FIELDS)].sort_values(["ts_code", "trade_time"]).reset_index(drop=True)

    def _write_formal_clean_next_partition(self, *, run_id: str, partition: StkMinsPartition, frame: Any, expected_rows: int) -> None:
        if frame is None:
            raise RuntimeError(
                f"正式 clean candidate 分区没有可写入 DataFrame："
                f"freq={partition.freq} trade_date={partition.trade_date.isoformat()}"
            )
        tmp_partition = (
            self.lake_root
            / "_tmp"
            / run_id
            / FORMAL_CLEAN_RELATIVE_ROOT
            / f"freq={partition.freq}"
            / f"trade_date={partition.trade_date.isoformat()}"
        )
        final_partition = self._formal_clean_next_partition(freq=partition.freq, trade_date=partition.trade_date)
        backup_root = (
            self.lake_root
            / "_tmp"
            / run_id
            / "_backup"
            / FORMAL_CLEAN_RELATIVE_ROOT
            / f"freq={partition.freq}"
        )
        if tmp_partition.exists():
            shutil.rmtree(tmp_partition)
        tmp_partition.mkdir(parents=True, exist_ok=True)
        tmp_file = tmp_partition / "part-000.parquet"
        frame.to_parquet(tmp_file, index=False, engine="pyarrow", compression="zstd")
        validated = _row_count([tmp_file])
        if validated != expected_rows:
            raise RuntimeError(
                f"正式 clean candidate 写入校验失败：freq={partition.freq} trade_date={partition.trade_date.isoformat()} "
                f"expected={expected_rows} validated={validated}"
            )
        replace_directory_atomically(tmp_dir=tmp_partition, final_dir=final_partition, backup_root=backup_root)

    def _write_clean_issue_ledger_to_path(
        self,
        *,
        issue_records: list[dict[str, Any]],
        ledger_relative_path: Path,
        run_label: str,
        audited_partition_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        if ledger_relative_path == FORMAL_CLEAN_ISSUE_LEDGER_RELATIVE_PATH:
            return self._write_formal_clean_next_issue_ledger(
                issue_records=issue_records,
                ledger_relative_path=ledger_relative_path,
                run_label=run_label,
                audited_partition_keys=set(audited_partition_keys or []),
            )

        ledger_file = self.lake_root / ledger_relative_path
        existing_rows = self._read_optional_parquet_rows(ledger_file)
        ledger_rows = sorted(issue_records, key=lambda row: str(row.get("issue_id") or ""))

        LakeRootService(self.lake_root).require_ready_for_write()
        run_id = _run_id(run_label)
        tmp_file = self.lake_root / "_tmp" / run_id / ledger_relative_path
        backup_root = self.lake_root / "_tmp" / run_id / "_backup" / ledger_relative_path.parent
        if ledger_rows:
            written = write_rows_to_parquet(ledger_rows, tmp_file)
        else:
            written = _write_empty_issue_ledger(tmp_file)
        validated = read_parquet_row_count(tmp_file)
        if written != validated:
            raise RuntimeError(f"clean 完备性问题账本校验失败：written={written} validated={validated}")
        replace_file_atomically(tmp_file=tmp_file, final_file=ledger_file, backup_root=backup_root)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        return {
            "run_id": run_id,
            "path": str(ledger_file),
            "existing_rows": len(existing_rows),
            "new_records": len(issue_records),
            "written_rows": written,
            "write_skipped": False,
        }

    def _write_formal_clean_next_issue_ledger(
        self,
        *,
        issue_records: list[dict[str, Any]],
        ledger_relative_path: Path,
        run_label: str,
        audited_partition_keys: set[str],
    ) -> dict[str, Any]:
        ledger_file = self.lake_root / ledger_relative_path
        existing_rows = self._read_optional_parquet_rows(ledger_file)

        LakeRootService(self.lake_root).require_ready_for_write()
        run_id = _run_id(run_label)
        observed_at = datetime.now(timezone.utc)

        existing_by_key: dict[str, dict[str, Any]] = {}
        for row in existing_rows:
            normalized = _normalize_formal_ledger_existing_row(row)
            if normalized:
                existing_by_key[str(normalized["issue_key"])] = normalized

        current_by_key: dict[str, dict[str, Any]] = {}
        for record in issue_records:
            current = _formal_ledger_row_from_issue_record(record=record, run_id=run_id, observed_at=observed_at)
            current_by_key[str(current["issue_key"])] = current

        merged_by_key: dict[str, dict[str, Any]] = {}
        for issue_key, current in current_by_key.items():
            existing = existing_by_key.get(issue_key)
            if existing:
                merged = dict(current)
                merged["first_seen_run_id"] = existing.get("first_seen_run_id") or current["first_seen_run_id"]
                merged["first_seen_at"] = existing.get("first_seen_at") or current["first_seen_at"]
                merged["seen_count"] = int(existing.get("seen_count") or 0) + 1
                merged["issue_state"] = "open"
                merged["resolved_run_id"] = None
                merged["resolved_at"] = None
                merged["superseded_by_issue_key"] = None
                merged_by_key[issue_key] = merged
            else:
                merged_by_key[issue_key] = current

        for issue_key, existing in existing_by_key.items():
            if issue_key in merged_by_key:
                continue
            if existing.get("issue_state") == "open" and str(existing.get("partition_key") or "") in audited_partition_keys:
                resolved = dict(existing)
                resolved["issue_state"] = "resolved"
                resolved["resolved_run_id"] = run_id
                resolved["resolved_at"] = observed_at
                merged_by_key[issue_key] = resolved
            else:
                merged_by_key[issue_key] = existing

        ledger_rows = sorted((_formal_ledger_project(row) for row in merged_by_key.values()), key=lambda row: str(row["issue_key"]))
        tmp_file = self.lake_root / "_tmp" / run_id / ledger_relative_path
        backup_root = self.lake_root / "_tmp" / run_id / "_backup" / ledger_relative_path.parent
        if ledger_rows:
            written = write_rows_to_parquet(ledger_rows, tmp_file)
        else:
            written = _write_empty_issue_ledger(tmp_file, fields=FORMAL_ISSUE_LEDGER_FIELDS)
        validated = read_parquet_row_count(tmp_file)
        if written != validated:
            raise RuntimeError(f"clean_next 完备性问题账本校验失败：written={written} validated={validated}")
        replace_file_atomically(tmp_file=tmp_file, final_file=ledger_file, backup_root=backup_root)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)

        issue_states = Counter(str(row.get("issue_state") or "") for row in ledger_rows)
        return {
            "run_id": run_id,
            "path": str(ledger_file),
            "existing_rows": len(existing_rows),
            "new_records": len(issue_records),
            "written_rows": written,
            "open_records": int(issue_states.get("open", 0)),
            "resolved_records": int(issue_states.get("resolved", 0)),
            "write_skipped": False,
        }

    def _build_identity_rows(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        stock_rows = self._read_optional_parquet_rows(self.lake_root / "manifest" / "security_universe" / "tushare_stock_basic.parquet")
        if not stock_rows:
            raise RuntimeError("缺少 stock_basic manifest，无法建立 security_identity_map。")
        stock_by_code = {str(row.get("ts_code") or "").strip(): row for row in stock_rows if str(row.get("ts_code") or "").strip()}
        identity_rows: dict[str, dict[str, Any]] = {}
        diagnostics: dict[str, Any] = {
            "stock_basic_rows": len(stock_rows),
            "bse_mapping_rows": 0,
            "namechange_rows": 0,
            "namechange_alias_rows": 0,
            "conflicts": [],
        }

        for ts_code, row in sorted(stock_by_code.items()):
            list_date = _parse_date(row.get("list_date"))
            delist_date = _parse_date(row.get("delist_date"))
            identity_rows[ts_code] = _identity_row(
                latest_ts_code=ts_code,
                source_ts_code=ts_code,
                valid_from=list_date,
                valid_to=delist_date,
                effective_list_date=list_date,
                effective_delist_date=delist_date,
                identity_source="stock_basic",
                confidence="confirmed",
                reason="stock_basic current/listed security",
            )

        bse_rows = self._read_optional_parquet_rows(self._security_reference_file("tushare_bse_mapping.parquet"))
        diagnostics["bse_mapping_rows"] = len(bse_rows)
        for row in bse_rows:
            old_code = str(row.get("o_code") or "").strip()
            new_code = str(row.get("n_code") or "").strip()
            if not old_code or not new_code or new_code not in stock_by_code:
                continue
            stock = stock_by_code[new_code]
            identity_rows.setdefault(
                old_code,
                _identity_row(
                    latest_ts_code=new_code,
                    source_ts_code=old_code,
                    valid_from=_parse_date(stock.get("list_date")),
                    valid_to=_parse_date(stock.get("delist_date")),
                    effective_list_date=_parse_date(stock.get("list_date")),
                    effective_delist_date=_parse_date(stock.get("delist_date")),
                    identity_source="bse_mapping",
                    confidence="confirmed",
                    reason=f"bse_mapping o_code={old_code} -> n_code={new_code}",
                ),
            )

        namechange_rows = self._read_optional_parquet_rows(self._security_reference_file("tushare_namechange.parquet"))
        diagnostics["namechange_rows"] = len(namechange_rows)
        alias_rows = self._infer_namechange_alias_rows(namechange_rows=namechange_rows, stock_by_code=stock_by_code)
        diagnostics["namechange_alias_rows"] = len(alias_rows)
        for row in alias_rows:
            existing = identity_rows.get(str(row["source_ts_code"]))
            if existing and existing["latest_ts_code"] != row["latest_ts_code"]:
                diagnostics["conflicts"].append({"source_ts_code": row["source_ts_code"], "existing": existing, "candidate": row})
                continue
            identity_rows[str(row["source_ts_code"])] = row

        rows = sorted(identity_rows.values(), key=lambda item: (str(item["latest_ts_code"]), str(item["source_ts_code"])))
        return rows, diagnostics

    def _infer_namechange_alias_rows(
        self,
        *,
        namechange_rows: list[dict[str, Any]],
        stock_by_code: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in namechange_rows:
            ts_code = str(row.get("ts_code") or "").strip()
            if ts_code:
                rows_by_code[ts_code].append(row)
        signatures_by_stock: dict[tuple[str, date | None, date | None], set[str]] = defaultdict(set)
        for ts_code in stock_by_code:
            for row in rows_by_code.get(ts_code, []):
                signatures_by_stock[_namechange_signature(row)].add(ts_code)

        alias_rows: list[dict[str, Any]] = []
        for source_code, rows in rows_by_code.items():
            if source_code in stock_by_code:
                continue
            candidate_counts: Counter[str] = Counter()
            for row in rows:
                for candidate in signatures_by_stock.get(_namechange_signature(row), set()):
                    candidate_counts[candidate] += 1
            if not candidate_counts:
                continue
            top_count = max(candidate_counts.values())
            candidates = sorted(code for code, count in candidate_counts.items() if count == top_count)
            if len(candidates) != 1 or top_count < 2:
                continue
            latest_code = candidates[0]
            stock = stock_by_code[latest_code]
            list_date = _parse_date(stock.get("list_date"))
            delist_date = _parse_date(stock.get("delist_date"))
            alias_rows.append(
                _identity_row(
                    latest_ts_code=latest_code,
                    source_ts_code=source_code,
                    valid_from=list_date,
                    valid_to=delist_date,
                    effective_list_date=list_date,
                    effective_delist_date=delist_date,
                    identity_source="namechange",
                    confidence="inferred",
                    reason=f"namechange exact-overlap source_ts_code={source_code} -> latest_ts_code={latest_code}",
                )
            )
        return alias_rows

    def _load_or_build_identity_map(self) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        identity_file = self.lake_root / "manifest" / "security_identity" / "security_identity_map.parquet"
        if identity_file.exists():
            rows = self._read_optional_parquet_rows(identity_file)
            return _identity_by_source(rows), {"identity_source": "manifest/security_identity/security_identity_map.parquet"}
        rows, diagnostics = self._build_identity_rows()
        diagnostics = dict(diagnostics)
        diagnostics["identity_source"] = "in_memory_build"
        return _identity_by_source(rows), diagnostics

    def _read_optional_parquet_rows(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        pd = _require_pandas()
        return [dict(row) for row in pd.read_parquet(path, engine="pyarrow").to_dict(orient="records")]

    def _security_reference_file(self, name: str) -> Path:
        manifest_file = self.lake_root / "manifest" / "security_reference" / name
        if manifest_file.exists():
            return manifest_file
        raw_name = name.removeprefix("tushare_")
        return self.lake_root / "raw_tushare" / raw_name.removesuffix(".parquet") / "current" / "part-000.parquet"

    def _discover_partitions(
        self,
        *,
        layer: str,
        freqs: list[int],
        start_date: date | None,
        end_date: date | None,
        include_metadata: bool = True,
    ) -> list[StkMinsPartition]:
        if start_date and end_date and end_date < start_date:
            raise ValueError("end-date 不能早于 start-date。")
        if layer == "raw_tushare":
            root = self.lake_root / "raw_tushare" / "stk_mins_by_date"
        elif layer == "formal_clean_next":
            root = self.lake_root / FORMAL_CLEAN_RELATIVE_ROOT
        else:
            raise ValueError(f"不支持的 layer={layer}")
        partitions: list[StkMinsPartition] = []
        for freq in freqs:
            freq_root = root / f"freq={freq}"
            for partition in sorted(freq_root.glob("trade_date=*")):
                trade_date = _parse_trade_date_partition(partition)
                if trade_date is None:
                    continue
                if start_date and trade_date < start_date:
                    continue
                if end_date and trade_date > end_date:
                    continue
                files = tuple(_partition_files(partition))
                if not files:
                    continue
                partitions.append(
                    StkMinsPartition(
                        freq=freq,
                        trade_date=trade_date,
                        path=partition,
                        files=files,
                        row_count=_row_count(files) if include_metadata else 0,
                        byte_count=sum(path.stat().st_size for path in files) if include_metadata else 0,
                    )
                )
        return partitions

    def _formal_clean_next_partition(self, *, freq: int, trade_date: date) -> Path:
        return self.lake_root / FORMAL_CLEAN_RELATIVE_ROOT / f"freq={freq}" / f"trade_date={trade_date.isoformat()}"


def _identity_row(
    *,
    latest_ts_code: str,
    source_ts_code: str,
    valid_from: date | None,
    valid_to: date | None,
    effective_list_date: date | None,
    effective_delist_date: date | None,
    identity_source: str,
    confidence: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "latest_ts_code": latest_ts_code,
        "source_ts_code": source_ts_code,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "effective_list_date": effective_list_date,
        "effective_delist_date": effective_delist_date,
        "identity_source": identity_source,
        "confidence": confidence,
        "reason": reason,
        "created_at": datetime.now(timezone.utc),
    }


def _identity_by_source(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["source_ts_code"]): row for row in rows if str(row.get("source_ts_code") or "").strip()}


def _identity_by_latest(rows: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest_ts_code = str(row.get("latest_ts_code") or "").strip()
        if not latest_ts_code:
            continue
        existing = result.get(latest_ts_code)
        list_date = _parse_date(row.get("effective_list_date"))
        delist_date = _parse_date(row.get("effective_delist_date"))
        if existing is None:
            result[latest_ts_code] = dict(row)
            result[latest_ts_code]["effective_list_date"] = list_date
            result[latest_ts_code]["effective_delist_date"] = delist_date
            continue
        existing_list_date = _parse_date(existing.get("effective_list_date"))
        existing_delist_date = _parse_date(existing.get("effective_delist_date"))
        if list_date and (existing_list_date is None or list_date < existing_list_date):
            existing["effective_list_date"] = list_date
        if delist_date and (existing_delist_date is None or delist_date > existing_delist_date):
            existing["effective_delist_date"] = delist_date
    return result


def _namechange_signature(row: dict[str, Any]) -> tuple[str, date | None, date | None]:
    return (str(row.get("name") or "").strip(), _parse_date(row.get("start_date")), _parse_date(row.get("end_date")))


def _validate_freqs(freqs: list[int]) -> None:
    if not freqs:
        raise ValueError("必须至少指定一个 freq。")
    invalid = sorted(set(freqs) - RAW_FREQS)
    if invalid:
        raise ValueError(f"clean by_date 仅支持 raw freq=1/5/15/30/60，不支持 {invalid}。")


def _partition_summary(partition: StkMinsPartition) -> dict[str, Any]:
    return {
        "freq": partition.freq,
        "trade_date": partition.trade_date.isoformat(),
        "files": len(partition.files),
        "rows": partition.row_count,
        "bytes": partition.byte_count,
        "path": str(partition.path),
    }


def _issue_record(
    *,
    gate: str,
    issue_type: str,
    status: str,
    latest_ts_code: str,
    freq: int,
    trade_date: date,
    trade_time: Any | None = None,
    expected_value: str | None,
    actual_value: str | None,
    evidence_dataset: str | None,
    evidence_ref: str | None,
    action: str,
    reason: str,
) -> dict[str, Any]:
    trade_time_text = _normalize_issue_time(trade_time)
    identity = "|".join(
        [
            gate,
            issue_type,
            latest_ts_code,
            str(freq),
            trade_date.isoformat(),
            trade_time_text or "",
            expected_value or "",
            actual_value or "",
            evidence_ref or "",
        ]
    )
    return {
        "issue_id": sha1(identity.encode("utf-8")).hexdigest(),
        "gate": gate,
        "issue_type": issue_type,
        "status": status,
        "latest_ts_code": latest_ts_code,
        "freq": freq,
        "trade_date": trade_date,
        "trade_time": trade_time_text,
        "expected_value": expected_value,
        "actual_value": actual_value,
        "evidence_dataset": evidence_dataset,
        "evidence_ref": evidence_ref,
        "action": action,
        "reason": reason,
        "created_at": datetime.now(timezone.utc),
        "resolved_at": None,
    }


def _formal_ledger_row_from_issue_record(*, record: dict[str, Any], run_id: str, observed_at: datetime) -> dict[str, Any]:
    freq = int(record.get("freq") or 0)
    trade_date = _parse_date(record.get("trade_date"))
    partition_key = _partition_key(freq, trade_date)
    trade_time = _normalize_issue_time(record.get("trade_time"))
    issue_key = _formal_issue_key(
        dataset_key="stk_mins",
        layer=str(FORMAL_CLEAN_RELATIVE_ROOT),
        partition_key=partition_key,
        gate=str(record.get("gate") or ""),
        issue_type=str(record.get("issue_type") or ""),
        latest_ts_code=str(record.get("latest_ts_code") or ""),
        trade_time=trade_time,
        expected_value=_optional_text(record.get("expected_value")),
        evidence_ref=_optional_text(record.get("evidence_ref")),
    )
    return _formal_ledger_project(
        {
            "ledger_schema_version": FORMAL_ISSUE_LEDGER_SCHEMA_VERSION,
            "issue_key": issue_key,
            "issue_state": "open",
            "severity": "block",
            "dataset_key": "stk_mins",
            "source_key": "tushare",
            "layer": str(FORMAL_CLEAN_RELATIVE_ROOT),
            "partition_key": partition_key,
            "freq": freq,
            "trade_date": trade_date,
            "trade_time": trade_time,
            "latest_ts_code": str(record.get("latest_ts_code") or ""),
            "issue_type": str(record.get("issue_type") or ""),
            "expected_value": _optional_text(record.get("expected_value")),
            "actual_value": _optional_text(record.get("actual_value")),
            "evidence_dataset": _optional_text(record.get("evidence_dataset")),
            "evidence_ref": _optional_text(record.get("evidence_ref")),
            "action": "block",
            "reason": _optional_text(record.get("reason")),
            "first_seen_run_id": run_id,
            "last_seen_run_id": run_id,
            "resolved_run_id": None,
            "first_seen_at": observed_at,
            "last_seen_at": observed_at,
            "resolved_at": None,
            "seen_count": 1,
            "superseded_by_issue_key": None,
        }
    )


def _normalize_formal_ledger_existing_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("issue_key"):
        return _formal_ledger_project(row)
    if not row.get("issue_id"):
        return None
    created_at = row.get("created_at") or datetime.now(timezone.utc)
    return _formal_ledger_project(
        {
            **_formal_ledger_row_from_issue_record(record=row, run_id="legacy", observed_at=created_at),
            "first_seen_run_id": "legacy",
            "last_seen_run_id": "legacy",
            "first_seen_at": created_at,
            "last_seen_at": created_at,
            "resolved_at": row.get("resolved_at"),
            "issue_state": "resolved" if row.get("resolved_at") else "open",
        }
    )


def _formal_ledger_project(row: dict[str, Any]) -> dict[str, Any]:
    projected = {field: row.get(field) for field in FORMAL_ISSUE_LEDGER_FIELDS}
    projected["ledger_schema_version"] = FORMAL_ISSUE_LEDGER_SCHEMA_VERSION
    projected["severity"] = projected.get("severity") or "block"
    projected["issue_state"] = projected.get("issue_state") or "open"
    projected["dataset_key"] = projected.get("dataset_key") or "stk_mins"
    projected["source_key"] = projected.get("source_key") or "tushare"
    projected["layer"] = projected.get("layer") or str(FORMAL_CLEAN_RELATIVE_ROOT)
    projected["seen_count"] = int(projected.get("seen_count") or 0)
    return projected


def _formal_issue_key(
    *,
    dataset_key: str,
    layer: str,
    partition_key: str,
    gate: str,
    issue_type: str,
    latest_ts_code: str,
    trade_time: str | None,
    expected_value: str | None,
    evidence_ref: str | None,
) -> str:
    identity = "|".join(
        [
            dataset_key,
            layer,
            partition_key,
            gate,
            issue_type,
            latest_ts_code,
            trade_time or "",
            expected_value or "",
            evidence_ref or "",
        ]
    )
    return sha1(identity.encode("utf-8")).hexdigest()


def _partition_key(freq: int, trade_date: date) -> str:
    return f"freq={freq}/trade_date={trade_date.isoformat()}"


def _optional_text(value: Any | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    return text


def _write_empty_issue_ledger(output_path: Path, *, fields: tuple[str, ...] = ISSUE_LEDGER_FIELDS) -> int:
    try:
        import pandas as pd
        import pyarrow  # noqa: F401
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 Parquet 写入依赖，无法写入空问题账本。") from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=list(fields)).to_parquet(
        output_path,
        index=False,
        engine="pyarrow",
        compression="zstd",
    )
    return 0


def _normalize_issue_time(value: Any | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    return text


def _global_audit_status(status_counts: Counter[str]) -> str:
    if status_counts.get("failed", 0) or status_counts.get("duplicate_conflict_payload", 0):
        return "failed"
    if status_counts.get("needs_review", 0) or status_counts.get("missing_source_or_calendar_gap", 0):
        return "needs_review"
    return "success"


def _empty_formal_clean_frame(pd: Any) -> Any:
    return pd.DataFrame(columns=list(FORMAL_CLEAN_STK_MINS_FIELDS))


def _invalid_price(row: dict[str, Any]) -> bool:
    try:
        open_value = float(row.get("open"))
        close_value = float(row.get("close"))
        high_value = float(row.get("high"))
        low_value = float(row.get("low"))
    except (TypeError, ValueError):
        return True
    return open_value <= 0 or close_value <= 0 or high_value <= 0 or low_value <= 0 or high_value < low_value


def _invalid_volume_amount(row: dict[str, Any]) -> bool:
    for field in ("vol", "amount"):
        try:
            value = float(row.get(field) or 0)
        except (TypeError, ValueError):
            return True
        if value < 0:
            return True
    return False


def _numeric_series(frame: Any, field: str, pd: Any) -> Any:
    if field not in frame.columns:
        return pd.Series(float("nan"), index=frame.index)
    return pd.to_numeric(frame[field], errors="coerce")


def _partition_files(partition: Path) -> list[Path]:
    if not partition.exists():
        return []
    return sorted(path for path in partition.glob("*.parquet") if path.is_file())


def _row_count(files: list[Path] | tuple[Path, ...]) -> int:
    pq = _require_pyarrow_parquet()
    return sum(int(pq.ParquetFile(path).metadata.num_rows) for path in files)


def _replace_partition_keep_backup(*, tmp_partition: Path, final_partition: Path, backup_partition: Path) -> None:
    if backup_partition.exists():
        shutil.rmtree(backup_partition)
    final_partition.parent.mkdir(parents=True, exist_ok=True)
    backup_partition.parent.mkdir(parents=True, exist_ok=True)
    moved_final = False
    try:
        if final_partition.exists():
            final_partition.replace(backup_partition)
            moved_final = True
        tmp_partition.replace(final_partition)
    except Exception:
        if moved_final and backup_partition.exists() and not final_partition.exists():
            backup_partition.replace(final_partition)
        raise


def _parse_trade_date_partition(partition: Path) -> date | None:
    prefix = "trade_date="
    if not partition.name.startswith(prefix):
        return None
    return _parse_date(partition.name[len(prefix) :])


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    if len(text) == 8 and text.isdigit():
        return date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:8]}")
    return date.fromisoformat(text[:10])


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"


def _require_pyarrow_parquet():  # type: ignore[no-untyped-def]
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 pyarrow，无法读取 Parquet。请先安装 lake_console/backend/requirements.txt。") from exc
    return pq


def _require_pandas():  # type: ignore[no-untyped-def]
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 pandas，无法处理 Parquet。请先安装 lake_console/backend/requirements.txt。") from exc
    return pd
