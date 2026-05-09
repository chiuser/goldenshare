from __future__ import annotations

import math
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.index_mins_common import normalize_index_mins_freqs, normalize_index_mins_row
from lake_console.backend.app.services.index_mins_partition_writer import IndexMinsPartitionWriter
from lake_console.backend.app.services.index_mins_universe_filter import load_index_mins_universe_for_range
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.prod_raw_db import (
    build_prod_raw_index_mins_range_query,
    iter_prod_raw_rows,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService
from lake_console.backend.app.sync.helpers.dates import load_open_trade_dates


class ProdRawIndexMinsExportService:
    def __init__(
        self,
        *,
        lake_root: Path,
        database_url: str | None,
        progress=None,
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
        freqs: list[str],
    ) -> dict[str, Any]:
        _validate_date_args(trade_date=trade_date, start_date=start_date, end_date=end_date)
        normalized_freqs = normalize_index_mins_freqs(freqs)

        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("index-mins-prod-raw-db")
        LakeRootService(self.lake_root).require_ready_for_write()

        request_start_date, request_end_date = _resolve_request_range(
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        )
        trade_dates = load_open_trade_dates(
            lake_root=self.lake_root,
            start_date=request_start_date,
            end_date=request_end_date,
        )
        if not trade_dates:
            raise RuntimeError("index_mins 在目标范围内没有可导出的开市交易日。")

        universe = load_index_mins_universe_for_range(
            lake_root=self.lake_root,
            start_date=request_start_date,
            end_date=request_end_date,
            ts_code=ts_code,
        )
        self.progress(
            f"[index_mins:prod-raw-db] start run_id={run_id} dates={len(trade_dates)} freqs={','.join(normalized_freqs)} "
            f"codes={len(universe.ts_codes)} ts_code={ts_code or '-'}"
        )

        partition_writer = IndexMinsPartitionWriter(lake_root=self.lake_root, run_id=run_id, progress=self.progress)
        expected_effective_counts = {
            (current_freq, current_trade_date): universe.effective_code_count_on(trade_date=current_trade_date)
            for current_freq in normalized_freqs
            for current_trade_date in trade_dates
        }
        partition_fetched: dict[tuple[str, date], int] = {
            key: 0 for key in expected_effective_counts
        }
        fetched_total = 0
        rejected_total = 0
        request_count = 0
        expected_trade_date_set = set(trade_dates)

        for current_freq in normalized_freqs:
            request_count += 1
            query = build_prod_raw_index_mins_range_query(
                start_date=request_start_date,
                end_date=request_end_date,
                freq=current_freq,
                ts_codes=universe.ts_codes,
            )
            for batch in iter_prod_raw_rows(
                database_url=self.database_url,
                query=query,
                batch_size=20000,
                cursor_name=f"lake_index_mins_{current_freq.replace('min', '')}_prod_raw_cursor",
            ):
                fetched_total += len(batch)
                self.progress(
                    f"[index_mins:prod-raw-db] freq={current_freq} fetched_batch={len(batch)} fetched_total={fetched_total}"
                )
                grouped_rows: dict[date, list[dict[str, Any]]] = {}
                for row in batch:
                    try:
                        normalized = normalize_index_mins_row(row, requested_freq=current_freq)
                    except Exception:  # noqa: BLE001
                        rejected_total += 1
                        continue
                    row_trade_date = normalized["trade_time"].date()
                    current_ts_code = normalized["ts_code"]
                    if row_trade_date not in expected_trade_date_set:
                        rejected_total += 1
                        continue
                    if not universe.is_effective_on(ts_code=current_ts_code, trade_date=row_trade_date):
                        rejected_total += 1
                        continue
                    grouped_rows.setdefault(row_trade_date, []).append(normalized)
                for current_trade_date, rows in grouped_rows.items():
                    partition_writer.stage_rows(freq=current_freq, trade_date=current_trade_date, rows=rows)
                    partition_fetched[(current_freq, current_trade_date)] += len(rows)

        partitions: list[dict[str, Any]] = []
        written_total = 0
        for current_freq in normalized_freqs:
            for current_trade_date in trade_dates:
                effective_code_count = expected_effective_counts[(current_freq, current_trade_date)]
                partition_summary = partition_writer.finalize_partition(
                    freq=current_freq,
                    trade_date=current_trade_date,
                    skip_reason="no_effective_universe" if effective_code_count == 0 else "no_data",
                )
                partition_summary["fetched_rows"] = partition_fetched[(current_freq, current_trade_date)]
                partition_summary["effective_code_count"] = effective_code_count
                partitions.append(partition_summary)
                written_total += int(partition_summary["written_rows"])

        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "index_mins",
            "api_name": "idx_mins",
            "source": "prod-raw-db",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "mode": "point_incremental" if trade_date is not None else "range_rebuild",
            "trade_date": trade_date.isoformat() if trade_date is not None else None,
            "start_date": start_date.isoformat() if start_date is not None else None,
            "end_date": end_date.isoformat() if end_date is not None else None,
            "ts_code": _normalize_ts_code(ts_code),
            "freqs": normalized_freqs,
            "trade_date_count": len(trade_dates),
            "request_count": request_count,
            "fetched_rows": fetched_total,
            "written_rows": written_total,
            "rejected_rows": rejected_total,
            "universe": universe.to_dict(),
            "partitions": partitions,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[index_mins:prod-raw-db] done dates={len(trade_dates)} freqs={len(normalized_freqs)} "
            f"queries={request_count} fetched={fetched_total} written={written_total} rejected={rejected_total} "
            f"elapsed={math.ceil(elapsed)}s"
        )
        return summary


def _validate_date_args(*, trade_date: date | None, start_date: date | None, end_date: date | None) -> None:
    if trade_date and (start_date or end_date):
        raise ValueError("index_mins 的 trade_date 与 start/end date 不能同时传。")
    if (start_date is None) != (end_date is None):
        raise ValueError("index_mins 的 start-date 和 end-date 必须同时传入，或同时省略。")
    if trade_date is None and start_date is None:
        raise ValueError("index_mins 必须传 --trade-date 或 --start-date/--end-date。")
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ValueError("index_mins 的 end-date 不能早于 start-date。")


def _resolve_request_range(
    *,
    trade_date: date | None,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:
    if trade_date is not None:
        return trade_date, trade_date
    assert start_date is not None and end_date is not None
    return start_date, end_date


def _normalize_ts_code(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().upper()
    return text or None


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
