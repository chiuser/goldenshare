from __future__ import annotations

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


TARGET_START_DATE = date(2022, 7, 15)
TARGET_END_DATE = date(2022, 12, 30)
SOURCE_FREQ = 15
TARGET_FREQ = 30
SOURCE_EXPECTED_ROWS_PER_CODE = 17
TARGET_EXPECTED_ROWS_PER_CODE = 9
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
LEDGER_PATH = Path("manifest") / "stk_mins_quality" / "clean_completeness_issue_ledger.parquet"
_MORNING_START = time(9, 30)
_MORNING_END = time(11, 30)
_AFTERNOON_START = time(13, 15)
_AFTERNOON_END = time(15, 0)


class StkMinsCurrentClean2022BjFreq30RepairService:
    """Repair only 2022 BJ freq30 missing bars (bar_count=6) in current wrong clean dataset."""

    def __init__(self, *, lake_root: Path, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or (lambda message: print(message, flush=True))

    def repair(self, *, dry_run: bool, apply: bool) -> dict[str, Any]:
        if dry_run == apply:
            raise ValueError("必须且只能指定 --dry-run 或 --apply。")

        started_at = datetime.now(timezone.utc)
        started = time_module.monotonic()
        affected_codes_by_date = self._load_affected_codes_from_ledger()
        if not affected_codes_by_date:
            raise RuntimeError("账本筛选后没有命中 2022 北交所 30min bar_count=6 问题。")

        dry_run_day_stats: list[dict[str, Any]] = []
        apply_day_stats: list[dict[str, Any]] = []
        total_affected_codes = 0
        total_old_rows = 0
        total_rebuilt_rows = 0
        total_before_rows = 0
        total_after_rows = 0
        source_failures = 0
        source_failure_samples: list[str] = []

        run_id = _run_id("repair-current-clean-2022-bj-freq30") if apply else None
        if apply:
            LakeRootService(self.lake_root).require_ready_for_write()
            self.progress(
                "[repair_current_clean_2022_bj_freq30] start "
                f"run_id={run_id} date_range={TARGET_START_DATE.isoformat()}~{TARGET_END_DATE.isoformat()}"
            )

        for index, trade_date in enumerate(sorted(affected_codes_by_date), start=1):
            codes = affected_codes_by_date[trade_date]
            try:
                plan = self._build_day_plan(trade_date=trade_date, affected_codes=codes)
            except Exception as exc:  # noqa: BLE001
                source_failures += 1
                if len(source_failure_samples) < 10:
                    source_failure_samples.append(f"{trade_date.isoformat()}: {exc}")
                raise RuntimeError(
                    f"专项门禁失败：trade_date={trade_date.isoformat()} error={exc}"
                ) from exc

            dry_run_day_stats.append(plan["dry_run"])
            total_affected_codes += plan["affected_codes"]
            total_old_rows += plan["old_affected_rows"]
            total_rebuilt_rows += plan["rebuilt_rows"]
            total_before_rows += plan["target_rows_before"]
            total_after_rows += plan["target_rows_after"]

            if apply and run_id:
                result = self._apply_day_plan(run_id=run_id, plan=plan)
                apply_day_stats.append(result)
                self.progress(
                    f"[repair_current_clean_2022_bj_freq30] day={index}/{len(affected_codes_by_date)} "
                    f"trade_date={trade_date.isoformat()} affected_codes={plan['affected_codes']} "
                    f"old_rows={plan['old_affected_rows']} rebuilt_rows={plan['rebuilt_rows']} "
                    f"final_rows={plan['target_rows_after']}"
                )

        if run_id:
            TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)

        elapsed = time_module.monotonic() - started
        summary = {
            "operation": "repair_current_clean_2022_bj_freq30",
            "mode": "apply" if apply else "dry_run",
            "dataset_layer": "research/stk_mins_by_date_clean",
            "schema_mode": "current_wrong_clean_10_columns",
            "date_range": {
                "start": TARGET_START_DATE.isoformat(),
                "end": TARGET_END_DATE.isoformat(),
            },
            "source_freq": SOURCE_FREQ,
            "target_freq": TARGET_FREQ,
            "affected_trade_dates": len(affected_codes_by_date),
            "affected_codes_total": total_affected_codes,
            "old_affected_rows_total": total_old_rows,
            "rebuilt_rows_total": total_rebuilt_rows,
            "target_rows_before_total": total_before_rows,
            "target_rows_after_total": total_after_rows,
            "net_reduction_total": total_before_rows - total_after_rows,
            "source_checks": {
                "expected_source_rows_per_code": SOURCE_EXPECTED_ROWS_PER_CODE,
                "expected_target_rows_per_code": TARGET_EXPECTED_ROWS_PER_CODE,
                "source_failures": source_failures,
                "source_failure_samples": source_failure_samples,
            },
            "dry_run_day_stats": dry_run_day_stats,
            "apply_day_stats": apply_day_stats if apply else None,
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "write_intent": apply,
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        return summary

    def _load_affected_codes_from_ledger(self) -> dict[date, list[str]]:
        ledger_file = self.lake_root / LEDGER_PATH
        if not ledger_file.exists():
            raise RuntimeError(f"缺少问题账本：{ledger_file}")

        rows = _read_parquet_rows(ledger_file)
        grouped: dict[date, set[str]] = defaultdict(set)
        for row in rows:
            trade_date = _parse_date(row.get("trade_date"))
            if trade_date < TARGET_START_DATE or trade_date > TARGET_END_DATE:
                continue
            if _parse_int(row.get("freq")) != TARGET_FREQ:
                continue
            if str(row.get("expected_value") or "") != "bar_count=9":
                continue
            if str(row.get("actual_value") or "") != "bar_count=6":
                continue
            issue_type = str(row.get("issue_type") or "")
            if issue_type and issue_type != "missing_intraday_bar":
                continue
            ts_code = str(row.get("latest_ts_code") or "").strip()
            if not ts_code or not ts_code.endswith(".BJ"):
                continue
            grouped[trade_date].add(ts_code)
        return {trade_date: sorted(codes) for trade_date, codes in grouped.items() if codes}

    def _build_day_plan(self, *, trade_date: date, affected_codes: list[str]) -> dict[str, Any]:
        source_partition = self._partition(freq=SOURCE_FREQ, trade_date=trade_date)
        target_partition = self._partition(freq=TARGET_FREQ, trade_date=trade_date)

        source_frame = _read_partition_frame(source_partition)
        target_frame = _read_partition_frame(target_partition)
        self._assert_schema(source_frame, partition=str(source_partition))
        self._assert_schema(target_frame, partition=str(target_partition))

        source_rows = [_normalize_row(row) for row in _rows_from_frame(source_frame)]
        target_rows = [_normalize_row(row) for row in _rows_from_frame(target_frame)]
        source_by_code = self._group_source_by_code(source_rows=source_rows, affected_codes=affected_codes)

        affected_set = set(affected_codes)
        old_affected_rows = [row for row in target_rows if str(row.get("ts_code") or "") in affected_set]
        unaffected_rows = [row for row in target_rows if str(row.get("ts_code") or "") not in affected_set]

        rebuilt_rows: list[dict[str, Any]] = []
        for ts_code in affected_codes:
            rebuilt = _aggregate_30min_from_15min(
                ts_code=ts_code,
                source_rows=source_by_code.get(ts_code, []),
                trade_date=trade_date,
            )
            rebuilt_rows.extend(rebuilt)

        final_rows = [_normalize_output_row(row) for row in unaffected_rows + rebuilt_rows]
        self._assert_unique_key(rows=final_rows, trade_date=trade_date)
        self._assert_output_schema(rows=final_rows, trade_date=trade_date)

        return {
            "trade_date": trade_date,
            "target_partition": str(target_partition),
            "affected_codes": len(affected_codes),
            "target_rows_before": len(target_rows),
            "old_affected_rows": len(old_affected_rows),
            "rebuilt_rows": len(rebuilt_rows),
            "target_rows_after": len(final_rows),
            "final_rows_payload": final_rows,
            "dry_run": {
                "trade_date": trade_date.isoformat(),
                "affected_codes": len(affected_codes),
                "target_rows_before": len(target_rows),
                "old_affected_rows": len(old_affected_rows),
                "rebuilt_rows": len(rebuilt_rows),
                "target_rows_after": len(final_rows),
                "net_reduction": len(target_rows) - len(final_rows),
                "partition": str(target_partition),
            },
        }

    def _apply_day_plan(self, *, run_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        trade_date: date = plan["trade_date"]
        target_partition = self._partition(freq=TARGET_FREQ, trade_date=trade_date)
        tmp_partition = (
            self.lake_root
            / "_tmp"
            / run_id
            / "research"
            / "stk_mins_by_date_clean"
            / f"freq={TARGET_FREQ}"
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
            / f"freq={TARGET_FREQ}"
        )
        written = write_rows_to_parquet(plan["final_rows_payload"], tmp_file)
        validated = read_parquet_row_count(tmp_file)
        expected = int(plan["target_rows_after"])
        if written != validated or written != expected:
            raise RuntimeError(
                "专项写入校验失败："
                f"trade_date={trade_date.isoformat()} expected={expected} written={written} validated={validated}"
            )
        replace_directory_atomically(tmp_dir=tmp_partition, final_dir=target_partition, backup_root=backup_root)
        return {
            "trade_date": trade_date.isoformat(),
            "affected_codes": plan["affected_codes"],
            "target_rows_before": plan["target_rows_before"],
            "old_affected_rows": plan["old_affected_rows"],
            "rebuilt_rows": plan["rebuilt_rows"],
            "target_rows_after": plan["target_rows_after"],
            "partition": str(target_partition),
        }

    def _group_source_by_code(
        self,
        *,
        source_rows: list[dict[str, Any]],
        affected_codes: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        affected_set = set(affected_codes)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in source_rows:
            ts_code = str(row.get("ts_code") or "")
            if ts_code in affected_set:
                grouped[ts_code].append(row)
        return grouped

    def _assert_schema(self, frame: Any, *, partition: str) -> None:
        columns = [str(item) for item in list(frame.columns)]
        if columns != list(TARGET_SCHEMA):
            raise RuntimeError(
                f"分区 schema 不符合当前错误 clean 10 列口径：partition={partition} "
                f"expected={','.join(TARGET_SCHEMA)} actual={','.join(columns)}"
            )

    def _assert_unique_key(self, *, rows: list[dict[str, Any]], trade_date: date) -> None:
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
                f"分区写入前唯一键校验失败：trade_date={trade_date.isoformat()} 出现重复 (ts_code,freq,trade_time)。"
            )

    def _assert_output_schema(self, *, rows: list[dict[str, Any]], trade_date: date) -> None:
        if not rows:
            raise RuntimeError(f"分区写入前校验失败：trade_date={trade_date.isoformat()} 没有可写入行。")
        example_keys = tuple(rows[0].keys())
        if example_keys != TARGET_SCHEMA:
            raise RuntimeError(
                f"分区写入前 schema 校验失败：trade_date={trade_date.isoformat()} "
                f"expected={TARGET_SCHEMA} actual={example_keys}"
            )

    def _partition(self, *, freq: int, trade_date: date) -> Path:
        return (
            self.lake_root
            / "research"
            / "stk_mins_by_date_clean"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        )


def _aggregate_30min_from_15min(
    *,
    ts_code: str,
    source_rows: list[dict[str, Any]],
    trade_date: date,
) -> list[dict[str, Any]]:
    if not source_rows:
        raise RuntimeError(f"15min 源数据缺失：ts_code={ts_code} trade_date={trade_date.isoformat()}")
    ordered = sorted((_normalize_row(row) for row in source_rows), key=lambda row: _parse_trade_time(row.get("trade_time")))
    regular_rows = _extract_regular_15min_rows(ts_code=ts_code, trade_date=trade_date, rows=ordered)
    _assert_source_15min_structure(ts_code=ts_code, trade_date=trade_date, rows=regular_rows)

    rows: list[dict[str, Any]] = []
    rows.append(_aggregate_chunk(ts_code=ts_code, trade_date=trade_date, chunk=[regular_rows[0]]))
    for offset in range(1, len(regular_rows), 2):
        chunk = regular_rows[offset : offset + 2]
        rows.append(_aggregate_chunk(ts_code=ts_code, trade_date=trade_date, chunk=chunk))

    if len(rows) != TARGET_EXPECTED_ROWS_PER_CODE:
        raise RuntimeError(
            f"30min 重建行数异常：ts_code={ts_code} trade_date={trade_date.isoformat()} "
            f"expected={TARGET_EXPECTED_ROWS_PER_CODE} actual={len(rows)}"
        )
    return rows


def _assert_source_15min_structure(*, ts_code: str, trade_date: date, rows: list[dict[str, Any]]) -> None:
    if len(rows) != SOURCE_EXPECTED_ROWS_PER_CODE:
        raise RuntimeError(
            f"15min 源行数异常：ts_code={ts_code} trade_date={trade_date.isoformat()} "
            f"expected={SOURCE_EXPECTED_ROWS_PER_CODE} actual={len(rows)}"
        )

    expected_times = [
        "09:30:00",
        "09:45:00",
        "10:00:00",
        "10:15:00",
        "10:30:00",
        "10:45:00",
        "11:00:00",
        "11:15:00",
        "11:30:00",
        "13:15:00",
        "13:30:00",
        "13:45:00",
        "14:00:00",
        "14:15:00",
        "14:30:00",
        "14:45:00",
        "15:00:00",
    ]
    actual_times = [row["trade_time"].strftime("%H:%M:%S") for row in rows]
    if actual_times != expected_times:
        raise RuntimeError(
            f"15min 时间结构异常：ts_code={ts_code} trade_date={trade_date.isoformat()} "
            f"actual={actual_times}"
        )

    keys = [(row["ts_code"], row["freq"], row["trade_time"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise RuntimeError(
            f"15min 源存在重复 key：ts_code={ts_code} trade_date={trade_date.isoformat()}"
        )


def _extract_regular_15min_rows(*, ts_code: str, trade_date: date, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regular: list[dict[str, Any]] = []
    for row in rows:
        value = _parse_trade_time(row.get("trade_time")).time()
        if (_MORNING_START <= value <= _MORNING_END) or (_AFTERNOON_START <= value <= _AFTERNOON_END):
            regular.append(row)
    if len(regular) < SOURCE_EXPECTED_ROWS_PER_CODE:
        raise RuntimeError(
            f"15min 常规时段不足：ts_code={ts_code} trade_date={trade_date.isoformat()} actual={len(regular)}"
        )
    return regular


def _aggregate_chunk(*, ts_code: str, trade_date: date, chunk: list[dict[str, Any]]) -> dict[str, Any]:
    if not chunk:
        raise RuntimeError(f"聚合 chunk 为空：ts_code={ts_code} trade_date={trade_date.isoformat()}")
    open_value = float(chunk[0]["open"])
    close_value = float(chunk[-1]["close"])
    high_value = max(float(row["high"]) for row in chunk)
    low_value = min(float(row["low"]) for row in chunk)
    vol_value = sum(int(row["vol"]) for row in chunk)
    amount_value = sum(float(row["amount"]) for row in chunk)
    return _normalize_output_row(
        {
            "ts_code": ts_code,
            "freq": TARGET_FREQ,
            "trade_time": _parse_trade_time(chunk[-1]["trade_time"]),
            "open": open_value,
            "close": close_value,
            "high": high_value,
            "low": low_value,
            "vol": vol_value,
            "amount": amount_value,
            "trade_date": trade_date,
        }
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


def _read_parquet_rows(parquet_file: Path) -> list[dict[str, Any]]:
    if not parquet_file.exists():
        return []
    pd = _require_pandas()
    frame = pd.read_parquet(parquet_file, engine="pyarrow")
    return [dict(row) for row in frame.to_dict(orient="records")]


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
