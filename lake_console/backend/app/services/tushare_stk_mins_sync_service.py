from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time as time_type, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.tushare_stk_mins import STK_MINS_ALLOWED_FREQS, STK_MINS_FIELDS
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_rows,
    read_parquet_row_count,
    replace_directory_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService
from lake_console.backend.app.services.tushare_client import TushareLakeClient


STK_MINS_PAGE_LIMIT = 8000
DEFAULT_PART_ROWS = 200_000


@dataclass(frozen=True)
class StkMinsProgressEvent:
    units_done: int
    units_total: int
    ts_code: str
    trade_date: date
    freq: int
    fetched_rows: int
    written_rows: int


ProgressCallback = Callable[[str | StkMinsProgressEvent], None]


class TushareStkMinsSyncService:
    def __init__(
        self,
        *,
        lake_root: Path,
        client: TushareLakeClient,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.lake_root = lake_root
        self.client = client
        self.progress = progress or print

    def sync_single_symbol_day(self, *, ts_code: str, freq: int, trade_date: date) -> dict[str, Any]:
        if not ts_code:
            raise ValueError("sync-stk-mins 当前阶段必须显式传入 --ts-code。")
        if freq not in STK_MINS_ALLOWED_FREQS:
            allowed = ", ".join(str(item) for item in sorted(STK_MINS_ALLOWED_FREQS))
            raise ValueError(f"不支持的 freq={freq}，允许值：{allowed}")

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("stk-mins")
        LakeRootService(self.lake_root).require_ready_for_write()
        self._ensure_stock_universe_exists()
        start_date = datetime.combine(trade_date, time_type(hour=9), tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        end_date = datetime.combine(trade_date, time_type(hour=19), tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        self.progress(f"[stk_mins] start run_id={run_id} ts_code={ts_code} freq={freq} trade_date={trade_date.isoformat()}")

        all_rows: list[dict[str, Any]] = []
        offset = 0
        page = 1
        while True:
            rows = self.client.stk_mins(
                ts_code=ts_code,
                freq=freq,
                start_date=start_date,
                end_date=end_date,
                limit=STK_MINS_PAGE_LIMIT,
                offset=offset,
            )
            self.progress(
                f"[stk_mins] page={page} ts_code={ts_code} freq={freq} trade_date={trade_date.isoformat()} "
                f"offset={offset} fetched_rows={len(rows)} accumulated_rows={len(all_rows) + len(rows)}"
            )
            all_rows.extend(_normalize_stk_mins_row(row, freq=freq, trade_date=trade_date) for row in rows)
            if len(rows) < STK_MINS_PAGE_LIMIT:
                break
            offset += STK_MINS_PAGE_LIMIT
            page += 1

        if not all_rows:
            self.progress(f"[stk_mins] done fetched=0 written=0 ts_code={ts_code} freq={freq} trade_date={trade_date.isoformat()}")
            summary = self._summary(
                run_id=run_id,
                started_at=started_at,
                ts_code=ts_code,
                freq=freq,
                trade_date=trade_date,
                fetched_rows=0,
                written_rows=0,
                output=None,
                elapsed_seconds=round(time.monotonic() - started, 3),
            )
            ManifestService(self.lake_root).append_sync_run(summary)
            return summary

        partition = (
            self.lake_root
            / "raw_tushare"
            / "stk_mins_by_date"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        )
        tmp_dir = self.lake_root / "_tmp" / run_id / "raw_tushare" / "stk_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date.isoformat()}"
        tmp_file = tmp_dir / "part-000.parquet"
        backup_root = self.lake_root / "_tmp" / run_id / "_backup"
        self.progress(f"[stk_mins] writing rows={len(all_rows)} partition={tmp_dir}")
        written = write_rows_to_parquet(all_rows, tmp_file)
        validated = read_parquet_row_count(tmp_file)
        if validated != written:
            raise RuntimeError(f"stk_mins Parquet 校验失败：written={written} validated={validated}")

        replace_directory_atomically(tmp_dir=tmp_dir, final_dir=partition, backup_root=backup_root)
        elapsed = time.monotonic() - started
        summary = self._summary(
            run_id=run_id,
            started_at=started_at,
            ts_code=ts_code,
            freq=freq,
            trade_date=trade_date,
            fetched_rows=len(all_rows),
            written_rows=written,
            output=str(partition),
            elapsed_seconds=round(elapsed, 3),
        )
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[stk_mins] done ts_code={ts_code} freq={freq} trade_date={trade_date.isoformat()} "
            f"fetched={len(all_rows)} written={written} partition={partition} elapsed={math.ceil(elapsed)}s"
        )
        return summary

    def sync_market_day(self, *, freqs: list[int], trade_date: date, part_rows: int = DEFAULT_PART_ROWS) -> dict[str, Any]:
        if not freqs:
            raise ValueError("sync-stk-mins --all-market 必须至少指定一个 freq。")
        invalid_freqs = sorted(set(freqs) - STK_MINS_ALLOWED_FREQS)
        if invalid_freqs:
            allowed = ", ".join(str(item) for item in sorted(STK_MINS_ALLOWED_FREQS))
            raise ValueError(f"不支持的 freq={invalid_freqs}，允许值：{allowed}")
        if part_rows <= 0:
            raise ValueError("part_rows 必须大于 0。")

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("stk-mins-market")
        LakeRootService(self.lake_root).require_ready_for_write()
        ts_codes = self._load_stock_universe_codes()
        self.progress(
            f"[stk_mins] start all_market run_id={run_id} symbols_total={len(ts_codes)} "
            f"freqs={','.join(str(item) for item in freqs)} trade_date={trade_date.isoformat()}"
        )

        day_summary = self._sync_market_day_partitions(
            run_id=run_id,
            freqs=freqs,
            trade_date=trade_date,
            ts_codes=ts_codes,
            part_rows=part_rows,
            verbose=True,
        )
        total_fetched = int(day_summary["fetched_rows"])
        total_written = int(day_summary["written_rows"])

        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "stk_mins",
            "api_name": "stk_mins",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "mode": "all_market",
            "freqs": freqs,
            "trade_date": trade_date.isoformat(),
            "symbols_total": len(ts_codes),
            "fetched_rows": total_fetched,
            "written_rows": total_written,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[stk_mins] done all_market trade_date={trade_date.isoformat()} freqs={','.join(str(item) for item in freqs)} "
            f"symbols_total={len(ts_codes)} fetched={total_fetched} written={total_written} elapsed={math.ceil(elapsed)}s"
        )
        return summary

    def _sync_market_day_partitions(
        self,
        *,
        run_id: str,
        freqs: list[int],
        trade_date: date,
        ts_codes: list[str],
        part_rows: int,
        verbose: bool,
        unit_base: int = 0,
        units_total: int | None = None,
    ) -> dict[str, Any]:
        total_units = units_total or (len(freqs) * len(ts_codes))
        total_fetched = 0
        total_written = 0
        for freq_index, freq in enumerate(freqs, start=1):
            tmp_partition = (
                self.lake_root
                / "_tmp"
                / run_id
                / "raw_tushare"
                / "stk_mins_by_date"
                / f"freq={freq}"
                / f"trade_date={trade_date.isoformat()}"
            )
            final_partition = (
                self.lake_root
                / "raw_tushare"
                / "stk_mins_by_date"
                / f"freq={freq}"
                / f"trade_date={trade_date.isoformat()}"
            )
            part_buffer: list[dict[str, Any]] = []
            part_index = 0
            freq_fetched = 0
            freq_written = 0
            for symbol_index, ts_code in enumerate(ts_codes, start=1):
                rows = self._fetch_symbol_day(ts_code=ts_code, freq=freq, trade_date=trade_date, verbose=verbose)
                part_buffer.extend(rows)
                freq_fetched += len(rows)
                total_fetched += len(rows)
                unit_done = unit_base + ((freq_index - 1) * len(ts_codes)) + symbol_index
                if verbose:
                    self.progress(
                        f"[stk_mins] all_market freq={freq} freq_index={freq_index}/{len(freqs)} "
                        f"symbol={ts_code} symbols_done={symbol_index}/{len(ts_codes)} "
                        f"fetched_rows={len(rows)} accumulated_freq_rows={freq_fetched}"
                    )
                else:
                    self.progress(
                        StkMinsProgressEvent(
                            units_done=unit_done,
                            units_total=total_units,
                            ts_code=ts_code,
                            trade_date=trade_date,
                            freq=freq,
                            fetched_rows=len(rows),
                            written_rows=total_written,
                        )
                    )
                if len(part_buffer) >= part_rows:
                    written = self._flush_part(rows=part_buffer, tmp_partition=tmp_partition, part_index=part_index)
                    freq_written += written
                    total_written += written
                    part_index += 1
                    part_buffer = []
                    if verbose:
                        self.progress(
                            f"[stk_mins] all_market flush freq={freq} part={part_index} "
                            f"freq_written={freq_written} total_written={total_written}"
                        )
            if part_buffer:
                written = self._flush_part(rows=part_buffer, tmp_partition=tmp_partition, part_index=part_index)
                freq_written += written
                total_written += written
            if freq_written:
                replace_directory_atomically(
                    tmp_dir=tmp_partition,
                    final_dir=final_partition,
                    backup_root=self.lake_root / "_tmp" / run_id / "_backup",
                )
            if verbose:
                self.progress(
                    f"[stk_mins] all_market freq_done freq={freq} fetched={freq_fetched} written={freq_written} "
                    f"partition={final_partition}"
                )
        return {
            "trade_date": trade_date.isoformat(),
            "freqs": freqs,
            "symbols_total": len(ts_codes),
            "fetched_rows": total_fetched,
            "written_rows": total_written,
        }

    def sync_range(
        self,
        *,
        start_date: date,
        end_date: date,
        freqs: list[int],
        all_market: bool,
        ts_code: str | None = None,
        freq: int | None = None,
        part_rows: int = DEFAULT_PART_ROWS,
    ) -> dict[str, Any]:
        if end_date < start_date:
            raise ValueError("sync-stk-mins-range 的 end-date 不能早于 start-date。")
        trade_dates = self._load_open_trade_dates(start_date=start_date, end_date=end_date)
        if not trade_dates:
            raise RuntimeError(f"本地交易日历中 {start_date.isoformat()} ~ {end_date.isoformat()} 没有开市日。")

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("stk-mins-range")
        self.progress(
            f"[stk_mins_range] start run_id={run_id} start_date={start_date.isoformat()} end_date={end_date.isoformat()} "
            f"trade_dates={len(trade_dates)} mode={'all_market' if all_market else 'single_symbol'}"
        )

        total_fetched = 0
        total_written = 0
        summaries: list[dict[str, Any]] = []
        if all_market:
            if not freqs:
                raise ValueError("sync-stk-mins-range --all-market 必须至少指定一个 freq。")
            invalid_freqs = sorted(set(freqs) - STK_MINS_ALLOWED_FREQS)
            if invalid_freqs:
                allowed = ", ".join(str(item) for item in sorted(STK_MINS_ALLOWED_FREQS))
                raise ValueError(f"不支持的 freq={invalid_freqs}，允许值：{allowed}")
            if part_rows <= 0:
                raise ValueError("part_rows 必须大于 0。")
            LakeRootService(self.lake_root).require_ready_for_write()
            ts_codes = self._load_stock_universe_codes()
            units_per_day = len(freqs) * len(ts_codes)
            units_total = len(trade_dates) * units_per_day
            for date_index, trade_date in enumerate(trade_dates, start=1):
                day_summary = self._sync_market_day_partitions(
                    run_id=run_id,
                    freqs=freqs,
                    trade_date=trade_date,
                    ts_codes=ts_codes,
                    part_rows=part_rows,
                    verbose=False,
                    unit_base=(date_index - 1) * units_per_day,
                    units_total=units_total,
                )
                summaries.append(day_summary)
                total_fetched += int(day_summary.get("fetched_rows") or 0)
                total_written += int(day_summary.get("written_rows") or 0)
        else:
            for date_index, trade_date in enumerate(trade_dates, start=1):
                self.progress(f"[stk_mins_range] trade_date={trade_date.isoformat()} dates_done={date_index}/{len(trade_dates)}")
                if not ts_code:
                    raise ValueError("单股票区间模式必须传 ts_code。")
                if freq is None:
                    raise ValueError("单股票区间模式必须传 freq。")
                day_summary = self.sync_single_symbol_day(ts_code=ts_code, freq=freq, trade_date=trade_date)
                summaries.append(day_summary)
                total_fetched += int(day_summary.get("fetched_rows") or 0)
                total_written += int(day_summary.get("written_rows") or 0)

        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "stk_mins",
            "api_name": "stk_mins",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "mode": "range_all_market" if all_market else "range_single_symbol",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "trade_dates": [item.isoformat() for item in trade_dates],
            "trade_date_count": len(trade_dates),
            "freqs": freqs if all_market else ([freq] if freq is not None else []),
            "ts_code": ts_code,
            "fetched_rows": total_fetched,
            "written_rows": total_written,
            "day_runs": summaries,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        self.progress(
            f"[stk_mins_range] done trade_dates={len(trade_dates)} fetched={total_fetched} "
            f"written={total_written} elapsed={math.ceil(elapsed)}s"
        )
        return summary

    @staticmethod
    def _summary(
        *,
        run_id: str,
        started_at: datetime,
        ts_code: str,
        freq: int,
        trade_date: date,
        fetched_rows: int,
        written_rows: int,
        output: str | None,
        elapsed_seconds: float,
    ) -> dict[str, Any]:
        return {
            "dataset_key": "stk_mins",
            "api_name": "stk_mins",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "ts_code": ts_code,
            "freq": freq,
            "trade_date": trade_date.isoformat(),
            "fetched_rows": fetched_rows,
            "written_rows": written_rows,
            "output": output,
            "elapsed_seconds": elapsed_seconds,
        }

    def _load_stock_universe_codes(self) -> list[str]:
        universe_file = self.lake_root / "manifest" / "security_universe" / "tushare_stock_basic.parquet"
        self._ensure_stock_universe_exists()
        rows = read_parquet_rows(universe_file)
        codes = sorted(
            {
                str(row.get("ts_code")).strip()
                for row in rows
                if row.get("ts_code") and str(row.get("list_status") or "L").strip() == "L"
            }
        )
        if not codes:
            raise RuntimeError("本地股票池中没有 list_status=L 的有效 ts_code。")
        return codes

    def _load_open_trade_dates(self, *, start_date: date, end_date: date) -> list[date]:
        calendar_file = self.lake_root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
        if not calendar_file.exists():
            raise RuntimeError(
                "缺少本地交易日历 manifest/trading_calendar/tushare_trade_cal.parquet。"
                "请先执行 sync-trade-cal。"
            )
        rows = read_parquet_rows(calendar_file)
        result: list[date] = []
        for row in rows:
            if not bool(row.get("is_open")):
                continue
            cal_date = _parse_date(row.get("cal_date"))
            if start_date <= cal_date <= end_date:
                result.append(cal_date)
        return sorted(set(result))

    def _ensure_stock_universe_exists(self) -> None:
        universe_file = self.lake_root / "manifest" / "security_universe" / "tushare_stock_basic.parquet"
        if not universe_file.exists():
            raise RuntimeError(
                "缺少本地股票池 manifest/security_universe/tushare_stock_basic.parquet。"
                "请先执行 sync-stock-basic。"
            )

    def _fetch_symbol_day(self, *, ts_code: str, freq: int, trade_date: date, verbose: bool = True) -> list[dict[str, Any]]:
        start_date = datetime.combine(trade_date, time_type(hour=9), tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        end_date = datetime.combine(trade_date, time_type(hour=19), tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        rows: list[dict[str, Any]] = []
        offset = 0
        page = 1
        while True:
            page_rows = self.client.stk_mins(
                ts_code=ts_code,
                freq=freq,
                start_date=start_date,
                end_date=end_date,
                limit=STK_MINS_PAGE_LIMIT,
                offset=offset,
            )
            if verbose:
                self.progress(
                    f"[stk_mins] page={page} ts_code={ts_code} freq={freq} trade_date={trade_date.isoformat()} "
                    f"offset={offset} fetched_rows={len(page_rows)}"
                )
            rows.extend(_normalize_stk_mins_row(row, freq=freq, trade_date=trade_date) for row in page_rows)
            if len(page_rows) < STK_MINS_PAGE_LIMIT:
                break
            offset += STK_MINS_PAGE_LIMIT
            page += 1
        return rows

    @staticmethod
    def _flush_part(*, rows: list[dict[str, Any]], tmp_partition: Path, part_index: int) -> int:
        output_file = tmp_partition / f"part-{part_index:05d}.parquet"
        written = write_rows_to_parquet(rows, output_file)
        validated = read_parquet_row_count(output_file)
        if validated != written:
            raise RuntimeError(f"stk_mins part 校验失败：written={written} validated={validated} file={output_file}")
        return written


def _normalize_stk_mins_row(row: dict[str, Any], *, freq: int, trade_date: date) -> dict[str, Any]:
    normalized: dict[str, Any] = {field: None for field in STK_MINS_FIELDS}
    for field in STK_MINS_FIELDS:
        normalized[field] = None if _is_nan(row.get(field)) else row.get(field)
    normalized["freq"] = freq
    normalized["trade_time"] = _normalize_trade_time(normalized.get("trade_time"), trade_date=trade_date)
    return normalized


def _normalize_trade_time(value: Any, *, trade_date: date) -> str:
    if isinstance(value, datetime):
        trade_time = value
    elif value is None:
        raise ValueError("stk_mins 返回行缺少 trade_time。")
    else:
        trade_time = datetime.fromisoformat(str(value))
    if trade_time.date() != trade_date:
        raise ValueError(f"stk_mins 返回 trade_time={trade_time} 与请求 trade_date={trade_date} 不一致。")
    return trade_time.strftime("%Y-%m-%d %H:%M:%S")


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    raw_value = str(value).strip()
    if len(raw_value) == 8 and raw_value.isdigit():
        return date(int(raw_value[:4]), int(raw_value[4:6]), int(raw_value[6:]))
    return date.fromisoformat(raw_value)


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
