from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    replace_directory_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.prod_raw_event_date_db import (
    PROD_RAW_EVENT_DATE_SOURCE,
    EventDateDatasetSpec,
    get_event_date_dataset_spec,
    iter_event_date_rows,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


class DbEventDateExportService:
    def __init__(
        self,
        *,
        lake_root: Path,
        dataset_key: str,
        database_url: str | None,
        iter_rows: Callable[..., Iterator[list[dict[str, Any]]]] = iter_event_date_rows,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.lake_root = lake_root
        self.dataset_key = dataset_key
        self.database_url = database_url
        self.iter_rows = iter_rows
        self.progress = progress or print

    def export(self, *, event_dates: list[date]) -> dict[str, Any]:
        if not event_dates:
            raise ValueError(f"{self.dataset_key} prod_db_event_date 至少需要一个 event_date。")
        spec = get_event_date_dataset_spec(self.dataset_key)
        ordered_dates = sorted(set(event_dates))
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id(f"{self.dataset_key}-event-date")
        LakeRootService(self.lake_root).require_ready_for_write()
        self.progress(f"[{self.dataset_key}:{PROD_RAW_EVENT_DATE_SOURCE}] start run_id={run_id} dates={len(ordered_dates)}")

        partitions = [
            self._export_event_date(
                run_id=run_id,
                spec=spec,
                event_date=event_date,
                unit_index=index,
                unit_total=len(ordered_dates),
            )
            for index, event_date in enumerate(ordered_dates, start=1)
        ]
        fetched_total = sum(int(partition["fetched_rows"]) for partition in partitions)
        written_total = sum(int(partition["written_rows"]) for partition in partitions)
        skipped_total = sum(1 for partition in partitions if partition["skipped_replace"])
        source_changed_to_zero_total = sum(
            1 for partition in partitions if partition.get("skip_reason") == "source_changed_to_zero"
        )
        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": self.dataset_key,
            "api_name": self.dataset_key,
            "source": PROD_RAW_EVENT_DATE_SOURCE,
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "mode": "event_date_point" if len(ordered_dates) == 1 else "event_date_range",
            "date_axis": "event_date",
            "partition_field": "event_date",
            "source_date_field": spec.source_date_field,
            "start_date": ordered_dates[0].isoformat(),
            "end_date": ordered_dates[-1].isoformat(),
            "event_dates": [item.isoformat() for item in ordered_dates],
            "event_date_count": len(ordered_dates),
            "fetched_rows": fetched_total,
            "written_rows": written_total,
            "skipped_partitions": skipped_total,
            "source_changed_to_zero_partitions": source_changed_to_zero_total,
            "no_data_partitions": skipped_total,
            "partitions": partitions,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[{self.dataset_key}:{PROD_RAW_EVENT_DATE_SOURCE}] done dates={len(ordered_dates)} "
            f"fetched={fetched_total} written={written_total} skipped={skipped_total} elapsed={math.ceil(elapsed)}s"
        )
        return summary

    def _export_event_date(
        self,
        *,
        run_id: str,
        spec: EventDateDatasetSpec,
        event_date: date,
        unit_index: int,
        unit_total: int,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        fetched_rows = 0
        for batch in self.iter_rows(
            database_url=self.database_url,
            dataset_key=self.dataset_key,
            event_date=event_date,
            batch_size=20000,
            cursor_name=f"lake_{self.dataset_key}_event_date_cursor",
        ):
            fetched_rows += len(batch)
            rows.extend(self._normalize_row(row, spec=spec, expected_event_date=event_date) for row in batch)
            self.progress(
                f"[{self.dataset_key}:{PROD_RAW_EVENT_DATE_SOURCE}] unit={unit_index}/{unit_total} "
                f"event_date={event_date.isoformat()} fetched={fetched_rows}"
            )
        return self._write_partition(
            run_id=run_id,
            spec=spec,
            event_date=event_date,
            rows=rows,
            fetched_rows=fetched_rows,
            unit_index=unit_index,
            unit_total=unit_total,
        )

    def _write_partition(
        self,
        *,
        run_id: str,
        spec: EventDateDatasetSpec,
        event_date: date,
        rows: list[dict[str, Any]],
        fetched_rows: int,
        unit_index: int,
        unit_total: int,
    ) -> dict[str, Any]:
        if not rows:
            self.progress(
                f"[{self.dataset_key}:{PROD_RAW_EVENT_DATE_SOURCE}] unit={unit_index}/{unit_total} "
                f"event_date={event_date.isoformat()} fetched=0 skipped_replace=true"
            )
            return {
                "event_date": event_date.isoformat(),
                "fetched_rows": fetched_rows,
                "written_rows": 0,
                "skipped_replace": True,
                "skip_reason": "source_changed_to_zero",
                "output": None,
            }

        partition = f"event_date={event_date.isoformat()}"
        tmp_dir = self.lake_root / "_tmp" / run_id / "raw_tushare" / self.dataset_key / partition
        tmp_file = tmp_dir / "part-000.parquet"
        final_dir = self.lake_root / "raw_tushare" / self.dataset_key / partition
        final_file = final_dir / "part-000.parquet"
        backup_root = self.lake_root / "_tmp" / run_id / "_backup" / self.dataset_key / partition

        written = _write_and_validate(rows=rows, tmp_file=tmp_file, expected_fields=spec.fields)
        replace_directory_atomically(tmp_dir=tmp_dir, final_dir=final_dir, backup_root=backup_root)
        self.progress(
            f"[{self.dataset_key}:{PROD_RAW_EVENT_DATE_SOURCE}] unit={unit_index}/{unit_total} "
            f"event_date={event_date.isoformat()} written={written} output={final_file}"
        )
        return {
            "event_date": event_date.isoformat(),
            "fetched_rows": fetched_rows,
            "written_rows": written,
            "skipped_replace": False,
            "skip_reason": None,
            "output": str(final_file),
        }

    def _normalize_row(
        self,
        row: dict[str, Any],
        *,
        spec: EventDateDatasetSpec,
        expected_event_date: date,
    ) -> dict[str, Any]:
        source_date = _parse_event_date(row.get(spec.source_date_field))
        if source_date != expected_event_date:
            raise ValueError(
                f"{self.dataset_key} 返回 {spec.source_date_field}={source_date.isoformat()}，"
                f"与计划 event_date={expected_event_date.isoformat()} 不一致。"
            )
        normalized: dict[str, Any] = {}
        for field in spec.fields:
            value = row.get(field)
            if field == spec.source_date_field:
                normalized[field] = source_date
            elif value is None or _is_nan(value):
                normalized[field] = None
            elif isinstance(value, Decimal):
                normalized[field] = float(value)
            else:
                normalized[field] = value
        return normalized


def _write_and_validate(*, rows: list[dict[str, Any]], tmp_file: Path, expected_fields: tuple[str, ...]) -> int:
    if any(tuple(row) != expected_fields for row in rows):
        raise RuntimeError(f"event_date Parquet schema 不等于字段白名单：expected={expected_fields}")
    written = write_rows_to_parquet(rows, tmp_file)
    validated = read_parquet_row_count(tmp_file)
    if validated != written:
        raise RuntimeError(f"event_date Parquet 行数校验失败：written={written} validated={validated} file={tmp_file}")
    return written


def _parse_event_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if len(normalized) == 8 and normalized.isdigit():
            return date.fromisoformat(f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}")
        return date.fromisoformat(normalized)
    raise ValueError(f"event_date 不可解析：{value!r}")


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _run_id(suffix: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{suffix}"
