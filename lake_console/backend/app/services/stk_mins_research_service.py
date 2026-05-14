from __future__ import annotations

import hashlib
import math
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    replace_directory_atomically,
)
from lake_console.backend.app.services.stk_mins_clean_next_gate import CleanNextGateBlockedError, CleanNextPartitionGateService, clean_next_partition_key
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


RAW_FREQS = {1, 5, 15, 30, 60}
DERIVED_FREQS = {90, 120}


class StkMinsResearchService:
    def __init__(self, *, lake_root: Path, bucket_count: int, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.bucket_count = bucket_count
        self.progress = progress or print

    def rebuild_month(
        self,
        *,
        freq: int,
        trade_month: str,
        gate_rows_by_key: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if freq not in RAW_FREQS | DERIVED_FREQS:
            raise ValueError("research 重排仅支持 freq=1/5/15/30/60/90/120。")
        if self.bucket_count <= 0:
            raise ValueError("bucket_count 必须大于 0。")
        _validate_trade_month(trade_month)

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("research-stk-mins")
        LakeRootService(self.lake_root).require_ready_for_write()
        source_node_key = "clean_next_by_date" if freq in RAW_FREQS else "derived_by_date"
        source_root = _source_root(lake_root=self.lake_root, source_node_key=source_node_key, freq=freq)
        source_files = _month_source_files(source_root=source_root, trade_month=trade_month)
        if not source_files:
            raise RuntimeError(f"缺少可重排源文件：{source_root}/trade_date={trade_month}-*/")
        if freq in RAW_FREQS:
            _require_clean_next_gate_for_files(
                lake_root=self.lake_root,
                freq=freq,
                source_files=source_files,
                gate_rows_by_key=gate_rows_by_key,
            )

        tmp_month = (
            self.lake_root
            / "_tmp"
            / run_id
            / "research"
            / "stk_mins_by_symbol_month"
            / f"freq={freq}"
            / f"trade_month={trade_month}"
        )
        final_month = (
            self.lake_root
            / "research"
            / "stk_mins_by_symbol_month"
            / f"freq={freq}"
            / f"trade_month={trade_month}"
        )
        self.progress(
            f"[research_stk_mins] start run_id={run_id} freq={freq} trade_month={trade_month} "
            f"source_node_key={source_node_key} source_files={len(source_files)} buckets={self.bucket_count}"
        )
        source_rows, bucket_counts = _write_month_buckets_streaming(
            source_files=source_files,
            tmp_month=tmp_month,
            bucket_count=self.bucket_count,
        )
        written_total = 0
        for bucket, written in sorted(bucket_counts.items()):
            tmp_file = tmp_month / f"bucket={bucket}" / "part-000.parquet"
            validated = read_parquet_row_count(tmp_file)
            if validated != written:
                raise RuntimeError(f"research bucket 校验失败：written={written} validated={validated} file={tmp_file}")
            written_total += written
            self.progress(f"[research_stk_mins] bucket={bucket} written={written} accumulated={written_total}")

        replace_directory_atomically(
            tmp_dir=tmp_month,
            final_dir=final_month,
            backup_root=self.lake_root / "_tmp" / run_id / "_backup",
        )
        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "stk_mins",
            "operation": "research_stk_mins",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "freq": freq,
            "trade_month": trade_month,
            "source_node_key": source_node_key,
            "source_files": len(source_files),
            "source_rows": source_rows,
            "bucket_count": self.bucket_count,
            "written_rows": written_total,
            "output": str(final_month),
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[research_stk_mins] done freq={freq} trade_month={trade_month} "
            f"source_rows={source_rows} written={written_total} output={final_month} elapsed={math.ceil(elapsed)}s"
        )
        return summary

    def rebuild_range(self, *, freqs: list[int], start_month: str, end_month: str) -> dict[str, Any]:
        if not freqs:
            raise ValueError("rebuild-stk-mins-research-range 必须至少指定一个 freq。")
        invalid_freqs = sorted(set(freqs) - (RAW_FREQS | DERIVED_FREQS))
        if invalid_freqs:
            raise ValueError(f"research 重排仅支持 freq=1/5/15/30/60/90/120，不支持 {invalid_freqs}。")
        if self.bucket_count <= 0:
            raise ValueError("bucket_count 必须大于 0。")
        months = list_trade_months(start_month=start_month, end_month=end_month)
        if not months:
            raise ValueError("rebuild-stk-mins-research-range 没有可重建月份。")

        LakeRootService(self.lake_root).require_ready_for_write()
        missing_sources = _missing_month_sources(lake_root=self.lake_root, freqs=freqs, trade_months=months)
        if missing_sources:
            preview = "\n".join(str(item) for item in missing_sources[:10])
            suffix = "" if len(missing_sources) <= 10 else f"\n... 另有 {len(missing_sources) - 10} 个缺失源月份"
            raise RuntimeError(f"rebuild-stk-mins-research-range 缺少源文件，未执行任何写入：\n{preview}{suffix}")
        gate_rows_by_key = _gate_rows_by_key(lake_root=self.lake_root)
        gate_errors = _month_gate_errors(
            lake_root=self.lake_root,
            freqs=freqs,
            trade_months=months,
            gate_rows_by_key=gate_rows_by_key,
        )
        if gate_errors:
            preview = "\n".join(gate_errors[:10])
            suffix = "" if len(gate_errors) <= 10 else f"\n... 另有 {len(gate_errors) - 10} 个 gate 问题"
            raise RuntimeError(f"rebuild-stk-mins-research-range 源 clean_next gate 未通过，未执行任何写入：\n{preview}{suffix}")

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("research-stk-mins-range")
        units_total = len(freqs) * len(months)
        self.progress(
            f"[research_stk_mins_range] start run_id={run_id} start_month={start_month} "
            f"end_month={end_month} months={len(months)} freqs={freqs} units_total={units_total}"
        )

        summaries: list[dict[str, Any]] = []
        total_source_rows = 0
        total_written_rows = 0
        unit = 0
        for freq in freqs:
            for trade_month in months:
                unit += 1
                self.progress(
                    f"[research_stk_mins_range] unit={unit}/{units_total} "
                    f"freq={freq} trade_month={trade_month}"
                )
                summary = self.rebuild_month(freq=freq, trade_month=trade_month, gate_rows_by_key=gate_rows_by_key)
                summaries.append(summary)
                total_source_rows += int(summary.get("source_rows") or 0)
                total_written_rows += int(summary.get("written_rows") or 0)

        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "stk_mins",
            "operation": "research_stk_mins_range",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "start_month": start_month,
            "end_month": end_month,
            "trade_months": months,
            "freqs": freqs,
            "units_total": units_total,
            "source_rows": total_source_rows,
            "written_rows": total_written_rows,
            "unit_summaries": summaries,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[research_stk_mins_range] done start_month={start_month} end_month={end_month} "
            f"months={len(months)} freqs={freqs} source_rows={total_source_rows} "
            f"written={total_written_rows} elapsed={math.ceil(elapsed)}s"
        )
        return summary


def bucket_rows(*, rows: list[dict[str, Any]], bucket_count: int) -> dict[int, list[dict[str, Any]]]:
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        bucket_key = _bucket_key(row)
        if not bucket_key:
            continue
        bucket = stable_bucket(ts_code=bucket_key, bucket_count=bucket_count)
        buckets[bucket].append(row)
    return buckets


def _write_month_buckets_streaming(*, source_files: list[Path], tmp_month: Path, bucket_count: int) -> tuple[int, dict[int, int]]:
    """Rewrite by-date files into monthly buckets without loading a full month into memory."""
    pa, pq = _require_pyarrow()
    writers: dict[int, Any] = {}
    bucket_counts: dict[int, int] = defaultdict(int)
    source_rows = 0
    try:
        for source_file in source_files:
            parquet_file = pq.ParquetFile(source_file)
            for batch in parquet_file.iter_batches(batch_size=100_000):
                table = _normalize_stk_mins_table_schema(pa.Table.from_batches([batch]), pa=pa)
                rows = table.to_pylist()
                if not rows:
                    continue
                source_rows += len(rows)
                rows_by_bucket: dict[int, list[dict[str, Any]]] = defaultdict(list)
                for row in rows:
                    bucket_key = _bucket_key(row)
                    if not bucket_key:
                        continue
                    bucket = stable_bucket(ts_code=bucket_key, bucket_count=bucket_count)
                    rows_by_bucket[bucket].append(row)
                for bucket, bucket_rows_value in rows_by_bucket.items():
                    bucket_file = tmp_month / f"bucket={bucket}" / "part-000.parquet"
                    bucket_file.parent.mkdir(parents=True, exist_ok=True)
                    bucket_table = pa.Table.from_pylist(bucket_rows_value, schema=table.schema)
                    writer = writers.get(bucket)
                    if writer is None:
                        writer = pq.ParquetWriter(bucket_file, bucket_table.schema, compression="zstd")
                        writers[bucket] = writer
                    writer.write_table(bucket_table)
                    bucket_counts[bucket] += len(bucket_rows_value)
    finally:
        for writer in writers.values():
            writer.close()
    return source_rows, dict(bucket_counts)


def _normalize_stk_mins_table_schema(table: Any, *, pa: Any) -> Any:
    """Keep monthly streaming writers stable when a batch has all-null optional fields."""
    expected_types = {
        "ts_code": pa.large_string(),
        "freq": pa.int64(),
        "trade_date": pa.large_string(),
        "trade_time": pa.timestamp("us"),
        "open": pa.float64(),
        "close": pa.float64(),
        "high": pa.float64(),
        "low": pa.float64(),
        "vol": pa.int64(),
        "amount": pa.float64(),
        "exchange": pa.large_string(),
        "vwap": pa.float64(),
    }
    fields = [pa.field(field.name, expected_types.get(field.name, field.type)) for field in table.schema]
    return table.cast(pa.schema(fields), safe=False)


def stable_bucket(*, ts_code: str, bucket_count: int) -> int:
    digest = hashlib.sha256(ts_code.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % bucket_count


def _month_source_files(*, source_root: Path, trade_month: str) -> list[Path]:
    files: list[Path] = []
    for partition in sorted(source_root.glob(f"trade_date={trade_month}-*")):
        files.extend(sorted(partition.glob("*.parquet")))
    return files


def list_trade_months(*, start_month: str, end_month: str) -> list[str]:
    start_year, start_month_value = _parse_trade_month(start_month)
    end_year, end_month_value = _parse_trade_month(end_month)
    if (end_year, end_month_value) < (start_year, start_month_value):
        raise ValueError("end-month 不能早于 start-month。")

    months: list[str] = []
    year = start_year
    month = start_month_value
    while (year, month) <= (end_year, end_month_value):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def _missing_month_sources(*, lake_root: Path, freqs: list[int], trade_months: list[str]) -> list[Path]:
    missing: list[Path] = []
    for freq in freqs:
        source_node_key = "clean_next_by_date" if freq in RAW_FREQS else "derived_by_date"
        source_root = _source_root(lake_root=lake_root, source_node_key=source_node_key, freq=freq)
        for trade_month in trade_months:
            if not _month_source_files(source_root=source_root, trade_month=trade_month):
                missing.append(source_root / f"trade_date={trade_month}-*")
    return missing


def _month_gate_errors(
    *,
    lake_root: Path,
    freqs: list[int],
    trade_months: list[str],
    gate_rows_by_key: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    for freq in freqs:
        if freq not in RAW_FREQS:
            continue
        source_root = _source_root(lake_root=lake_root, source_node_key="clean_next_by_date", freq=freq)
        for trade_month in trade_months:
            source_files = _month_source_files(source_root=source_root, trade_month=trade_month)
            try:
                _require_clean_next_gate_for_files(
                    lake_root=lake_root,
                    freq=freq,
                    source_files=source_files,
                    gate_rows_by_key=gate_rows_by_key,
                )
            except CleanNextGateBlockedError as exc:
                errors.append(str(exc))
    return errors


def _source_root(*, lake_root: Path, source_node_key: str, freq: int) -> Path:
    if source_node_key == "clean_next_by_date":
        return lake_root / "research" / "stk_mins_by_date_clean_next" / f"freq={freq}"
    if source_node_key == "derived_by_date":
        return lake_root / "derived" / "stk_mins_by_date" / f"freq={freq}"
    raise ValueError(f"不支持的 stk_mins research source_node_key={source_node_key}")


def _require_clean_next_gate_for_files(
    *,
    lake_root: Path,
    freq: int,
    source_files: list[Path],
    gate_rows_by_key: dict[str, dict[str, Any]] | None = None,
) -> None:
    service = None if gate_rows_by_key is not None else CleanNextPartitionGateService(lake_root=lake_root)
    for trade_date in sorted({_parse_partition_date(path.parent) for path in source_files}):
        if trade_date is None:
            continue
        if gate_rows_by_key is None:
            assert service is not None
            service.require_passed(freq=freq, trade_date=trade_date)
            continue
        partition_key = clean_next_partition_key(freq=freq, trade_date=trade_date)
        row = gate_rows_by_key.get(partition_key)
        if not row:
            raise CleanNextGateBlockedError(f"clean_next gate 缺少分区状态：{partition_key}")
        if str(row.get("status") or "") != "passed":
            ledger_path = row.get("ledger_path") or "-"
            raise CleanNextGateBlockedError(f"clean_next gate 未通过：{partition_key} status={row.get('status')} ledger={ledger_path}")


def _gate_rows_by_key(*, lake_root: Path) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("partition_key") or ""): row
        for row in CleanNextPartitionGateService(lake_root=lake_root).read_statuses()
        if str(row.get("partition_key") or "")
    }


def _parse_partition_date(partition: Path) -> date | None:
    prefix = "trade_date="
    if not partition.name.startswith(prefix):
        return None
    try:
        return date.fromisoformat(partition.name[len(prefix) :])
    except ValueError:
        return None


def _bucket_key(row: dict[str, Any]) -> str:
    return str(row.get("ts_code") or "").strip()


def _validate_trade_month(value: str) -> None:
    _parse_trade_month(value)


def _parse_trade_month(value: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError("trade_month 必须是 YYYY-MM 格式。") from exc
    return parsed.year, parsed.month


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"


def _require_pyarrow():  # type: ignore[no-untyped-def]
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 pyarrow，无法流式重排 stk_mins research。请先安装 lake_console/backend/requirements.txt。") from exc
    return pa, pq
