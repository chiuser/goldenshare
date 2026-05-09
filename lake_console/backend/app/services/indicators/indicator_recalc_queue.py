from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Mapping

from lake_console.backend.app.services.indicators.macd_spec import DEFAULT_MACD_PARAMS
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    read_parquet_rows,
    replace_file_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


QUEUE_REQUIRED_FIELDS = (
    "queue_id",
    "indicator_key",
    "params_key",
    "freq_scope",
    "freq_value",
    "security_scope",
    "ts_code",
    "invalid_from_time",
    "reason",
    "status",
    "created_at",
    "finished_at",
    "error_message",
)
QUEUE_STATUSES = frozenset({"pending", "running", "done", "failed"})
SOURCE_LAYERS = frozenset({"raw_tushare", "derived"})


class IndicatorRecalcQueueService:
    def __init__(self, *, lake_root: Path) -> None:
        self.lake_root = lake_root

    def source_event_file(self) -> Path:
        return self.lake_root / "manifest" / "source_partition_events" / "stk_mins.jsonl"

    def queue_file(self) -> Path:
        return self.lake_root / "manifest" / "indicator_recalc_queue" / "stk_mins_macd.parquet"

    def record_source_partition_replaced(
        self,
        *,
        layer: str,
        freq: int,
        trade_date: date,
        run_id: str,
        written_rows: int,
    ) -> dict[str, Any]:
        if layer not in SOURCE_LAYERS:
            raise ValueError(f"不支持的 source layer：{layer}")
        if freq <= 0:
            raise ValueError("freq 必须大于 0。")
        if written_rows < 0:
            raise ValueError("written_rows 不能小于 0。")

        LakeRootService(self.lake_root).require_ready_for_write()
        recorded_at = _now()
        event = {
            "event_id": _event_id(layer=layer, freq=freq, trade_date=trade_date, run_id=run_id, written_rows=written_rows),
            "dataset_key": "stk_mins",
            "layer": layer,
            "freq": int(freq),
            "trade_date": trade_date.isoformat(),
            "event_type": "partition_replaced",
            "run_id": run_id,
            "written_rows": int(written_rows),
            "recorded_at": recorded_at.isoformat(),
        }
        event_file = self.source_event_file()
        event_file.parent.mkdir(parents=True, exist_ok=True)
        with event_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

        queue_item = self.upsert_pending_from_source_event(event)
        return {
            "event": event,
            "queue_item": queue_item,
        }

    def upsert_pending_from_source_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        _validate_source_event(event)
        invalid_from_time = datetime.combine(_event_trade_date(event), time.min)
        now = _now()
        queue_id = _queue_id(
            indicator_key="macd",
            params_key=DEFAULT_MACD_PARAMS.params_key,
            freq_scope="single",
            freq_value=int(event["freq"]),
            security_scope="all",
            ts_code=None,
            invalid_from_time=invalid_from_time,
            reason="source_partition_replaced",
        )
        existing_rows = self.list_items(include_done=True)
        rows_by_id = {str(row["queue_id"]): dict(row) for row in existing_rows}
        existing = rows_by_id.get(queue_id)
        created_at = _parse_datetime(existing["created_at"]) if existing else now
        queue_item = {
            "queue_id": queue_id,
            "indicator_key": "macd",
            "params_key": DEFAULT_MACD_PARAMS.params_key,
            "freq_scope": "single",
            "freq_value": int(event["freq"]),
            "security_scope": "all",
            "ts_code": None,
            "invalid_from_time": invalid_from_time,
            "reason": "source_partition_replaced",
            "status": "pending",
            "created_at": created_at,
            "finished_at": None,
            "error_message": None,
        }
        rows_by_id[queue_id] = queue_item
        self._replace_queue_rows(list(rows_by_id.values()), run_id=f"indicator-recalc-queue-{queue_id[:12]}")
        return dict(queue_item)

    def list_items(self, *, indicator: str = "macd", include_done: bool = False) -> list[dict[str, Any]]:
        if indicator != "macd":
            raise ValueError(f"当前仅支持 indicator=macd：{indicator}")
        queue_file = self.queue_file()
        if not queue_file.exists():
            return []
        rows = [_normalize_queue_row(row) for row in read_parquet_rows(queue_file)]
        if not include_done:
            rows = [row for row in rows if row["status"] != "done"]
        return sorted(rows, key=lambda row: (str(row["status"]), _parse_datetime(row["invalid_from_time"]), int(row["freq_value"] or 0)))

    def mark_done(self, *, queue_id: str) -> dict[str, Any]:
        if not queue_id.strip():
            raise ValueError("queue_id 不能为空。")
        rows = self.list_items(include_done=True)
        if not rows:
            raise ValueError("indicator_recalc_queue 为空。")
        matched = False
        finished_at = _now()
        updated_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            if str(normalized["queue_id"]) == queue_id:
                normalized["status"] = "done"
                normalized["finished_at"] = finished_at
                normalized["error_message"] = None
                matched = True
            updated_rows.append(normalized)
        if not matched:
            raise ValueError(f"未找到 queue_id={queue_id}")
        self._replace_queue_rows(updated_rows, run_id=f"indicator-recalc-queue-done-{queue_id[:12]}")
        return {
            "operation": "mark_indicator_recalc_done",
            "queue_id": queue_id,
            "status": "done",
            "finished_at": finished_at.isoformat(),
        }

    def format_queue_items(self, items: list[Mapping[str, Any]]) -> str:
        if not items:
            return "没有待处理的 indicator_recalc_queue。"
        lines: list[str] = []
        for index, item in enumerate(items, start=1):
            invalid_from_time = _parse_datetime(item["invalid_from_time"])
            invalid_from_date = invalid_from_time.date().isoformat()
            freq_value = int(item["freq_value"])
            queue_id = str(item["queue_id"])
            scope_label = "all-market" if item["security_scope"] == "all" else str(item.get("ts_code") or "")
            lines.extend(
                [
                    f"[{index}] {item['indicator_key']} / {item['params_key']} / freq={freq_value} / {scope_label}",
                    f"queue_id: {queue_id}",
                    f"reason: {item['reason']}",
                    f"invalid_from: {invalid_from_time.isoformat(sep=' ')}",
                    f"status: {item['status']}",
                    "",
                    "suggested_command:",
                    _suggested_compute_command(item, start_date=invalid_from_date),
                    "",
                    "mark_done_command:",
                    f"lake-console mark-indicator-recalc-done --queue-id {queue_id}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()

    def _replace_queue_rows(self, rows: list[dict[str, Any]], *, run_id: str) -> None:
        if not rows:
            raise ValueError("indicator_recalc_queue 不能写入空表。")
        normalized = [_normalize_queue_row(row) for row in rows]
        tmp_file = self.lake_root / "_tmp" / run_id / "manifest" / "indicator_recalc_queue" / "stk_mins_macd.parquet"
        final_file = self.queue_file()
        written = write_rows_to_parquet(normalized, tmp_file)
        validated = read_parquet_row_count(tmp_file)
        if validated != written:
            raise RuntimeError(f"indicator_recalc_queue 校验失败：written={written} validated={validated}")
        replace_file_atomically(
            tmp_file=tmp_file,
            final_file=final_file,
            backup_root=self.lake_root / "_tmp" / run_id / "_backup",
        )
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)


def _suggested_compute_command(item: Mapping[str, Any], *, start_date: str) -> str:
    scope_args = "--all-market"
    if item["security_scope"] == "single":
        scope_args = f"--ts-code {item['ts_code']}"
    return "\n".join(
        [
            "lake-console compute-stk-mins-indicator \\",
            "  --indicator macd \\",
            "  --mode incremental \\",
            f"  {scope_args} \\",
            f"  --freq {int(item['freq_value'])} \\",
            f"  --start-date {start_date} \\",
            "  --end-date <请填源数据最新交易日>",
        ]
    )


def _normalize_queue_row(row: Mapping[str, Any]) -> dict[str, Any]:
    for field in QUEUE_REQUIRED_FIELDS:
        if field not in row:
            raise ValueError(f"indicator_recalc_queue 缺少字段：{field}")
    status = str(row["status"] or "").strip()
    if status not in QUEUE_STATUSES:
        raise ValueError(f"indicator_recalc_queue status 无效：{status}")
    freq_scope = str(row["freq_scope"] or "").strip()
    security_scope = str(row["security_scope"] or "").strip()
    if freq_scope not in {"all", "single"}:
        raise ValueError(f"indicator_recalc_queue freq_scope 无效：{freq_scope}")
    if security_scope not in {"all", "single"}:
        raise ValueError(f"indicator_recalc_queue security_scope 无效：{security_scope}")
    freq_value = None if _is_empty(row["freq_value"]) else int(row["freq_value"])
    ts_code = None if _is_empty(row["ts_code"]) else str(row["ts_code"]).strip()
    if freq_scope == "single" and freq_value is None:
        raise ValueError("indicator_recalc_queue freq_scope=single 时必须有 freq_value。")
    if security_scope == "single" and not ts_code:
        raise ValueError("indicator_recalc_queue security_scope=single 时必须有 ts_code。")
    return {
        "queue_id": str(row["queue_id"]).strip(),
        "indicator_key": str(row["indicator_key"]).strip(),
        "params_key": str(row["params_key"]).strip(),
        "freq_scope": freq_scope,
        "freq_value": freq_value,
        "security_scope": security_scope,
        "ts_code": ts_code,
        "invalid_from_time": _parse_datetime(row["invalid_from_time"]),
        "reason": str(row["reason"]).strip(),
        "status": status,
        "created_at": _parse_datetime(row["created_at"]),
        "finished_at": None if _is_empty(row["finished_at"]) else _parse_datetime(row["finished_at"]),
        "error_message": None if _is_empty(row["error_message"]) else str(row["error_message"]),
    }


def _validate_source_event(event: Mapping[str, Any]) -> None:
    if str(event.get("dataset_key") or "") != "stk_mins":
        raise ValueError(f"source partition event dataset_key 无效：{event.get('dataset_key')}")
    if str(event.get("event_type") or "") != "partition_replaced":
        raise ValueError(f"source partition event event_type 无效：{event.get('event_type')}")
    if str(event.get("layer") or "") not in SOURCE_LAYERS:
        raise ValueError(f"source partition event layer 无效：{event.get('layer')}")
    if int(event.get("freq") or 0) <= 0:
        raise ValueError(f"source partition event freq 无效：{event.get('freq')}")
    _event_trade_date(event)


def _event_trade_date(event: Mapping[str, Any]) -> date:
    value = event.get("trade_date")
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _event_id(*, layer: str, freq: int, trade_date: date, run_id: str, written_rows: int) -> str:
    raw_value = f"stk_mins|{layer}|{freq}|{trade_date.isoformat()}|{run_id}|{written_rows}"
    return "spe_" + hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:24]


def _queue_id(
    *,
    indicator_key: str,
    params_key: str,
    freq_scope: str,
    freq_value: int | None,
    security_scope: str,
    ts_code: str | None,
    invalid_from_time: datetime,
    reason: str,
) -> str:
    raw_value = "|".join(
        [
            indicator_key,
            params_key,
            freq_scope,
            str(freq_value) if freq_value is not None else "none",
            security_scope,
            ts_code or "none",
            invalid_from_time.isoformat(),
            reason,
        ]
    )
    return "irq_" + hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:24]


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().replace(tzinfo=None)
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError("timestamp 不能为空。")
    return datetime.fromisoformat(raw_value.replace("T", " ")).replace(tzinfo=None)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(value != value)
    except TypeError:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
