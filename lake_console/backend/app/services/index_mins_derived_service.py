from __future__ import annotations

import math
import time as time_module
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.index_mins_common import parse_trade_time
from lake_console.backend.app.services.index_mins_universe_filter import (
    load_index_mins_universe_for_range,
)
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_files,
    read_parquet_row_count,
    replace_directory_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService
from lake_console.backend.app.sync.helpers.dates import load_open_trade_dates


SUPPORTED_INDEX_MINS_DERIVED_TARGETS = frozenset({"90min", "120min"})
_DERIVED_SOURCE_FREQ = {
    "90min": "30min",
    "120min": "60min",
}
_EXPECTED_SOURCE_ROWS_PER_CODE = {
    "90min": 9,
    "120min": 5,
}
_EXPECTED_DERIVED_ROWS_PER_CODE = {
    "90min": 3,
    "120min": 2,
}
_EXPECTED_SOURCE_SCHEDULE = {
    "90min": (
        time(9, 30),
        time(10, 0),
        time(10, 30),
        time(11, 0),
        time(11, 30),
        time(13, 30),
        time(14, 0),
        time(14, 30),
        time(15, 0),
    ),
    "120min": (
        time(9, 30),
        time(10, 30),
        time(11, 30),
        time(14, 0),
        time(15, 0),
    ),
}
_DERIVED_CHUNK_RANGES = {
    "90min": ((1, 4), (4, 7), (7, 9)),
    "120min": ((0, 2), (2, 4)),
}


@dataclass(frozen=True)
class _DerivedSourceGate:
    target_freq: str
    source_freq: str
    trade_date: date
    expected_source_rows: int
    expected_written_rows: int
    effective_ts_codes: tuple[str, ...]
    source_files: tuple[Path, ...]


class IndexMinsDerivedService:
    def __init__(self, *, lake_root: Path, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or print

    def derive_day(self, *, trade_date: date, targets: list[str]) -> dict[str, Any]:
        normalized_targets = _normalize_targets(targets)
        LakeRootService(self.lake_root).require_ready_for_write()
        run_id = _run_id("derive-index-mins")
        started_at = datetime.now(timezone.utc)
        started = time_module.monotonic()
        gates = self._prepare_day_gates(trade_date=trade_date, targets=normalized_targets)
        self.progress(
            f"[derive_index_mins] start run_id={run_id} trade_date={trade_date.isoformat()} targets={normalized_targets}"
        )
        summary = self._derive_day_with_gates(run_id=run_id, trade_date=trade_date, gates=gates)
        elapsed = time_module.monotonic() - started
        manifest_summary = {
            "dataset_key": "index_mins",
            "operation": "derive_index_mins",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "source_layer": "raw_tushare",
            "trade_date": trade_date.isoformat(),
            "targets": normalized_targets,
            "source_rows": summary["source_rows"],
            "written_rows": summary["written_rows"],
            "target_summaries": summary["target_summaries"],
            "outputs": summary["outputs"],
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(manifest_summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[derive_index_mins] done trade_date={trade_date.isoformat()} targets={normalized_targets} "
            f"source_rows={summary['source_rows']} written={summary['written_rows']} elapsed={math.ceil(elapsed)}s"
        )
        return manifest_summary

    def derive_range(self, *, start_date: date, end_date: date, targets: list[str]) -> dict[str, Any]:
        if end_date < start_date:
            raise ValueError("derive-index-mins-range 的 end-date 不能早于 start-date。")
        normalized_targets = _normalize_targets(targets)
        LakeRootService(self.lake_root).require_ready_for_write()
        trade_dates = load_open_trade_dates(lake_root=self.lake_root, start_date=start_date, end_date=end_date)
        if not trade_dates:
            raise RuntimeError(
                f"本地交易日历中 {start_date.isoformat()} ~ {end_date.isoformat()} 没有开市日。"
            )
        prevalidated_gates: dict[tuple[date, str], _DerivedSourceGate] = {}
        for current_trade_date in trade_dates:
            day_gates = self._prepare_day_gates(trade_date=current_trade_date, targets=normalized_targets)
            for target_freq, gate in day_gates.items():
                prevalidated_gates[(current_trade_date, target_freq)] = gate

        run_id = _run_id("derive-index-mins-range")
        started_at = datetime.now(timezone.utc)
        started = time_module.monotonic()
        self.progress(
            f"[derive_index_mins_range] start run_id={run_id} start_date={start_date.isoformat()} "
            f"end_date={end_date.isoformat()} trade_dates={len(trade_dates)} targets={normalized_targets}"
        )

        total_source_rows = 0
        total_written_rows = 0
        day_summaries: list[dict[str, Any]] = []
        for index, current_trade_date in enumerate(trade_dates, start=1):
            self.progress(
                f"[derive_index_mins_range] day={index}/{len(trade_dates)} trade_date={current_trade_date.isoformat()} "
                f"targets={normalized_targets}"
            )
            day_gates = {
                target_freq: prevalidated_gates[(current_trade_date, target_freq)]
                for target_freq in normalized_targets
            }
            day_summary = self._derive_day_with_gates(
                run_id=run_id,
                trade_date=current_trade_date,
                gates=day_gates,
            )
            day_summaries.append(day_summary)
            total_source_rows += int(day_summary["source_rows"])
            total_written_rows += int(day_summary["written_rows"])

        elapsed = time_module.monotonic() - started
        manifest_summary = {
            "dataset_key": "index_mins",
            "operation": "derive_index_mins_range",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "source_layer": "raw_tushare",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "trade_dates": [item.isoformat() for item in trade_dates],
            "trade_date_count": len(trade_dates),
            "targets": normalized_targets,
            "source_rows": total_source_rows,
            "written_rows": total_written_rows,
            "day_summaries": day_summaries,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(manifest_summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[derive_index_mins_range] done start_date={start_date.isoformat()} end_date={end_date.isoformat()} "
            f"trade_dates={len(trade_dates)} targets={normalized_targets} source_rows={total_source_rows} "
            f"written={total_written_rows} elapsed={math.ceil(elapsed)}s"
        )
        return manifest_summary

    def _prepare_day_gates(self, *, trade_date: date, targets: list[str]) -> dict[str, _DerivedSourceGate]:
        universe = load_index_mins_universe_for_range(
            lake_root=self.lake_root,
            start_date=trade_date,
            end_date=trade_date,
        )
        effective_ts_codes = tuple(sorted(universe.ts_codes))
        gates: dict[str, _DerivedSourceGate] = {}
        for target_freq in targets:
            source_freq = _DERIVED_SOURCE_FREQ[target_freq]
            source_partition = self._source_partition(freq=source_freq, trade_date=trade_date)
            source_files = tuple(sorted(source_partition.glob("*.parquet")))
            if not source_files:
                raise RuntimeError(
                    "derive-index-mins 缺少正式 raw 源分区："
                    f"target_freq={target_freq} source_freq={source_freq} trade_date={trade_date.isoformat()}"
                )
            expected_source_rows = len(effective_ts_codes) * _EXPECTED_SOURCE_ROWS_PER_CODE[target_freq]
            actual_source_rows = sum(read_parquet_row_count(path) for path in source_files)
            if actual_source_rows != expected_source_rows:
                raise RuntimeError(
                    "derive-index-mins 源分区行数不满足 completeness gate："
                    f"target_freq={target_freq} source_freq={source_freq} trade_date={trade_date.isoformat()} "
                    f"expected_rows={expected_source_rows} actual_rows={actual_source_rows}"
                )
            gates[target_freq] = _DerivedSourceGate(
                target_freq=target_freq,
                source_freq=source_freq,
                trade_date=trade_date,
                expected_source_rows=expected_source_rows,
                expected_written_rows=len(effective_ts_codes) * _EXPECTED_DERIVED_ROWS_PER_CODE[target_freq],
                effective_ts_codes=effective_ts_codes,
                source_files=source_files,
            )
        return gates

    def _derive_day_with_gates(
        self,
        *,
        run_id: str,
        trade_date: date,
        gates: dict[str, _DerivedSourceGate],
    ) -> dict[str, Any]:
        total_source_rows = 0
        total_written_rows = 0
        outputs: list[str] = []
        target_summaries: list[dict[str, Any]] = []
        for target_freq in sorted(gates):
            gate = gates[target_freq]
            source_rows = read_parquet_files(list(gate.source_files))
            derived_rows = derive_index_mins_rows(
                source_rows,
                target_freq=target_freq,
                trade_date=trade_date,
                effective_ts_codes=gate.effective_ts_codes,
            )
            if len(derived_rows) != gate.expected_written_rows:
                raise RuntimeError(
                    "derive-index-mins 写入行数不满足 completeness gate："
                    f"target_freq={target_freq} trade_date={trade_date.isoformat()} "
                    f"expected_rows={gate.expected_written_rows} actual_rows={len(derived_rows)}"
                )
            final_partition = self._target_partition(freq=target_freq, trade_date=trade_date)
            tmp_partition = self._tmp_target_partition(run_id=run_id, freq=target_freq, trade_date=trade_date)
            tmp_file = tmp_partition / "part-000.parquet"
            written = write_rows_to_parquet(derived_rows, tmp_file)
            validated = read_parquet_row_count(tmp_file)
            if validated != written:
                raise RuntimeError(
                    "derive-index-mins 派生分区校验失败："
                    f"target_freq={target_freq} trade_date={trade_date.isoformat()} "
                    f"written={written} validated={validated}"
                )
            replace_directory_atomically(
                tmp_dir=tmp_partition,
                final_dir=final_partition,
                backup_root=self.lake_root / "_tmp" / run_id / "_backup",
            )
            self.progress(
                f"[derive_index_mins] target={target_freq} trade_date={trade_date.isoformat()} "
                f"source_freq={gate.source_freq} source_rows={len(source_rows)} written={written}"
            )
            total_source_rows += len(source_rows)
            total_written_rows += written
            outputs.append(str(final_partition))
            target_summaries.append(
                {
                    "target_freq": target_freq,
                    "source_freq": gate.source_freq,
                    "expected_source_rows": gate.expected_source_rows,
                    "expected_written_rows": gate.expected_written_rows,
                    "source_rows": len(source_rows),
                    "written_rows": written,
                    "output": str(final_partition),
                }
            )
        return {
            "trade_date": trade_date.isoformat(),
            "source_rows": total_source_rows,
            "written_rows": total_written_rows,
            "outputs": outputs,
            "target_summaries": target_summaries,
        }

    def _source_partition(self, *, freq: str, trade_date: date) -> Path:
        return (
            self.lake_root
            / "raw_tushare"
            / "index_mins_by_date"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        )

    def _target_partition(self, *, freq: str, trade_date: date) -> Path:
        return (
            self.lake_root
            / "derived"
            / "index_mins_by_date"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        )

    def _tmp_target_partition(self, *, run_id: str, freq: str, trade_date: date) -> Path:
        return (
            self.lake_root
            / "_tmp"
            / run_id
            / "derived"
            / "index_mins_by_date"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        )


def derive_index_mins_rows(
    source_rows: list[dict[str, Any]],
    *,
    target_freq: str,
    trade_date: date,
    effective_ts_codes: tuple[str, ...],
) -> list[dict[str, Any]]:
    if target_freq not in SUPPORTED_INDEX_MINS_DERIVED_TARGETS:
        raise ValueError(f"不支持的 target_freq={target_freq}")

    effective_set = set(effective_ts_codes)
    expected_schedule = _EXPECTED_SOURCE_SCHEDULE[target_freq]
    rows_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        ts_code = str(row.get("ts_code") or "").strip().upper()
        if ts_code not in effective_set:
            raise RuntimeError(
                f"derive-index-mins 源分区包含非当日有效指数：ts_code={ts_code} trade_date={trade_date.isoformat()}"
            )
        trade_time = parse_trade_time(row.get("trade_time"))
        if trade_time.date() != trade_date:
            raise RuntimeError(
                f"derive-index-mins 源分区存在跨日行：ts_code={ts_code} trade_time={trade_time.isoformat()} "
                f"expected_trade_date={trade_date.isoformat()}"
            )
        rows_by_code[ts_code].append(row)

    missing_codes = [ts_code for ts_code in effective_ts_codes if ts_code not in rows_by_code]
    if missing_codes:
        preview = ",".join(missing_codes[:5])
        suffix = "..." if len(missing_codes) > 5 else ""
        raise RuntimeError(
            f"derive-index-mins 缺少有效指数的源行：trade_date={trade_date.isoformat()} "
            f"target_freq={target_freq} missing_ts_code={preview}{suffix}"
        )

    result: list[dict[str, Any]] = []
    for ts_code in effective_ts_codes:
        sorted_rows = sorted(rows_by_code[ts_code], key=lambda item: parse_trade_time(item.get("trade_time")))
        actual_schedule = tuple(parse_trade_time(row.get("trade_time")).time() for row in sorted_rows)
        if actual_schedule != expected_schedule:
            preview = ",".join(item.strftime("%H:%M") for item in actual_schedule)
            raise RuntimeError(
                f"derive-index-mins 源分钟锚点不符合当前口径："
                f"ts_code={ts_code} trade_date={trade_date.isoformat()} target_freq={target_freq} schedule={preview}"
            )
        for start, end in _DERIVED_CHUNK_RANGES[target_freq]:
            chunk = sorted_rows[start:end]
            if not chunk:
                continue
            result.append(_aggregate_chunk(ts_code=ts_code, target_freq=target_freq, chunk=chunk))

    result.sort(key=lambda item: parse_trade_time(item["trade_time"]))
    result.sort(key=lambda item: str(item["ts_code"]))
    return result


def _aggregate_chunk(*, ts_code: str, target_freq: str, chunk: list[dict[str, Any]]) -> dict[str, Any]:
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
    exchange = _first_non_blank_text(chunk, field="exchange")

    return {
        "ts_code": ts_code,
        "freq": target_freq,
        "trade_time": parse_trade_time(last_row.get("trade_time")),
        "open": open_value,
        "close": close_value,
        "high": high_value,
        "low": low_value,
        "vol": vol_value,
        "amount": amount_value,
        "exchange": exchange,
        "vwap": vwap_value,
    }


def _normalize_targets(targets: list[str]) -> list[str]:
    if not targets:
        raise ValueError("derive-index-mins 必须至少指定一个 target freq。")
    normalized = [str(item).strip() for item in targets if str(item).strip()]
    invalid = sorted(set(normalized) - SUPPORTED_INDEX_MINS_DERIVED_TARGETS)
    if invalid:
        allowed = ", ".join(sorted(SUPPORTED_INDEX_MINS_DERIVED_TARGETS))
        raise ValueError(f"不支持的 derived targets={invalid}，允许值：{allowed}")
    return list(dict.fromkeys(normalized))


def _required_number(value: Any, *, field: str) -> float:
    if value is None:
        raise RuntimeError(f"derive-index-mins 输入字段为空：field={field}")
    return float(value)


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _first_non_blank_text(rows: list[dict[str, Any]], *, field: str) -> str | None:
    for row in rows:
        value = row.get(field)
        if value in (None, ""):
            continue
        text = str(value).strip()
        if text:
            return text.upper()
    return None


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
