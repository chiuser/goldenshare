from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.tushare_stk_mins import TRADE_CAL_FIELDS
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    replace_file_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService
from lake_console.backend.app.services.tushare_client import TushareLakeClient


DEFAULT_EXCHANGE = "SSE"


class TushareTradeCalSyncService:
    def __init__(
        self,
        *,
        lake_root: Path,
        client: TushareLakeClient,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.lake_root = lake_root
        self.client = client
        self.progress = progress or print

    def sync(self, *, start_date: date, end_date: date, exchange: str = DEFAULT_EXCHANGE) -> dict[str, Any]:
        if end_date < start_date:
            raise ValueError("sync-trade-cal 的 end-date 不能早于 start-date。")

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("trade-cal")
        LakeRootService(self.lake_root).require_ready_for_write()
        self.progress(
            f"[trade_cal] start run_id={run_id} exchange={exchange} "
            f"start_date={start_date.isoformat()} end_date={end_date.isoformat()}"
        )

        rows = self.client.trade_cal(
            exchange=exchange,
            start_date=_format_tushare_date(start_date),
            end_date=_format_tushare_date(end_date),
            fields=TRADE_CAL_FIELDS,
        )
        output_rows = sorted((_normalize_trade_cal_row(row, fallback_exchange=exchange) for row in rows), key=lambda row: str(row["cal_date"]))
        if not output_rows:
            raise RuntimeError("trade_cal 未获取到任何有效记录，拒绝覆盖本地交易日历。")

        backup_root = self.lake_root / "_tmp" / run_id / "_backup"
        raw_tmp = self.lake_root / "_tmp" / run_id / "raw_tushare" / "trade_cal" / "current" / "part-000.parquet"
        raw_final = self.lake_root / "raw_tushare" / "trade_cal" / "current" / "part-000.parquet"
        calendar_tmp = self.lake_root / "_tmp" / run_id / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
        calendar_final = self.lake_root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"

        self.progress(f"[trade_cal] fetched={len(rows)} writing_raw rows={len(output_rows)} output={raw_tmp}")
        raw_written = _write_and_validate(rows=output_rows, tmp_file=raw_tmp)
        self.progress(f"[trade_cal] writing_calendar rows={len(output_rows)} output={calendar_tmp}")
        calendar_written = _write_and_validate(rows=output_rows, tmp_file=calendar_tmp)

        replace_file_atomically(tmp_file=raw_tmp, final_file=raw_final, backup_root=backup_root / "raw_trade_cal")
        replace_file_atomically(tmp_file=calendar_tmp, final_file=calendar_final, backup_root=backup_root / "trading_calendar")
        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "trade_cal",
            "api_name": "trade_cal",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "exchange": exchange,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "fetched_rows": len(rows),
            "written_rows": raw_written,
            "raw_output": str(raw_final),
            "calendar_output": str(calendar_final),
            "calendar_written_rows": calendar_written,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[trade_cal] done fetched={len(rows)} raw_written={raw_written} calendar_written={calendar_written} "
            f"raw_output={raw_final} calendar_output={calendar_final} elapsed={math.ceil(elapsed)}s"
        )
        return summary


def _normalize_trade_cal_row(row: dict[str, Any], *, fallback_exchange: str) -> dict[str, Any]:
    cal_date = _normalize_date_text(row.get("cal_date"))
    if not cal_date:
        raise ValueError(f"trade_cal 返回行缺少 cal_date：{row}")
    pretrade_date = _normalize_date_text(row.get("pretrade_date"))
    return {
        "exchange": row.get("exchange") or fallback_exchange,
        "cal_date": cal_date,
        "is_open": _normalize_is_open(row.get("is_open")),
        "pretrade_date": pretrade_date,
    }


def _normalize_date_text(value: Any) -> str | None:
    if value is None:
        return None
    raw_value = str(value).strip()
    if not raw_value:
        return None
    if len(raw_value) == 8 and raw_value.isdigit():
        return f"{raw_value[:4]}-{raw_value[4:6]}-{raw_value[6:]}"
    return date.fromisoformat(raw_value).isoformat()


def _normalize_is_open(value: Any) -> bool:
    return str(value).strip() == "1"


def _format_tushare_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _write_and_validate(*, rows: list[dict[str, Any]], tmp_file: Path) -> int:
    written = write_rows_to_parquet(rows, tmp_file)
    validated = read_parquet_row_count(tmp_file)
    if validated != written:
        raise RuntimeError(f"trade_cal Parquet 校验失败：written={written} validated={validated} file={tmp_file}")
    return written


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
