from __future__ import annotations

import math
import shutil
import time as time_module
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


TARGET_TRADE_DATE = date(2024, 10, 30)
TARGET_FREQS: tuple[int, ...] = (5, 15, 30, 60)
SOURCE_FREQ = 1
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
    "exchange",
    "vwap",
)
EXPECTED_TARGET_ROWS_PER_CODE = {5: 49, 15: 17, 30: 9, 60: 5}
EXPECTED_SOURCE_TOTAL_ROWS_PER_CODE = 271
EXPECTED_SOURCE_REGULAR_ROWS_PER_CODE = 241
LEDGER_PATH = Path("manifest") / "stk_mins_quality" / "clean_next_completeness_issue_ledger.parquet"
CLEAN_NEXT_ROOT = Path("research") / "stk_mins_by_date_clean_next"

_MORNING_START = time(9, 30)
_MORNING_END = time(11, 30)
_AFTERNOON_START = time(13, 1)
_AFTERNOON_END = time(15, 0)


class StkMinsCleanNext20241030MultifreqRepairService:
    """Repair only the approved 2024-10-30 multifreq issue in formal clean_next."""

    def __init__(self, *, lake_root: Path, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or (lambda message: print(message, flush=True))

    def repair(self, *, dry_run: bool, apply: bool) -> dict[str, Any]:
        if dry_run == apply:
            raise ValueError("必须且只能指定 --dry-run 或 --apply。")

        started_at = datetime.now(timezone.utc)
        started = time_module.monotonic()

        affected_codes_by_freq = self._load_affected_codes_from_ledger()
        affected_codes_union = sorted({code for codes in affected_codes_by_freq.values() for code in codes})
        if not affected_codes_union:
            raise RuntimeError("账本筛选后没有受影响股票，不能执行 clean_next 专项修复。")

        source_partition = self._clean_next_partition(freq=SOURCE_FREQ)
        source_frame = _read_partition_frame(source_partition)
        self._assert_schema(source_frame, partition=str(source_partition))
        source_rows = _rows_from_frame(source_frame)

        source_rows_by_code = self._source_rows_by_code(
            source_rows=source_rows,
            affected_codes=affected_codes_union,
        )
        source_checks = self._validate_source_rows(
            source_rows_by_code=source_rows_by_code,
            affected_codes=affected_codes_union,
        )

        dry_run_freq_stats: list[dict[str, Any]] = []
        apply_freq_stats: list[dict[str, Any]] = []
        per_freq_payload: dict[int, dict[str, Any]] = {}
        for freq in TARGET_FREQS:
            payload = self._plan_single_freq(
                freq=freq,
                affected_codes=affected_codes_by_freq[freq],
                source_rows_by_code=source_rows_by_code,
            )
            per_freq_payload[freq] = payload
            dry_run_freq_stats.append(payload["dry_run"])

        run_id: str | None = None
        if apply:
            LakeRootService(self.lake_root).require_ready_for_write()
            run_id = _run_id("repair-clean-next-20241030-multifreq")
            self.progress(
                f"[repair_clean_next_20241030_multifreq] start run_id={run_id} "
                f"trade_date={TARGET_TRADE_DATE.isoformat()}"
            )
            for freq in TARGET_FREQS:
                payload = per_freq_payload[freq]
                apply_stats = self._apply_single_freq(run_id=run_id, freq=freq, payload=payload)
                apply_freq_stats.append(apply_stats)
                self.progress(
                    f"[repair_clean_next_20241030_multifreq] freq={freq} replaced "
                    f"old_affected_rows={apply_stats['old_affected_rows']} "
                    f"new_rows={apply_stats['rebuilt_rows']} final_rows={apply_stats['final_rows']}"
                )
            TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)

        elapsed = time_module.monotonic() - started
        return {
            "operation": "repair_stk_mins_clean_next_20241030_multifreq",
            "mode": "apply" if apply else "dry_run",
            "dataset_layer": str(CLEAN_NEXT_ROOT),
            "source_path": str(CLEAN_NEXT_ROOT),
            "schema_mode": "formal_clean_next_11_columns",
            "trade_date": TARGET_TRADE_DATE.isoformat(),
            "source_freq": SOURCE_FREQ,
            "target_freqs": list(TARGET_FREQS),
            "affected_codes_by_freq": {str(freq): len(affected_codes_by_freq[freq]) for freq in TARGET_FREQS},
            "affected_codes_union": len(affected_codes_union),
            "source_checks": source_checks,
            "dry_run_freq_stats": dry_run_freq_stats,
            "apply_freq_stats": apply_freq_stats if apply else None,
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "write_intent": apply,
        }

    def _load_affected_codes_from_ledger(self) -> dict[int, list[str]]:
        ledger_file = self.lake_root / LEDGER_PATH
        if not ledger_file.exists():
            raise RuntimeError(f"缺少 clean_next 完备性问题账本：{ledger_file}")

        rows = _read_parquet_rows(ledger_file)
        codes_by_freq: dict[int, set[str]] = {freq: set() for freq in TARGET_FREQS}
        for row in rows:
            record_trade_date = _parse_date(row.get("trade_date"))
            if record_trade_date != TARGET_TRADE_DATE:
                continue
            freq = _parse_int(row.get("freq"))
            if freq not in TARGET_FREQS:
                continue
            issue_type = str(row.get("issue_type") or "").strip()
            if issue_type and issue_type != "extra_intraday_bar":
                continue
            if str(row.get("actual_value") or "").strip() != "bar_count=271":
                continue
            ts_code = str(row.get("latest_ts_code") or "").strip()
            if not ts_code or ts_code == "__partition__":
                continue
            codes_by_freq[freq].add(ts_code)

        missing_freqs = [str(freq) for freq in TARGET_FREQS if not codes_by_freq[freq]]
        if missing_freqs:
            raise RuntimeError(f"账本筛选后缺少目标频率股票清单：freq={','.join(missing_freqs)}")
        return {freq: sorted(codes) for freq, codes in codes_by_freq.items()}

    def _source_rows_by_code(
        self,
        *,
        source_rows: list[dict[str, Any]],
        affected_codes: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        affected_set = set(affected_codes)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in source_rows:
            ts_code = str(row.get("ts_code") or "").strip()
            if ts_code in affected_set:
                grouped[ts_code].append(_normalize_row(row))
        return grouped

    def _validate_source_rows(
        self,
        *,
        source_rows_by_code: dict[str, list[dict[str, Any]]],
        affected_codes: list[str],
    ) -> dict[str, Any]:
        missing_codes: list[str] = []
        invalid_total_codes: list[str] = []
        invalid_regular_codes: list[str] = []
        duplicate_codes: list[str] = []

        for ts_code in affected_codes:
            rows = source_rows_by_code.get(ts_code, [])
            if not rows:
                missing_codes.append(ts_code)
                continue
            if len(rows) != EXPECTED_SOURCE_TOTAL_ROWS_PER_CODE:
                invalid_total_codes.append(ts_code)
            regular_rows = [row for row in rows if _is_regular_session(_parse_trade_time(row["trade_time"]).time())]
            if len(regular_rows) != EXPECTED_SOURCE_REGULAR_ROWS_PER_CODE:
                invalid_regular_codes.append(ts_code)
            keys = [(str(row["ts_code"]), int(row["freq"]), _parse_trade_time(row["trade_time"])) for row in rows]
            if len(set(keys)) != len(keys):
                duplicate_codes.append(ts_code)

        if missing_codes or invalid_total_codes or invalid_regular_codes or duplicate_codes:
            raise RuntimeError(
                "clean_next 1min 源数据门禁失败："
                f"missing={_preview(missing_codes)} "
                f"invalid_total={_preview(invalid_total_codes)} "
                f"invalid_regular={_preview(invalid_regular_codes)} "
                f"duplicates={_preview(duplicate_codes)}"
            )

        return {
            "expected_total_rows_per_code": EXPECTED_SOURCE_TOTAL_ROWS_PER_CODE,
            "expected_regular_rows_per_code": EXPECTED_SOURCE_REGULAR_ROWS_PER_CODE,
            "validated_codes": len(affected_codes),
            "missing_codes": 0,
            "invalid_total_codes": 0,
            "invalid_regular_codes": 0,
            "duplicate_codes": 0,
            "schema": list(TARGET_SCHEMA),
        }

    def _plan_single_freq(
        self,
        *,
        freq: int,
        affected_codes: list[str],
        source_rows_by_code: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        target_partition = self._clean_next_partition(freq=freq)
        target_frame = _read_partition_frame(target_partition)
        self._assert_schema(target_frame, partition=str(target_partition))
        target_rows = [_normalize_row(row) for row in _rows_from_frame(target_frame)]

        affected_set = set(affected_codes)
        old_affected_rows = [row for row in target_rows if str(row.get("ts_code") or "").strip() in affected_set]
        unaffected_rows = [row for row in target_rows if str(row.get("ts_code") or "").strip() not in affected_set]

        rebuilt_rows: list[dict[str, Any]] = []
        per_code_rebuilt_counts: dict[str, int] = {}
        vwap_stats = _empty_vwap_stats()
        for ts_code in affected_codes:
            built, code_vwap_stats = _aggregate_from_1min(
                ts_code=ts_code,
                source_rows=source_rows_by_code[ts_code],
                target_freq=freq,
            )
            per_code_rebuilt_counts[ts_code] = len(built)
            rebuilt_rows.extend(built)
            _merge_vwap_stats(vwap_stats, code_vwap_stats)

        bad_counts = [code for code, value in per_code_rebuilt_counts.items() if value != EXPECTED_TARGET_ROWS_PER_CODE[freq]]
        if bad_counts:
            raise RuntimeError(
                f"目标频率重建行数不符合预期：freq={freq} expected={EXPECTED_TARGET_ROWS_PER_CODE[freq]} "
                f"bad_codes={_preview(bad_counts)}"
            )
        if vwap_stats["missing_vwap_rows"] > 0:
            raise RuntimeError(f"vwap 生成门禁失败：freq={freq} missing_vwap_rows={vwap_stats['missing_vwap_rows']}")

        final_rows = [_normalize_output_row(row) for row in unaffected_rows + rebuilt_rows]
        self._assert_unique_key(rows=final_rows, freq=freq)
        self._assert_output_schema(rows=final_rows, freq=freq)

        return {
            "freq": freq,
            "target_partition": str(target_partition),
            "target_rows_before": len(target_rows),
            "old_affected_rows": len(old_affected_rows),
            "unaffected_rows": len(unaffected_rows),
            "rebuilt_rows": len(rebuilt_rows),
            "final_rows": len(final_rows),
            "affected_codes": affected_codes,
            "final_rows_payload": final_rows,
            "vwap_stats": dict(vwap_stats),
            "dry_run": {
                "freq": freq,
                "affected_codes": len(affected_codes),
                "old_affected_rows": len(old_affected_rows),
                "rebuilt_rows": len(rebuilt_rows),
                "target_rows_before": len(target_rows),
                "target_rows_after": len(final_rows),
                "net_reduction": len(target_rows) - len(final_rows),
                "expected_rows_per_code": EXPECTED_TARGET_ROWS_PER_CODE[freq],
                "partition": str(target_partition),
                "vwap_stats": dict(vwap_stats),
            },
        }

    def _apply_single_freq(self, *, run_id: str, freq: int, payload: dict[str, Any]) -> dict[str, Any]:
        target_partition = self._clean_next_partition(freq=freq)
        tmp_partition = (
            self.lake_root
            / "_tmp"
            / run_id
            / CLEAN_NEXT_ROOT
            / f"freq={freq}"
            / f"trade_date={TARGET_TRADE_DATE.isoformat()}"
        )
        backup_root = self.lake_root / "_tmp" / run_id / "_backup" / CLEAN_NEXT_ROOT / f"freq={freq}"
        tmp_file = tmp_partition / "part-00000.parquet"

        written = write_rows_to_parquet(payload["final_rows_payload"], tmp_file)
        validated = read_parquet_row_count(tmp_file)
        if written != validated or written != payload["final_rows"]:
            raise RuntimeError(
                f"专项修复写入校验失败：freq={freq} expected={payload['final_rows']} "
                f"written={written} validated={validated}"
            )

        _replace_directory_atomically_keep_backup(tmp_dir=tmp_partition, final_dir=target_partition, backup_root=backup_root)
        self._post_apply_check(freq=freq, affected_codes=payload["affected_codes"])
        return {
            "freq": freq,
            "old_affected_rows": payload["old_affected_rows"],
            "rebuilt_rows": payload["rebuilt_rows"],
            "target_rows_before": payload["target_rows_before"],
            "final_rows": payload["final_rows"],
            "partition": str(target_partition),
            "vwap_stats": dict(payload["vwap_stats"]),
        }

    def _post_apply_check(self, *, freq: int, affected_codes: list[str]) -> None:
        frame = _read_partition_frame(self._clean_next_partition(freq=freq))
        self._assert_schema(frame, partition=str(self._clean_next_partition(freq=freq)))
        rows = [_normalize_row(row) for row in _rows_from_frame(frame)]
        affected_set = set(affected_codes)
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            code = str(row["ts_code"])
            if code in affected_set:
                counts[code] += 1
        bad_codes = [code for code in affected_codes if counts.get(code, 0) != EXPECTED_TARGET_ROWS_PER_CODE[freq]]
        if bad_codes:
            raise RuntimeError(
                f"apply 后分区直读校验失败：freq={freq} expected={EXPECTED_TARGET_ROWS_PER_CODE[freq]} "
                f"bad_codes={_preview(bad_codes)}"
            )
        self._assert_unique_key(rows=rows, freq=freq)

    def _assert_schema(self, frame: Any, *, partition: str) -> None:
        columns = [str(item) for item in list(frame.columns)]
        if columns != list(TARGET_SCHEMA):
            raise RuntimeError(
                f"分区 schema 不符合 clean_next 11 列口径：partition={partition} "
                f"expected={','.join(TARGET_SCHEMA)} actual={','.join(columns)}"
            )

    def _assert_unique_key(self, *, rows: list[dict[str, Any]], freq: int) -> None:
        keys = [
            (
                str(row["ts_code"]).strip(),
                int(row["freq"]),
                _parse_trade_time(row["trade_time"]),
            )
            for row in rows
        ]
        if len(set(keys)) != len(keys):
            raise RuntimeError(f"分区唯一键校验失败：freq={freq} 出现重复 (ts_code,freq,trade_time)。")

    def _assert_output_schema(self, *, rows: list[dict[str, Any]], freq: int) -> None:
        if not rows:
            raise RuntimeError(f"分区写入前校验失败：freq={freq} 没有可写入行。")
        example_keys = tuple(rows[0].keys())
        if example_keys != TARGET_SCHEMA:
            raise RuntimeError(
                f"分区写入前 schema 校验失败：freq={freq} expected={TARGET_SCHEMA} actual={example_keys}"
            )

    def _clean_next_partition(self, *, freq: int) -> Path:
        return self.lake_root / CLEAN_NEXT_ROOT / f"freq={freq}" / f"trade_date={TARGET_TRADE_DATE.isoformat()}"


def _aggregate_from_1min(
    *,
    ts_code: str,
    source_rows: list[dict[str, Any]],
    target_freq: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if target_freq not in EXPECTED_TARGET_ROWS_PER_CODE:
        raise ValueError(f"不支持的目标频率：{target_freq}")

    stats = _empty_vwap_stats()
    normalized_rows = sorted((_normalize_row(item) for item in source_rows), key=lambda row: _parse_trade_time(row["trade_time"]))
    regular_rows = [row for row in normalized_rows if _is_regular_session(_parse_trade_time(row["trade_time"]).time())]
    morning_rows = [row for row in regular_rows if _MORNING_START <= _parse_trade_time(row["trade_time"]).time() <= _MORNING_END]
    afternoon_rows = [
        row for row in regular_rows if _AFTERNOON_START <= _parse_trade_time(row["trade_time"]).time() <= _AFTERNOON_END
    ]

    if len(morning_rows) != 121 or len(afternoon_rows) != 120:
        raise RuntimeError(
            f"1min 常规时段结构异常：ts_code={ts_code} freq={target_freq} "
            f"morning={len(morning_rows)} afternoon={len(afternoon_rows)}"
        )
    if _parse_trade_time(morning_rows[0]["trade_time"]).time() != _MORNING_START:
        raise RuntimeError(
            f"1min 早盘首根异常：ts_code={ts_code} freq={target_freq} "
            f"first_time={_parse_trade_time(morning_rows[0]['trade_time']).time()}"
        )

    rows: list[dict[str, Any]] = []
    rows.append(_aggregate_chunk(ts_code=ts_code, target_freq=target_freq, chunk=[morning_rows[0]], stats=stats))
    rows.extend(_aggregate_fixed_chunks(ts_code=ts_code, target_freq=target_freq, rows=morning_rows[1:], stats=stats))
    rows.extend(_aggregate_fixed_chunks(ts_code=ts_code, target_freq=target_freq, rows=afternoon_rows, stats=stats))
    return rows, stats


def _aggregate_fixed_chunks(
    *,
    ts_code: str,
    target_freq: int,
    rows: list[dict[str, Any]],
    stats: dict[str, int],
) -> list[dict[str, Any]]:
    if len(rows) % target_freq != 0:
        raise RuntimeError(
            f"固定窗口聚合失败：ts_code={ts_code} freq={target_freq} rows={len(rows)} 不能被窗口整除"
        )
    result: list[dict[str, Any]] = []
    for offset in range(0, len(rows), target_freq):
        chunk = rows[offset : offset + target_freq]
        result.append(_aggregate_chunk(ts_code=ts_code, target_freq=target_freq, chunk=chunk, stats=stats))
    return result


def _aggregate_chunk(
    *,
    ts_code: str,
    target_freq: int,
    chunk: list[dict[str, Any]],
    stats: dict[str, int],
) -> dict[str, Any]:
    if not chunk:
        raise RuntimeError(f"聚合 chunk 为空：ts_code={ts_code} freq={target_freq}")

    exchanges = [_normalize_optional_text(row.get("exchange")) for row in chunk]
    non_empty_exchanges = sorted({value for value in exchanges if value is not None})
    if len(non_empty_exchanges) > 1:
        raise RuntimeError(
            f"exchange 聚合门禁失败：ts_code={ts_code} freq={target_freq} "
            f"trade_time={_parse_trade_time(chunk[-1]['trade_time']).isoformat()} exchanges={non_empty_exchanges}"
        )
    exchange_value = non_empty_exchanges[0] if non_empty_exchanges else None

    vol_value = sum(int(row["vol"]) for row in chunk)
    amount_value = sum(float(row["amount"]) for row in chunk)
    vwap_value = _resolve_vwap(chunk=chunk, vol_value=vol_value, amount_value=amount_value, stats=stats)

    return _normalize_output_row(
        {
            "ts_code": ts_code,
            "freq": target_freq,
            "trade_time": _parse_trade_time(chunk[-1]["trade_time"]),
            "open": float(chunk[0]["open"]),
            "close": float(chunk[-1]["close"]),
            "high": max(float(row["high"]) for row in chunk),
            "low": min(float(row["low"]) for row in chunk),
            "vol": vol_value,
            "amount": amount_value,
            "exchange": exchange_value,
            "vwap": vwap_value,
        }
    )


def _resolve_vwap(*, chunk: list[dict[str, Any]], vol_value: int, amount_value: float, stats: dict[str, int]) -> float:
    if len(chunk) == 1:
        source_vwap = _optional_float(chunk[0].get("vwap"))
        if source_vwap is None:
            stats["missing_vwap_rows"] += 1
            return math.nan
        stats["source_single_vwap_rows"] += 1
        return source_vwap

    if vol_value > 0:
        stats["amount_div_vol_rows"] += 1
        return float(amount_value) / float(vol_value)

    for row in reversed(chunk):
        source_vwap = _optional_float(row.get("vwap"))
        if source_vwap is not None:
            stats["last_source_vwap_fallback_rows"] += 1
            return source_vwap

    stats["missing_vwap_rows"] += 1
    return math.nan


def _read_partition_frame(partition_dir: Path) -> Any:
    if not partition_dir.exists():
        raise RuntimeError(f"分区不存在：{partition_dir}")
    files = sorted(partition_dir.glob("*.parquet"))
    if not files:
        raise RuntimeError(f"分区无 Parquet 文件：{partition_dir}")
    pd = _require_pandas()
    frames = [pd.read_parquet(path, engine="pyarrow") for path in files]
    return pd.concat(frames, ignore_index=True)


def _replace_directory_atomically_keep_backup(*, tmp_dir: Path, final_dir: Path, backup_root: Path) -> None:
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_root / final_dir.name
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    if final_dir.exists():
        final_dir.replace(backup_dir)
    try:
        tmp_dir.replace(final_dir)
    except Exception:
        if backup_dir.exists() and not final_dir.exists():
            backup_dir.replace(final_dir)
        raise


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
            "exchange": _normalize_optional_text(row.get("exchange")),
            "vwap": _optional_float(row.get("vwap")),
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
        "exchange": _normalize_optional_text(row.get("exchange")),
        "vwap": _required_float(row.get("vwap"), field_name="vwap"),
    }


def _is_regular_session(value: time) -> bool:
    return (_MORNING_START <= value <= _MORNING_END) or (_AFTERNOON_START <= value <= _AFTERNOON_END)


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
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))


def _optional_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    parsed = float(value)
    if math.isnan(parsed):
        return None
    return parsed


def _required_float(value: Any, *, field_name: str) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        raise ValueError(f"{field_name} 不能为空")
    return parsed


def _normalize_optional_text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(math.isnan(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _empty_vwap_stats() -> dict[str, int]:
    return {
        "source_single_vwap_rows": 0,
        "amount_div_vol_rows": 0,
        "last_source_vwap_fallback_rows": 0,
        "missing_vwap_rows": 0,
    }


def _merge_vwap_stats(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + int(value)


def _preview(values: list[str], *, limit: int = 8) -> str:
    if not values:
        return "-"
    if len(values) <= limit:
        return ",".join(values)
    return ",".join(values[:limit]) + f"...(+{len(values) - limit})"


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
