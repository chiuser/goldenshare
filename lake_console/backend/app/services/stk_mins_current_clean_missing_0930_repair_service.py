from __future__ import annotations

import csv
import time as time_module
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    replace_directory_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


INPUT_CSV_PATH = Path("/tmp/stk_mins_clean_missing_0930_with_1min_availability.csv")
SOURCE_FREQ = 1
TARGET_FREQS: tuple[int, ...] = (5, 15, 30, 60)
TARGET_SCHEMA = (
    "ts_code",
    "freq",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
    "trade_date",
)
_TARGET_ROW_TIME = time(9, 30, 0)


class StkMinsCurrentCleanMissing0930RepairService:
    """Repair missing 09:30 rows for current wrong clean dataset from a fixed CSV allowlist."""

    def __init__(
        self,
        *,
        lake_root: Path,
        progress: Callable[[str], None] | None = None,
        csv_path: Path | None = None,
    ) -> None:
        self.lake_root = lake_root
        self.progress = progress or (lambda message: print(message, flush=True))
        self.csv_path = csv_path or INPUT_CSV_PATH

    def repair(self, *, dry_run: bool, apply: bool) -> dict[str, Any]:
        if dry_run == apply:
            raise ValueError("必须且只能指定 --dry-run 或 --apply。")

        started_at = datetime.now(timezone.utc)
        started = time_module.monotonic()
        targets_by_partition = self._load_targets_from_csv()
        if not targets_by_partition:
            raise RuntimeError("指定 CSV 中没有命中可修复的 09:30 目标。")

        partition_stats: list[dict[str, Any]] = []
        apply_partition_stats: list[dict[str, Any]] = []
        total_targets = 0
        total_source_missing = 0
        total_source_duplicate = 0
        total_already_present = 0
        total_to_insert = 0
        total_rows_before = 0
        total_rows_after = 0
        total_partitions_written = 0

        run_id = _run_id("repair-current-clean-missing-0930") if apply else None
        if apply:
            LakeRootService(self.lake_root).require_ready_for_write()
            self.progress(
                "[repair_current_clean_missing_0930] start "
                f"run_id={run_id} csv={self.csv_path}"
            )

        ordered_keys = sorted(targets_by_partition.keys(), key=lambda item: (item[0], item[1]))
        total_partitions = len(ordered_keys)
        for index, (trade_date, freq) in enumerate(ordered_keys, start=1):
            codes = targets_by_partition[(trade_date, freq)]
            plan = self._build_partition_plan(trade_date=trade_date, freq=freq, target_codes=codes)

            partition_stats.append(plan["dry_run"])
            total_targets += plan["targets"]
            total_source_missing += plan["source_missing"]
            total_source_duplicate += plan["source_duplicate"]
            total_already_present += plan["already_present"]
            total_to_insert += plan["to_insert"]
            total_rows_before += plan["rows_before"]
            total_rows_after += plan["rows_after"]

            if apply and run_id:
                apply_stats = self._apply_partition_plan(run_id=run_id, plan=plan)
                apply_partition_stats.append(apply_stats)
                if apply_stats["written"]:
                    total_partitions_written += 1
                self.progress(
                    f"[repair_current_clean_missing_0930] partition={index}/{len(ordered_keys)} "
                    f"trade_date={trade_date.isoformat()} freq={freq} targets={plan['targets']} "
                    f"already_present={plan['already_present']} to_insert={plan['to_insert']} "
                    f"rows_before={plan['rows_before']} rows_after={plan['rows_after']} "
                    f"written={apply_stats['written']}"
                )
            elif index == 1 or index % 50 == 0 or index == total_partitions:
                self.progress(
                    f"[repair_current_clean_missing_0930] dry_run partition={index}/{total_partitions} "
                    f"trade_date={trade_date.isoformat()} freq={freq} targets={plan['targets']} "
                    f"already_present={plan['already_present']} to_insert={plan['to_insert']}"
                )

        if run_id:
            TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)

        elapsed = time_module.monotonic() - started
        summary = {
            "operation": "repair_current_clean_missing_0930",
            "mode": "apply" if apply else "dry_run",
            "dataset_layer": "research/stk_mins_by_date_clean",
            "schema_mode": "current_wrong_clean_10_columns",
            "csv_path": str(self.csv_path),
            "source_freq": SOURCE_FREQ,
            "target_freqs": list(TARGET_FREQS),
            "target_row_time": "09:30:00",
            "partition_count": len(ordered_keys),
            "targets_total": total_targets,
            "source_missing_total": total_source_missing,
            "source_duplicate_total": total_source_duplicate,
            "already_present_total": total_already_present,
            "to_insert_total": total_to_insert,
            "rows_before_total": total_rows_before,
            "rows_after_total": total_rows_after,
            "net_reduction_total": total_rows_before - total_rows_after,
            "partitions_written_total": total_partitions_written if apply else 0,
            "dry_run_partition_stats": partition_stats,
            "apply_partition_stats": apply_partition_stats if apply else None,
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "write_intent": apply,
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        return summary

    def _load_targets_from_csv(self) -> dict[tuple[date, int], list[str]]:
        if not self.csv_path.exists():
            raise RuntimeError(f"缺少指定 CSV：{self.csv_path}")

        required_columns = {
            "issue_type",
            "action",
            "latest_ts_code",
            "freq",
            "trade_date",
            "has_clean_1min_0930",
        }
        grouped: dict[tuple[date, int], set[str]] = defaultdict(set)
        with self.csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise RuntimeError(f"CSV 缺少表头：{self.csv_path}")
            missing_columns = [column for column in sorted(required_columns) if column not in reader.fieldnames]
            if missing_columns:
                raise RuntimeError(f"CSV 缺少必要列：{','.join(missing_columns)} path={self.csv_path}")

            for row in reader:
                if str(row.get("issue_type") or "").strip() != "missing_intraday_bar":
                    continue
                if str(row.get("action") or "").strip() != "repair_required":
                    continue
                has_clean = str(row.get("has_clean_1min_0930") or "").strip().lower()
                if has_clean != "true":
                    continue
                freq = _parse_int(row.get("freq"))
                if freq not in TARGET_FREQS:
                    continue
                trade_date = _parse_date(row.get("trade_date"))
                ts_code = str(row.get("latest_ts_code") or "").strip()
                if not ts_code:
                    continue
                grouped[(trade_date, freq)].add(ts_code)

        return {
            (trade_date, freq): sorted(codes)
            for (trade_date, freq), codes in grouped.items()
            if codes
        }

    def _build_partition_plan(
        self,
        *,
        trade_date: date,
        freq: int,
        target_codes: list[str],
    ) -> dict[str, Any]:
        source_partition = self._partition(freq=SOURCE_FREQ, trade_date=trade_date)
        target_partition = self._partition(freq=freq, trade_date=trade_date)

        source_frame = _read_partition_frame(source_partition)
        target_frame = _read_partition_frame(target_partition)
        self._assert_schema(source_frame, partition=str(source_partition))
        self._assert_schema(target_frame, partition=str(target_partition))

        source_rows = [_normalize_row(row) for row in _rows_from_frame(source_frame)]
        target_rows = [_normalize_row(row) for row in _rows_from_frame(target_frame)]
        self._assert_unique_key(rows=target_rows, partition=str(target_partition))

        source_0930_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in source_rows:
            if _parse_trade_time(row.get("trade_time")).time() != _TARGET_ROW_TIME:
                continue
            source_0930_candidates[str(row.get("ts_code") or "")].append(row)

        source_0930_map: dict[str, dict[str, Any]] = {}
        source_missing_codes: list[str] = []
        source_duplicate_codes: list[str] = []
        for ts_code in target_codes:
            matched = source_0930_candidates.get(ts_code, [])
            if not matched:
                source_missing_codes.append(ts_code)
                continue
            if len(matched) > 1:
                source_duplicate_codes.append(ts_code)
                continue
            source_0930_map[ts_code] = matched[0]

        if source_missing_codes or source_duplicate_codes:
            raise RuntimeError(
                f"09:30 源门禁失败：trade_date={trade_date.isoformat()} freq={freq} "
                f"source_missing={_preview(source_missing_codes)} "
                f"source_duplicate={_preview(source_duplicate_codes)}"
            )

        target_0930_existing = {
            str(row.get("ts_code") or "")
            for row in target_rows
            if _parse_trade_time(row.get("trade_time")).time() == _TARGET_ROW_TIME
        }
        already_present_codes = [code for code in target_codes if code in target_0930_existing]
        to_insert_codes = [code for code in target_codes if code not in target_0930_existing]

        insert_rows = [
            _normalize_output_row(
                {
                    "ts_code": code,
                    "freq": freq,
                    "trade_time": _parse_trade_time(source_0930_map[code]["trade_time"]),
                    "open": float(source_0930_map[code]["open"]),
                    "close": float(source_0930_map[code]["close"]),
                    "high": float(source_0930_map[code]["high"]),
                    "low": float(source_0930_map[code]["low"]),
                    "vol": int(source_0930_map[code]["vol"]),
                    "amount": float(source_0930_map[code]["amount"]),
                    "trade_date": trade_date,
                }
            )
            for code in to_insert_codes
        ]
        final_rows = [_normalize_output_row(row) for row in target_rows + insert_rows]
        self._assert_unique_key(rows=final_rows, partition=str(target_partition))
        self._assert_output_schema(rows=final_rows, partition=str(target_partition))

        return {
            "trade_date": trade_date,
            "freq": freq,
            "target_partition": str(target_partition),
            "targets": len(target_codes),
            "source_missing": 0,
            "source_duplicate": 0,
            "already_present": len(already_present_codes),
            "to_insert": len(to_insert_codes),
            "rows_before": len(target_rows),
            "rows_after": len(final_rows),
            "insert_rows_payload": insert_rows,
            "final_rows_payload": final_rows,
            "dry_run": {
                "trade_date": trade_date.isoformat(),
                "freq": freq,
                "partition": str(target_partition),
                "targets": len(target_codes),
                "source_missing": 0,
                "source_duplicate": 0,
                "already_present": len(already_present_codes),
                "to_insert": len(to_insert_codes),
                "rows_before": len(target_rows),
                "rows_after": len(final_rows),
                "net_reduction": len(target_rows) - len(final_rows),
            },
        }

    def _apply_partition_plan(self, *, run_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        trade_date: date = plan["trade_date"]
        freq: int = plan["freq"]
        target_partition = self._partition(freq=freq, trade_date=trade_date)
        if int(plan["to_insert"]) == 0:
            return {
                "trade_date": trade_date.isoformat(),
                "freq": freq,
                "written": False,
                "inserted_rows": 0,
                "rows_before": plan["rows_before"],
                "rows_after": plan["rows_after"],
                "partition": str(target_partition),
            }

        tmp_partition = (
            self.lake_root
            / "_tmp"
            / run_id
            / "research"
            / "stk_mins_by_date_clean"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        )
        tmp_file = tmp_partition / "part-00000.parquet"
        backup_root = (
            self.lake_root
            / "_tmp"
            / run_id
            / "_backup"
            / "research"
            / "stk_mins_by_date_clean"
            / f"freq={freq}"
        )
        written = write_rows_to_parquet(plan["final_rows_payload"], tmp_file)
        validated = read_parquet_row_count(tmp_file)
        expected = int(plan["rows_after"])
        if written != validated or written != expected:
            raise RuntimeError(
                "09:30 专项写入校验失败："
                f"trade_date={trade_date.isoformat()} freq={freq} "
                f"expected={expected} written={written} validated={validated}"
            )
        replace_directory_atomically(tmp_dir=tmp_partition, final_dir=target_partition, backup_root=backup_root)
        return {
            "trade_date": trade_date.isoformat(),
            "freq": freq,
            "written": True,
            "inserted_rows": int(plan["to_insert"]),
            "rows_before": plan["rows_before"],
            "rows_after": plan["rows_after"],
            "partition": str(target_partition),
        }

    def _partition(self, *, freq: int, trade_date: date) -> Path:
        return (
            self.lake_root
            / "research"
            / "stk_mins_by_date_clean"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        )

    def _assert_schema(self, frame: Any, *, partition: str) -> None:
        columns = [str(item) for item in list(frame.columns)]
        if columns != list(TARGET_SCHEMA):
            raise RuntimeError(
                f"分区 schema 不符合当前错误 clean 10 列口径：partition={partition} "
                f"expected={','.join(TARGET_SCHEMA)} actual={','.join(columns)}"
            )

    def _assert_unique_key(self, *, rows: list[dict[str, Any]], partition: str) -> None:
        keys = [
            (
                str(row.get("ts_code") or ""),
                int(row.get("freq") or 0),
                _parse_trade_time(row.get("trade_time")),
            )
            for row in rows
        ]
        if len(set(keys)) != len(keys):
            raise RuntimeError(
                f"分区唯一键校验失败：partition={partition} 出现重复 (ts_code,freq,trade_time)。"
            )

    def _assert_output_schema(self, *, rows: list[dict[str, Any]], partition: str) -> None:
        if not rows:
            raise RuntimeError(f"分区写入前校验失败：partition={partition} 没有可写入行。")
        example_keys = tuple(rows[0].keys())
        if example_keys != TARGET_SCHEMA:
            raise RuntimeError(
                f"分区写入前 schema 校验失败：partition={partition} "
                f"expected={TARGET_SCHEMA} actual={example_keys}"
            )


def _read_partition_frame(partition_dir: Path) -> Any:
    if not partition_dir.exists():
        raise RuntimeError(f"分区不存在：{partition_dir}")
    files = sorted(partition_dir.glob("*.parquet"))
    if not files:
        raise RuntimeError(f"分区无 Parquet 文件：{partition_dir}")
    pd = _require_pandas()
    frames = [pd.read_parquet(path, engine="pyarrow") for path in files]
    return pd.concat(frames, ignore_index=True)


def _rows_from_frame(frame: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in frame.to_dict(orient="records")]


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return _normalize_output_row(
        {
            "ts_code": str(row.get("ts_code") or "").strip(),
            "freq": int(row.get("freq") or 0),
            "trade_time": _parse_trade_time(row.get("trade_time")),
            "open": float(row.get("open") or 0.0),
            "close": float(row.get("close") or 0.0),
            "high": float(row.get("high") or 0.0),
            "low": float(row.get("low") or 0.0),
            "vol": int(row.get("vol") or 0),
            "amount": float(row.get("amount") or 0.0),
            "trade_date": _parse_date(row.get("trade_date")),
        }
    )


def _normalize_output_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts_code": str(row["ts_code"]),
        "freq": int(row["freq"]),
        "trade_time": _parse_trade_time(row["trade_time"]),
        "open": float(row["open"]),
        "close": float(row["close"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "vol": int(row["vol"]),
        "amount": float(row["amount"]),
        "trade_date": _parse_date(row["trade_date"]),
    }


def _parse_trade_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if value is None:
        raise ValueError("trade_time 不能为空")
    text = str(value).strip()
    if not text:
        raise ValueError("trade_time 不能为空字符串")
    return datetime.fromisoformat(text)


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value is None:
        raise ValueError("trade_date 不能为空")
    text = str(value).strip()
    if not text:
        raise ValueError("trade_date 不能为空字符串")
    return date.fromisoformat(text)


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))


def _preview(values: list[str], *, limit: int = 10) -> str:
    if not values:
        return "[]"
    body = ", ".join(values[:limit])
    suffix = "" if len(values) <= limit else f", ... (+{len(values) - limit})"
    return f"[{body}{suffix}]"


def _run_id(label: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{label}"


def _require_pandas():  # type: ignore[no-untyped-def]
    try:
        import pandas as pd
        import pyarrow  # noqa: F401
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "缺少 Parquet 依赖。请先安装：lake_console/.venv/bin/pip install -r lake_console/backend/requirements.txt"
        ) from exc
    return pd
