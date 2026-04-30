from __future__ import annotations

import math
import time as time_module
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_files,
    read_parquet_row_count,
    replace_directory_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


DERIVED_FREQ_MAP = {
    90: (30, 3),
    120: (60, 2),
}


class StkMinsDerivedService:
    def __init__(self, *, lake_root: Path, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or print

    def derive_day(self, *, trade_date: date, targets: list[int]) -> dict[str, Any]:
        if not targets:
            raise ValueError("derive-stk-mins 必须至少指定一个 target freq。")
        invalid = sorted(set(targets) - set(DERIVED_FREQ_MAP))
        if invalid:
            raise ValueError(f"不支持的派生 freq={invalid}，当前仅支持 90 和 120。")

        started_at = datetime.now(timezone.utc)
        started = time_module.monotonic()
        run_id = _run_id("derive-stk-mins")
        LakeRootService(self.lake_root).require_ready_for_write()
        self.progress(f"[derive_stk_mins] start run_id={run_id} trade_date={trade_date.isoformat()} targets={targets}")

        total_source_rows = 0
        total_written_rows = 0
        outputs: list[str] = []
        for target_freq in targets:
            source_freq, group_size = DERIVED_FREQ_MAP[target_freq]
            source_partition = (
                self.lake_root
                / "raw_tushare"
                / "stk_mins_by_date"
                / f"freq={source_freq}"
                / f"trade_date={trade_date.isoformat()}"
            )
            source_files = sorted(source_partition.glob("*.parquet"))
            if not source_files:
                raise RuntimeError(f"缺少源分区：{source_partition}")

            source_rows = read_parquet_files(source_files)
            derived_rows = derive_rows(source_rows, target_freq=target_freq, group_size=group_size)
            total_source_rows += len(source_rows)
            self.progress(
                f"[derive_stk_mins] target={target_freq} source_freq={source_freq} "
                f"source_rows={len(source_rows)} derived_rows={len(derived_rows)}"
            )
            if not derived_rows:
                continue

            final_partition = (
                self.lake_root
                / "derived"
                / "stk_mins_by_date"
                / f"freq={target_freq}"
                / f"trade_date={trade_date.isoformat()}"
            )
            tmp_partition = (
                self.lake_root
                / "_tmp"
                / run_id
                / "derived"
                / "stk_mins_by_date"
                / f"freq={target_freq}"
                / f"trade_date={trade_date.isoformat()}"
            )
            tmp_file = tmp_partition / "part-000.parquet"
            written = write_rows_to_parquet(derived_rows, tmp_file)
            validated = read_parquet_row_count(tmp_file)
            if validated != written:
                raise RuntimeError(f"派生分区校验失败：written={written} validated={validated} file={tmp_file}")
            replace_directory_atomically(
                tmp_dir=tmp_partition,
                final_dir=final_partition,
                backup_root=self.lake_root / "_tmp" / run_id / "_backup",
            )
            total_written_rows += written
            outputs.append(str(final_partition))
            self.progress(f"[derive_stk_mins] target_done={target_freq} written={written} partition={final_partition}")

        elapsed = time_module.monotonic() - started
        summary = {
            "dataset_key": "stk_mins",
            "operation": "derive_stk_mins",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "trade_date": trade_date.isoformat(),
            "targets": targets,
            "source_rows": total_source_rows,
            "written_rows": total_written_rows,
            "outputs": outputs,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[derive_stk_mins] done trade_date={trade_date.isoformat()} targets={targets} "
            f"source_rows={total_source_rows} written={total_written_rows} elapsed={math.ceil(elapsed)}s"
        )
        return summary


def derive_rows(source_rows: list[dict[str, Any]], *, target_freq: int, group_size: int) -> list[dict[str, Any]]:
    rows_by_code_session: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        ts_code = str(row.get("ts_code") or "").strip()
        if ts_code:
            rows_by_code_session[(ts_code, _session_key(row.get("trade_time")))].append(row)

    result: list[dict[str, Any]] = []
    for (ts_code, _session), rows in sorted(rows_by_code_session.items()):
        sorted_rows = sorted(rows, key=lambda item: str(item.get("trade_time") or ""))
        for start in range(0, len(sorted_rows), group_size):
            chunk = sorted_rows[start : start + group_size]
            if len(chunk) < group_size:
                continue
            result.append(_aggregate_chunk(ts_code=ts_code, target_freq=target_freq, chunk=chunk))
    return result


def _aggregate_chunk(*, ts_code: str, target_freq: int, chunk: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ts_code": ts_code,
        "freq": target_freq,
        "trade_time": chunk[-1].get("trade_time"),
        "open": chunk[0].get("open"),
        "close": chunk[-1].get("close"),
        "high": max(_number(row.get("high")) for row in chunk),
        "low": min(_number(row.get("low")) for row in chunk),
        "vol": sum(_number(row.get("vol")) for row in chunk),
        "amount": sum(_number(row.get("amount")) for row in chunk),
    }


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _session_key(value: Any) -> str:
    trade_time = _parse_trade_time(value)
    if trade_time is None:
        return "unknown"
    session = "am" if trade_time.time() < time(12, 0) else "pm"
    return f"{trade_time.date().isoformat()}-{session}"


def _parse_trade_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    raw_value = str(value).strip()
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value.replace("T", " "))
    except ValueError:
        return None


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
