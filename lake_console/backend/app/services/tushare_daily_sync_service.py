from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.datasets.market_equity import DAILY_FIELDS
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    read_parquet_rows,
    replace_directory_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService
from lake_console.backend.app.services.tushare_client import TushareLakeClient


DAILY_PAGE_LIMIT = 6000


class TushareDailySyncService:
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

    def sync(
        self,
        *,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        ts_code: str | None = None,
    ) -> dict[str, Any]:
        if trade_date and (start_date or end_date):
            raise ValueError("daily 的 trade_date 与 start/end date 不能同时传。")
        if (start_date is None) != (end_date is None):
            raise ValueError("daily 的 start-date 和 end-date 必须同时传入，或同时省略。")
        if trade_date is None and start_date is None:
            raise ValueError("daily 必须传 --trade-date 或 --start-date/--end-date。")
        if start_date is not None and end_date is not None and end_date < start_date:
            raise ValueError("daily 的 end-date 不能早于 start-date。")

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("daily")
        LakeRootService(self.lake_root).require_ready_for_write()

        trade_dates = [trade_date] if trade_date is not None else self._load_open_trade_dates(start_date=start_date, end_date=end_date)  # type: ignore[arg-type]
        if not trade_dates:
            raise RuntimeError("本地交易日历未找到可同步的开市交易日。")

        normalized_ts_code = _normalize_ts_code(ts_code)
        self.progress(
            f"[daily] start run_id={run_id} dates={len(trade_dates)} "
            f"ts_code={normalized_ts_code or '-'}"
        )

        summaries: list[dict[str, Any]] = []
        fetched_total = 0
        written_total = 0
        rejected_total = 0
        for index, current_date in enumerate(trade_dates, start=1):
            summary = self._sync_trade_date(
                run_id=run_id,
                trade_date=current_date,
                ts_code=normalized_ts_code,
                unit_index=index,
                unit_total=len(trade_dates),
            )
            summaries.append(summary)
            fetched_total += int(summary["fetched_rows"])
            written_total += int(summary["written_rows"])
            rejected_total += int(summary["rejected_rows"])

        elapsed = time.monotonic() - started
        final_summary = {
            "dataset_key": "daily",
            "api_name": "daily",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "mode": "point_incremental" if trade_date is not None else "range_rebuild",
            "trade_date": trade_date.isoformat() if trade_date is not None else None,
            "start_date": start_date.isoformat() if start_date is not None else None,
            "end_date": end_date.isoformat() if end_date is not None else None,
            "ts_code": normalized_ts_code,
            "trade_date_count": len(trade_dates),
            "fetched_rows": fetched_total,
            "written_rows": written_total,
            "rejected_rows": rejected_total,
            "partitions": summaries,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(final_summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[daily] done dates={len(trade_dates)} fetched={fetched_total} "
            f"written={written_total} rejected={rejected_total} elapsed={math.ceil(elapsed)}s"
        )
        return final_summary

    def _sync_trade_date(
        self,
        *,
        run_id: str,
        trade_date: date,
        ts_code: str | None,
        unit_index: int,
        unit_total: int,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        rejected = 0
        fetched_total = 0
        offset = 0
        page = 1
        while True:
            page_rows = self.client.daily(
                fields=DAILY_FIELDS,
                trade_date=_format_tushare_date(trade_date),
                ts_code=ts_code,
                limit=DAILY_PAGE_LIMIT,
                offset=offset,
            )
            fetched_total += len(page_rows)
            self.progress(
                f"[daily] unit={unit_index}/{unit_total} trade_date={trade_date.isoformat()} "
                f"page={page} offset={offset} fetched_page={len(page_rows)} fetched_total={fetched_total}"
            )
            for row in page_rows:
                normalized = _normalize_daily_row(row, expected_trade_date=trade_date)
                if normalized is None:
                    rejected += 1
                    continue
                rows.append(normalized)
            if len(page_rows) < DAILY_PAGE_LIMIT:
                break
            offset += DAILY_PAGE_LIMIT
            page += 1

        if not rows:
            raise RuntimeError(
                f"daily {trade_date.isoformat()} 未获取到任何有效记录，拒绝覆盖本地日线分区。"
            )

        tmp_dir = self.lake_root / "_tmp" / run_id / "raw_tushare" / "daily" / f"trade_date={trade_date.isoformat()}"
        tmp_file = tmp_dir / "part-000.parquet"
        final_dir = self.lake_root / "raw_tushare" / "daily" / f"trade_date={trade_date.isoformat()}"
        final_file = final_dir / "part-000.parquet"
        backup_root = self.lake_root / "_tmp" / run_id / "_backup" / "daily" / f"trade_date={trade_date.isoformat()}"

        rows.sort(key=lambda item: str(item.get("ts_code") or ""))
        self.progress(f"[daily] writing trade_date={trade_date.isoformat()} rows={len(rows)} output={tmp_file}")
        written = _write_and_validate(rows=rows, tmp_file=tmp_file)
        replace_directory_atomically(tmp_dir=tmp_dir, final_dir=final_dir, backup_root=backup_root)
        self.progress(
            f"[daily] unit={unit_index}/{unit_total} trade_date={trade_date.isoformat()} "
            f"fetched={fetched_total} written={written} rejected={rejected} output={final_file}"
        )
        return {
            "trade_date": trade_date.isoformat(),
            "fetched_rows": fetched_total,
            "written_rows": written,
            "rejected_rows": rejected,
            "output": str(final_file),
        }

    def _load_open_trade_dates(self, *, start_date: date, end_date: date) -> list[date]:
        calendar_file = self.lake_root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
        if not calendar_file.exists():
            raise RuntimeError(
                "缺少本地交易日历 manifest/trading_calendar/tushare_trade_cal.parquet。"
                "请先执行 sync-trade-cal。"
            )
        rows = read_parquet_rows(calendar_file)
        trade_dates: list[date] = []
        for row in rows:
            if not _is_open(row.get("is_open")):
                continue
            current_date = _parse_date(row.get("cal_date"))
            if start_date <= current_date <= end_date:
                trade_dates.append(current_date)
        return sorted(set(trade_dates))


def _normalize_daily_row(row: dict[str, Any], *, expected_trade_date: date) -> dict[str, Any] | None:
    trade_date = _normalize_date(row.get("trade_date"))
    ts_code = _normalize_ts_code(row.get("ts_code"))
    if trade_date is None or ts_code is None:
        return None
    if trade_date != expected_trade_date:
        return None
    normalized: dict[str, Any] = {"ts_code": ts_code, "trade_date": trade_date}
    for field in DAILY_FIELDS:
        if field in {"ts_code", "trade_date"}:
            continue
        value = row.get(field)
        normalized[field] = None if _is_nan(value) else value
    return normalized


def _normalize_ts_code(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    return text


def _normalize_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    raw_value = str(value).strip()
    if not raw_value or raw_value.lower() in {"nan", "nat", "none", "null"}:
        return None
    if len(raw_value) == 8 and raw_value.isdigit():
        return date.fromisoformat(f"{raw_value[:4]}-{raw_value[4:6]}-{raw_value[6:]}")
    return date.fromisoformat(raw_value)


def _parse_date(value: Any) -> date:
    normalized = _normalize_date(value)
    if normalized is None:
        raise ValueError(f"无法解析日期：{value!r}")
    return normalized


def _is_open(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip() == "1"


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _format_tushare_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _write_and_validate(*, rows: list[dict[str, Any]], tmp_file: Path) -> int:
    written = write_rows_to_parquet(rows, tmp_file)
    validated = read_parquet_row_count(tmp_file)
    if validated != written:
        raise RuntimeError(f"daily Parquet 校验失败：written={written} validated={validated} file={tmp_file}")
    return written


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
