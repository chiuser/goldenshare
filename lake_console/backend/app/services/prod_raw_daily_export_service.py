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
from lake_console.backend.app.services.prod_raw_db import (
    PROD_RAW_DB_SOURCE,
    build_daily_prod_raw_query,
    build_daily_prod_raw_range_query,
    fetch_prod_raw_rows,
    iter_prod_raw_rows,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


class ProdRawDailyExportService:
    def __init__(
        self,
        *,
        lake_root: Path,
        database_url: str | None,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.lake_root = lake_root
        self.database_url = database_url
        self.progress = progress or print

    def export(
        self,
        *,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        ts_code: str | None = None,
    ) -> dict[str, Any]:
        if ts_code:
            raise ValueError("daily --from prod-raw-db 第一版不支持 --ts-code；请按 trade_date 全市场导出。")
        if trade_date and (start_date or end_date):
            raise ValueError("daily prod-raw-db 的 trade_date 与 start/end date 不能同时传。")
        if (start_date is None) != (end_date is None):
            raise ValueError("daily prod-raw-db 的 start-date 和 end-date 必须同时传入，或同时省略。")
        if trade_date is None and start_date is None:
            raise ValueError("daily prod-raw-db 必须传 --trade-date 或 --start-date/--end-date。")
        if start_date is not None and end_date is not None and end_date < start_date:
            raise ValueError("daily prod-raw-db 的 end-date 不能早于 start-date。")

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("daily-prod-raw")
        LakeRootService(self.lake_root).require_ready_for_write()
        trade_dates = [trade_date] if trade_date is not None else self._load_open_trade_dates(start_date=start_date, end_date=end_date)  # type: ignore[arg-type]
        if not trade_dates:
            raise RuntimeError("本地交易日历未找到可导出的开市交易日。")

        self.progress(f"[daily:prod-raw-db] start run_id={run_id} dates={len(trade_dates)}")
        if trade_date is not None:
            partitions = [
                self._export_trade_date(
                    run_id=run_id,
                    trade_date=trade_date,
                    unit_index=1,
                    unit_total=1,
                )
            ]
        else:
            partitions = self._export_trade_date_range(run_id=run_id, trade_dates=trade_dates)

        fetched_total = sum(int(partition["fetched_rows"]) for partition in partitions)
        written_total = sum(int(partition["written_rows"]) for partition in partitions)
        skipped_total = sum(1 for partition in partitions if partition["skipped_replace"])

        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "daily",
            "api_name": "daily",
            "source": PROD_RAW_DB_SOURCE,
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "mode": "point_incremental" if trade_date is not None else "range_rebuild",
            "trade_date": trade_date.isoformat() if trade_date is not None else None,
            "start_date": start_date.isoformat() if start_date is not None else None,
            "end_date": end_date.isoformat() if end_date is not None else None,
            "trade_date_count": len(trade_dates),
            "fetched_rows": fetched_total,
            "written_rows": written_total,
            "skipped_partitions": skipped_total,
            "partitions": partitions,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[daily:prod-raw-db] done dates={len(trade_dates)} fetched={fetched_total} "
            f"written={written_total} skipped={skipped_total} elapsed={math.ceil(elapsed)}s"
        )
        return summary

    def _export_trade_date(self, *, run_id: str, trade_date: date, unit_index: int, unit_total: int) -> dict[str, Any]:
        query = build_daily_prod_raw_query(trade_date=trade_date)
        source_rows = fetch_prod_raw_rows(database_url=self.database_url, query=query)
        rows = [_normalize_daily_prod_raw_row(row, expected_trade_date=trade_date) for row in source_rows]
        self.progress(
            f"[daily:prod-raw-db] unit={unit_index}/{unit_total} trade_date={trade_date.isoformat()} fetched={len(rows)}"
        )
        return self._write_partition(
            run_id=run_id,
            trade_date=trade_date,
            rows=rows,
            fetched_rows=len(source_rows),
            unit_index=unit_index,
            unit_total=unit_total,
        )

    def _export_trade_date_range(self, *, run_id: str, trade_dates: list[date]) -> list[dict[str, Any]]:
        expected_dates = set(trade_dates)
        unit_index_by_date = {item: index for index, item in enumerate(trade_dates, start=1)}
        summaries_by_date: dict[date, dict[str, Any]] = {}
        query = build_daily_prod_raw_range_query(start_date=min(trade_dates), end_date=max(trade_dates))

        current_date: date | None = None
        current_rows: list[dict[str, Any]] = []
        current_fetched = 0
        ignored_rows = 0
        fetched_total = 0
        for batch in iter_prod_raw_rows(database_url=self.database_url, query=query):
            fetched_total += len(batch)
            self.progress(
                f"[daily:prod-raw-db] range_fetch fetched_total={fetched_total} "
                f"current_trade_date={current_date.isoformat() if current_date else '-'}"
            )
            for source_row in batch:
                row_date = _parse_date(source_row.get("trade_date"))
                if row_date not in expected_dates:
                    ignored_rows += 1
                    continue
                if current_date is not None and row_date != current_date:
                    summaries_by_date[current_date] = self._write_partition(
                        run_id=run_id,
                        trade_date=current_date,
                        rows=current_rows,
                        fetched_rows=current_fetched,
                        unit_index=unit_index_by_date[current_date],
                        unit_total=len(trade_dates),
                    )
                    current_rows = []
                    current_fetched = 0
                current_date = row_date
                current_rows.append(_normalize_daily_prod_raw_row(source_row, expected_trade_date=row_date))
                current_fetched += 1

        if current_date is not None:
            summaries_by_date[current_date] = self._write_partition(
                run_id=run_id,
                trade_date=current_date,
                rows=current_rows,
                fetched_rows=current_fetched,
                unit_index=unit_index_by_date[current_date],
                unit_total=len(trade_dates),
            )

        if ignored_rows:
            self.progress(f"[daily:prod-raw-db] ignored rows outside local trading calendar={ignored_rows}")

        summaries: list[dict[str, Any]] = []
        for current_trade_date in trade_dates:
            summary = summaries_by_date.get(current_trade_date)
            if summary is None:
                summary = self._empty_partition_summary(trade_date=current_trade_date)
                self.progress(
                    f"[daily:prod-raw-db] unit={unit_index_by_date[current_trade_date]}/{len(trade_dates)} "
                    f"trade_date={current_trade_date.isoformat()} fetched=0 skipped_replace=true"
                )
            summaries.append(summary)
        return summaries

    def _write_partition(
        self,
        *,
        run_id: str,
        trade_date: date,
        rows: list[dict[str, Any]],
        fetched_rows: int,
        unit_index: int,
        unit_total: int,
    ) -> dict[str, Any]:
        if not rows:
            return self._empty_partition_summary(trade_date=trade_date)

        tmp_dir = self.lake_root / "_tmp" / run_id / "raw_tushare" / "daily" / f"trade_date={trade_date.isoformat()}"
        tmp_file = tmp_dir / "part-000.parquet"
        final_dir = self.lake_root / "raw_tushare" / "daily" / f"trade_date={trade_date.isoformat()}"
        final_file = final_dir / "part-000.parquet"
        backup_root = self.lake_root / "_tmp" / run_id / "_backup" / "daily" / f"trade_date={trade_date.isoformat()}"

        rows.sort(key=lambda item: str(item.get("ts_code") or ""))
        written = _write_and_validate(rows=rows, tmp_file=tmp_file)
        replace_directory_atomically(tmp_dir=tmp_dir, final_dir=final_dir, backup_root=backup_root)
        self.progress(
            f"[daily:prod-raw-db] unit={unit_index}/{unit_total} trade_date={trade_date.isoformat()} "
            f"written={written} output={final_file}"
        )
        return {
            "trade_date": trade_date.isoformat(),
            "fetched_rows": fetched_rows,
            "written_rows": written,
            "skipped_replace": False,
            "output": str(final_file),
        }

    def _empty_partition_summary(self, *, trade_date: date) -> dict[str, Any]:
        return {
            "trade_date": trade_date.isoformat(),
            "fetched_rows": 0,
            "written_rows": 0,
            "skipped_replace": True,
            "output": None,
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


def _normalize_daily_prod_raw_row(row: dict[str, Any], *, expected_trade_date: date) -> dict[str, Any]:
    trade_date = _parse_date(row.get("trade_date"))
    ts_code = _normalize_ts_code(row.get("ts_code"))
    if trade_date != expected_trade_date:
        raise ValueError(
            f"raw_tushare.daily 返回 trade_date={trade_date.isoformat()}，"
            f"与请求日期 {expected_trade_date.isoformat()} 不一致。"
        )
    if ts_code is None:
        raise ValueError("raw_tushare.daily 返回行缺少 ts_code。")
    normalized: dict[str, Any] = {"ts_code": ts_code, "trade_date": trade_date}
    for field in DAILY_FIELDS:
        if field in {"ts_code", "trade_date"}:
            continue
        value = row.get(field)
        normalized[field] = None if value is None or _is_nan(value) else float(value)
    return normalized


def _normalize_ts_code(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    raw_value = str(value).strip()
    if len(raw_value) == 8 and raw_value.isdigit():
        return date.fromisoformat(f"{raw_value[:4]}-{raw_value[4:6]}-{raw_value[6:]}")
    return date.fromisoformat(raw_value)


def _is_open(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip() == "1"


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _write_and_validate(*, rows: list[dict[str, Any]], tmp_file: Path) -> int:
    written = write_rows_to_parquet(rows, tmp_file)
    validated = read_parquet_row_count(tmp_file)
    if validated != written:
        raise RuntimeError(f"daily prod-raw-db Parquet 校验失败：written={written} validated={validated} file={tmp_file}")
    return written


def _run_id(prefix: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{prefix}"
