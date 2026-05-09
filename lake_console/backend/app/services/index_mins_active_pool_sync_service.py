from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.lake_root_service import LakeRootService
from lake_console.backend.app.services.manifest_service import ManifestService
from lake_console.backend.app.services.parquet_writer import (
    read_parquet_row_count,
    replace_file_atomically,
    write_rows_to_parquet,
)
from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


INDEX_MINS_ACTIVE_POOL_RESOURCE = "index_mins"
INDEX_MINS_ACTIVE_POOL_MANIFEST = Path("manifest") / "index_universe" / "index_mins_active_pool.parquet"


class IndexMinsActivePoolConfigError(RuntimeError):
    pass


class IndexMinsActivePoolSyncService:
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

    def sync(self) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        run_id = _run_id("index-mins-active-pool")
        LakeRootService(self.lake_root).require_ready_for_write()
        self.progress(f"[index_mins_active_pool] start run_id={run_id}")

        rows = _fetch_active_pool_rows(database_url=self.database_url)
        if not rows:
            raise RuntimeError("index_mins active pool 为空，拒绝覆盖本地 manifest。")

        tmp_file = self.lake_root / "_tmp" / run_id / INDEX_MINS_ACTIVE_POOL_MANIFEST
        final_file = self.lake_root / INDEX_MINS_ACTIVE_POOL_MANIFEST
        backup_root = self.lake_root / "_tmp" / run_id / "_backup" / "index_mins_active_pool"

        written = _write_and_validate(rows=rows, tmp_file=tmp_file)
        replace_file_atomically(tmp_file=tmp_file, final_file=final_file, backup_root=backup_root)

        elapsed = time.monotonic() - started
        summary = {
            "operation": "sync_index_mins_active_pool",
            "resource": INDEX_MINS_ACTIVE_POOL_RESOURCE,
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "written_rows": written,
            "output": str(final_file),
            "elapsed_seconds": round(elapsed, 3),
        }
        ManifestService(self.lake_root).append_sync_run(summary)
        TmpCleanupService(self.lake_root).cleanup_run_if_empty(run_id)
        self.progress(
            f"[index_mins_active_pool] done written={written} output={final_file} elapsed={math.ceil(elapsed)}s"
        )
        return summary


def _fetch_active_pool_rows(*, database_url: str | None) -> list[dict[str, Any]]:
    if not database_url:
        raise IndexMinsActivePoolConfigError(
            "缺少可用的生产数据库连接。请配置 GOLDENSHARE_PROD_RAW_DB_URL，或在缺省时提供 prod_core_db_url 作为只读连接。"
        )
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise IndexMinsActivePoolConfigError("缺少 psycopg，请先安装 lake_console/backend/requirements.txt。") from exc

    sql = (
        "select resource, ts_code "
        "from ops.index_series_active "
        "where resource = %s "
        "order by ts_code"
    )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("set transaction read only")
            with connection.cursor() as cursor:
                cursor.execute(sql, (INDEX_MINS_ACTIVE_POOL_RESOURCE,))
                raw_rows = [dict(row) for row in cursor.fetchall()]

    seen_codes: set[str] = set()
    rows: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        ts_code = str(raw_row.get("ts_code") or "").strip().upper()
        resource = str(raw_row.get("resource") or "").strip()
        if not ts_code:
            raise RuntimeError("index_mins active pool 返回了空 ts_code。")
        if resource != INDEX_MINS_ACTIVE_POOL_RESOURCE:
            raise RuntimeError(f"index_mins active pool 返回了意外 resource={resource!r}")
        if ts_code in seen_codes:
            raise RuntimeError(f"index_mins active pool ts_code 重复：{ts_code}")
        seen_codes.add(ts_code)
        rows.append(
            {
                "resource": INDEX_MINS_ACTIVE_POOL_RESOURCE,
                "ts_code": ts_code,
            }
        )
    return rows


def _write_and_validate(*, rows: list[dict[str, Any]], tmp_file: Path) -> int:
    written = write_rows_to_parquet(rows, tmp_file)
    validated = read_parquet_row_count(tmp_file)
    if validated != written:
        raise RuntimeError(
            f"index_mins active pool Parquet 校验失败：written={written} validated={validated} file={tmp_file}"
        )
    return written


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
