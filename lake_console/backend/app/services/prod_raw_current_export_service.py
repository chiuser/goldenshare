from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.datasets import get_dataset_definition
from lake_console.backend.app.catalog.models import LakeLayerDefinition
from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    replace_file_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.prod_raw_db import (
    PROD_RAW_DB_SOURCE,
    build_prod_raw_current_query,
    fetch_prod_raw_rows,
    iter_prod_raw_rows,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


_FLOAT_FIELDS: dict[str, tuple[str, ...]] = {
    "etf_basic": ("mgt_fee",),
    "etf_index": ("bp",),
    "ths_member": ("weight",),
}

_STREAMING_DATASETS = {"ths_member"}


class ProdRawCurrentExportService:
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

    def export(self, *, dataset_key: str) -> dict[str, Any]:
        definition = get_dataset_definition(dataset_key)
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id(dataset_key.replace("_", "-"))
        LakeRootService(self.lake_root).require_ready_for_write()

        raw_layer = _require_layer(definition.layers, layer="raw_tushare")
        manifest_layer = _require_layer(definition.layers, layer="manifest")
        query = build_prod_raw_current_query(dataset_key=dataset_key)

        self.progress(f"[{dataset_key}:prod-raw-db] start run_id={run_id}")
        rows, fetched_total = self._load_rows(dataset_key=dataset_key, query=query)
        if not rows:
            raise RuntimeError(f"{dataset_key} 未获取到任何有效记录，拒绝覆盖本地 current/manifest 文件。")

        raw_tmp = self.lake_root / "_tmp" / run_id / raw_layer.path
        raw_final = self.lake_root / raw_layer.path
        manifest_tmp = self.lake_root / "_tmp" / run_id / manifest_layer.path
        manifest_final = self.lake_root / manifest_layer.path
        backup_root = self.lake_root / "_tmp" / run_id / "_backup"

        self.progress(f"[{dataset_key}:prod-raw-db] writing raw rows={len(rows)} output={raw_tmp}")
        raw_written = _write_and_validate(rows=rows, tmp_file=raw_tmp)
        self.progress(f"[{dataset_key}:prod-raw-db] writing manifest rows={len(rows)} output={manifest_tmp}")
        manifest_written = _write_and_validate(rows=rows, tmp_file=manifest_tmp)

        replace_file_atomically(
            tmp_file=raw_tmp,
            final_file=raw_final,
            backup_root=backup_root / "raw_tushare" / dataset_key,
        )
        replace_file_atomically(
            tmp_file=manifest_tmp,
            final_file=manifest_final,
            backup_root=backup_root / "manifest" / dataset_key,
        )

        elapsed = time.monotonic() - started
        summary = {
            "dataset_key": dataset_key,
            "api_name": definition.api_name,
            "source": PROD_RAW_DB_SOURCE,
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "fetched_rows": fetched_total,
            "written_rows": raw_written,
            "raw_output": str(raw_final),
            "manifest_output": str(manifest_final),
            "manifest_written_rows": manifest_written,
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[{dataset_key}:prod-raw-db] done fetched={fetched_total} raw_written={raw_written} "
            f"manifest_written={manifest_written} elapsed={math.ceil(elapsed)}s"
        )
        return summary

    def _load_rows(self, *, dataset_key: str, query) -> tuple[list[dict[str, Any]], int]:
        rows: list[dict[str, Any]] = []
        if dataset_key in _STREAMING_DATASETS:
            fetched_total = 0
            for batch in iter_prod_raw_rows(
                database_url=self.database_url,
                query=query,
                batch_size=20000,
                cursor_name=f"lake_{dataset_key}_prod_raw_cursor",
            ):
                fetched_total += len(batch)
                rows.extend(_normalize_rows(dataset_key=dataset_key, rows=batch))
                self.progress(f"[{dataset_key}:prod-raw-db] fetched_total={fetched_total}")
            rows.sort(key=_sort_key(dataset_key))
            return rows, fetched_total

        source_rows = fetch_prod_raw_rows(database_url=self.database_url, query=query)
        rows = _normalize_rows(dataset_key=dataset_key, rows=source_rows)
        rows.sort(key=_sort_key(dataset_key))
        self.progress(f"[{dataset_key}:prod-raw-db] fetched={len(rows)}")
        return rows, len(source_rows)


def _normalize_rows(*, dataset_key: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    float_fields = set(_FLOAT_FIELDS.get(dataset_key, ()))
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            if value is None or _is_nan(value):
                normalized[key] = None
                continue
            if key in float_fields:
                normalized[key] = float(value)
                continue
            if isinstance(value, Decimal):
                normalized[key] = float(value)
                continue
            normalized[key] = value
        normalized_rows.append(normalized)
    return normalized_rows


def _sort_key(dataset_key: str) -> Callable[[dict[str, Any]], tuple[str, ...]]:
    if dataset_key == "ths_member":
        return lambda row: (str(row.get("ts_code") or ""), str(row.get("con_code") or ""))
    return lambda row: (str(row.get("ts_code") or ""),)


def _require_layer(layers: tuple[LakeLayerDefinition, ...], *, layer: str) -> LakeLayerDefinition:
    for item in layers:
        if item.layer == layer:
            return item
    raise RuntimeError(f"LakeDatasetDefinition 缺少 layer={layer} 定义。")


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _write_and_validate(*, rows: list[dict[str, Any]], tmp_file: Path) -> int:
    written = write_rows_to_parquet(rows, tmp_file)
    validated = read_parquet_row_count(tmp_file)
    if validated != written:
        raise RuntimeError(
            f"prod-raw current Parquet 校验失败：written={written} validated={validated} file={tmp_file}"
        )
    return written


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
