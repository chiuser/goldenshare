from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.tushare_reference_master import INDEX_BASIC_FIELDS
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    replace_file_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService
from lake_console.backend.app.services.tushare_client import TushareLakeClient


INDEX_BASIC_PAGE_LIMIT = 6000


class TushareIndexBasicSyncService:
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
        ts_code: str | None = None,
        name: str | None = None,
        markets: list[str] | None = None,
        publisher: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("index-basic")
        LakeRootService(self.lake_root).require_ready_for_write()
        self.progress(f"[index_basic] start run_id={run_id}")

        rows_by_code: dict[str, dict[str, Any]] = {}
        fetched_total = 0
        market_values = markets or [None]
        for market in market_values:
            offset = 0
            page = 1
            while True:
                rows = self.client.index_basic(
                    fields=INDEX_BASIC_FIELDS,
                    ts_code=ts_code,
                    name=name,
                    market=market,
                    publisher=publisher,
                    category=category,
                    limit=INDEX_BASIC_PAGE_LIMIT,
                    offset=offset,
                )
                fetched_total += len(rows)
                self.progress(
                    f"[index_basic] market={market or '-'} page={page} offset={offset} "
                    f"fetched={len(rows)} total_fetched={fetched_total}"
                )
                for row in rows:
                    normalized = _normalize_index_basic_row(row)
                    row_code = normalized.get("ts_code")
                    if not row_code:
                        continue
                    rows_by_code[str(row_code)] = normalized
                if len(rows) < INDEX_BASIC_PAGE_LIMIT:
                    break
                offset += INDEX_BASIC_PAGE_LIMIT
                page += 1

        output_rows = sorted(rows_by_code.values(), key=lambda item: str(item.get("ts_code") or ""))
        if not output_rows:
            raise RuntimeError("index_basic 未获取到任何有效指数记录，拒绝覆盖本地指数基础信息。")

        backup_root = self.lake_root / "_tmp" / run_id / "_backup"
        raw_tmp = self.lake_root / "_tmp" / run_id / "raw_tushare" / "index_basic" / "current" / "part-000.parquet"
        raw_final = self.lake_root / "raw_tushare" / "index_basic" / "current" / "part-000.parquet"
        universe_tmp = self.lake_root / "_tmp" / run_id / "manifest" / "index_universe" / "tushare_index_basic.parquet"
        universe_final = self.lake_root / "manifest" / "index_universe" / "tushare_index_basic.parquet"

        self.progress(f"[index_basic] writing raw rows={len(output_rows)} output={raw_tmp}")
        raw_written = _write_and_validate(rows=output_rows, tmp_file=raw_tmp)
        self.progress(f"[index_basic] writing universe rows={len(output_rows)} output={universe_tmp}")
        universe_written = _write_and_validate(rows=output_rows, tmp_file=universe_tmp)

        replace_file_atomically(tmp_file=raw_tmp, final_file=raw_final, backup_root=backup_root / "raw_index_basic")
        replace_file_atomically(tmp_file=universe_tmp, final_file=universe_final, backup_root=backup_root / "index_universe")
        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": "index_basic",
            "api_name": "index_basic",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "fetched_rows": fetched_total,
            "written_rows": raw_written,
            "raw_output": str(raw_final),
            "universe_output": str(universe_final),
            "universe_written_rows": universe_written,
            "markets": [item for item in market_values if item],
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[index_basic] done fetched={fetched_total} raw_written={raw_written} "
            f"universe_written={universe_written} raw_output={raw_final} "
            f"universe_output={universe_final} elapsed={math.ceil(elapsed)}s"
        )
        return summary


def _normalize_index_basic_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for field in INDEX_BASIC_FIELDS:
        value = row.get(field)
        normalized[field] = None if _is_nan(value) else value
    return normalized


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _write_and_validate(*, rows: list[dict[str, Any]], tmp_file: Path) -> int:
    written = write_rows_to_parquet(rows, tmp_file)
    validated = read_parquet_row_count(tmp_file)
    if validated != written:
        raise RuntimeError(f"index_basic Parquet 校验失败：written={written} validated={validated} file={tmp_file}")
    return written


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
