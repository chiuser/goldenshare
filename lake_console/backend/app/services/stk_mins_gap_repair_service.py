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


KNOWN_STK_MINS_SOURCE_GAPS_FROM_1M: dict[int, tuple[date, ...]] = {
    5: (
        date(2010, 9, 2),
    ),
    15: (
        date(2009, 5, 5),
        date(2009, 6, 5),
        date(2009, 12, 4),
    ),
}

SUPPORTED_STK_MINS_GAP_REPAIR_FREQS = frozenset(KNOWN_STK_MINS_SOURCE_GAPS_FROM_1M)

_MORNING_START = time(9, 30)
_MORNING_END = time(11, 30)
_AFTERNOON_START = time(13, 1)
_AFTERNOON_END = time(15, 0)


class StkMinsGapRepairService:
    def __init__(self, *, lake_root: Path, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or print

    def repair_day(self, *, trade_date: date, freq: int) -> dict[str, Any]:
        if freq not in SUPPORTED_STK_MINS_GAP_REPAIR_FREQS:
            allowed = ", ".join(str(item) for item in sorted(SUPPORTED_STK_MINS_GAP_REPAIR_FREQS))
            raise ValueError(f"repair-stk-mins-from-1m 仅支持 freq={allowed}。")
        allowed_dates = KNOWN_STK_MINS_SOURCE_GAPS_FROM_1M[freq]
        if trade_date not in allowed_dates:
            joined = ", ".join(item.isoformat() for item in allowed_dates)
            raise ValueError(
                f"trade_date={trade_date.isoformat()} 不在 freq={freq} 的已审计源端缺口白名单内。"
                f"当前允许日期：{joined}"
            )

        started_at = datetime.now(timezone.utc)
        started = time_module.monotonic()
        run_id = _run_id("repair-stk-mins-from-1m")
        LakeRootService(self.lake_root).require_ready_for_write()
        self.progress(
            f"[repair_stk_mins_from_1m] start run_id={run_id} trade_date={trade_date.isoformat()} target_freq={freq}"
        )

        source_partition = self._partition(freq=1, trade_date=trade_date)
        source_files = sorted(source_partition.glob("*.parquet"))
        if not source_files:
            raise RuntimeError(f"缺少 1 分钟源分区：{source_partition}")

        final_partition = self._partition(freq=freq, trade_date=trade_date)
        if final_partition.exists():
            raise RuntimeError(
                f"目标分区已存在，repair 不允许覆盖正式分区：{final_partition}"
            )

        source_rows = read_parquet_files(source_files)
        repaired_rows = derive_gap_rows(source_rows, target_freq=freq, trade_date=trade_date)
        if not repaired_rows:
            raise RuntimeError(
                f"1 分钟源分区存在，但无法生成 freq={freq} 修补结果：trade_date={trade_date.isoformat()}"
            )

        tmp_partition = self._tmp_partition(run_id=run_id, freq=freq, trade_date=trade_date)
        tmp_file = tmp_partition / "part-00000.parquet"
        written = write_rows_to_parquet(repaired_rows, tmp_file)
        validated = read_parquet_row_count(tmp_file)
        if validated != written:
            raise RuntimeError(f"repair_stk_mins_from_1m 校验失败：written={written} validated={validated}")
        replace_directory_atomically(
            tmp_dir=tmp_partition,
            final_dir=final_partition,
            backup_root=self.lake_root / "_tmp" / run_id / "_backup",
        )

        elapsed = time_module.monotonic() - started
        summary = {
            "dataset_key": "stk_mins",
            "operation": "repair_stk_mins_from_1m",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "trade_date": trade_date.isoformat(),
            "source_freq": 1,
            "target_freq": freq,
            "repair_reason": "source_gap",
            "known_source_gap_dates": [item.isoformat() for item in allowed_dates],
            "source_rows": len(source_rows),
            "written_rows": written,
            "output": str(final_partition),
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[repair_stk_mins_from_1m] done trade_date={trade_date.isoformat()} target_freq={freq} "
            f"source_rows={len(source_rows)} written={written} partition={final_partition} "
            f"elapsed={math.ceil(elapsed)}s"
        )
        return summary

    def _partition(self, *, freq: int, trade_date: date) -> Path:
        return self.lake_root / "raw_tushare" / "stk_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date.isoformat()}"

    def _tmp_partition(self, *, run_id: str, freq: int, trade_date: date) -> Path:
        return (
            self.lake_root
            / "_tmp"
            / run_id
            / "raw_tushare"
            / "stk_mins_by_date"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        )


def derive_gap_rows(source_rows: list[dict[str, Any]], *, target_freq: int, trade_date: date) -> list[dict[str, Any]]:
    if target_freq not in SUPPORTED_STK_MINS_GAP_REPAIR_FREQS:
        raise ValueError(f"不支持的 target_freq={target_freq}")

    group_size = target_freq
    rows_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        ts_code = str(row.get("ts_code") or "").strip()
        trade_time = _parse_trade_time(row.get("trade_time"))
        if not ts_code:
            continue
        if trade_time.date() != trade_date:
            raise RuntimeError(
                f"1 分钟源分区存在跨日行：ts_code={ts_code} trade_time={trade_time.isoformat()} "
                f"expected_trade_date={trade_date.isoformat()}"
            )
        rows_by_code[ts_code].append(row)

    output: list[dict[str, Any]] = []
    for ts_code in sorted(rows_by_code):
        sorted_rows = sorted(rows_by_code[ts_code], key=lambda item: _parse_trade_time(item.get("trade_time")))
        morning_rows, afternoon_rows, unexpected_rows = _split_sessions(sorted_rows)
        if unexpected_rows:
            preview = ", ".join(_parse_trade_time(item.get("trade_time")).isoformat() for item in unexpected_rows[:5])
            raise RuntimeError(
                f"ts_code={ts_code} 存在非交易时段分钟线，当前 repair 不接受：{preview}"
            )

        output.extend(_build_session_buckets(ts_code=ts_code, target_freq=target_freq, rows=morning_rows, first_bucket_singleton=True))
        output.extend(_build_session_buckets(ts_code=ts_code, target_freq=target_freq, rows=afternoon_rows, first_bucket_singleton=False))

    output.sort(key=lambda item: item["trade_time"], reverse=True)
    output.sort(key=lambda item: str(item["ts_code"]))
    return output


def _split_sessions(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    morning_rows: list[dict[str, Any]] = []
    afternoon_rows: list[dict[str, Any]] = []
    unexpected_rows: list[dict[str, Any]] = []
    for row in rows:
        trade_time = _parse_trade_time(row.get("trade_time")).time()
        if _MORNING_START <= trade_time <= _MORNING_END:
            morning_rows.append(row)
        elif _AFTERNOON_START <= trade_time <= _AFTERNOON_END:
            afternoon_rows.append(row)
        else:
            unexpected_rows.append(row)
    return morning_rows, afternoon_rows, unexpected_rows


def _build_session_buckets(
    *,
    ts_code: str,
    target_freq: int,
    rows: list[dict[str, Any]],
    first_bucket_singleton: bool,
) -> list[dict[str, Any]]:
    if not rows:
        return []

    remaining_rows = rows
    buckets: list[dict[str, Any]] = []
    if first_bucket_singleton:
        first_trade_time = _parse_trade_time(rows[0].get("trade_time")).time()
        if first_trade_time != _MORNING_START:
            raise RuntimeError(
                f"ts_code={ts_code} 早盘第一根不是 09:30，无法按现有 5/15 分钟口径修补：first_trade_time={first_trade_time}"
            )
        buckets.append(_aggregate_chunk(ts_code=ts_code, target_freq=target_freq, chunk=[rows[0]]))
        remaining_rows = rows[1:]

    if not remaining_rows:
        return buckets

    if len(remaining_rows) % target_freq != 0:
        raise RuntimeError(
            f"ts_code={ts_code} session 分钟线数量无法整除 target_freq={target_freq}：rows={len(remaining_rows)}"
        )

    for start in range(0, len(remaining_rows), target_freq):
        chunk = remaining_rows[start : start + target_freq]
        buckets.append(_aggregate_chunk(ts_code=ts_code, target_freq=target_freq, chunk=chunk))
    return buckets


def _aggregate_chunk(*, ts_code: str, target_freq: int, chunk: list[dict[str, Any]]) -> dict[str, Any]:
    if not chunk:
        raise ValueError("chunk 不能为空。")
    open_value = _required_number(chunk[0].get("open"), field="open")
    close_value = _required_number(chunk[-1].get("close"), field="close")
    high_value = max(_required_number(row.get("high"), field="high") for row in chunk)
    low_value = min(_required_number(row.get("low"), field="low") for row in chunk)
    vol_value = sum(_required_number(row.get("vol"), field="vol") for row in chunk)
    amount_value = sum(_required_number(row.get("amount"), field="amount") for row in chunk)
    last_row = chunk[-1]
    last_vwap = _optional_number(last_row.get("vwap"))
    if vol_value > 0:
        vwap_value = round(amount_value / vol_value, 3)
    elif last_vwap is not None:
        vwap_value = last_vwap
    else:
        vwap_value = close_value

    return {
        "ts_code": ts_code,
        "freq": target_freq,
        "trade_time": _parse_trade_time(last_row.get("trade_time")),
        "open": open_value,
        "close": close_value,
        "high": high_value,
        "low": low_value,
        "vol": vol_value,
        "amount": amount_value,
        "exchange": _first_non_empty_text(chunk),
        "vwap": vwap_value,
    }


def _first_non_empty_text(rows: list[dict[str, Any]]) -> str | None:
    for row in rows:
        value = _normalize_optional_text(row.get("exchange"))
        if value is not None:
            return value
    return None


def _required_number(value: Any, *, field: str) -> float:
    number = _optional_number(value)
    if number is None:
        raise RuntimeError(f"分钟线 repair 缺少数值字段 {field}")
    return number


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return float(value)


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def _parse_trade_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value is None:
        raise RuntimeError("分钟线 repair 缺少 trade_time")
    return datetime.fromisoformat(str(value))


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
