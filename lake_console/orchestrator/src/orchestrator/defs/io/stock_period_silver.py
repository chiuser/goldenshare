"""Silver-only writer boundary and durable per-period rename recovery."""

import fcntl
import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from orchestrator.defs.io.stock_period_raw import (
    atomic_json,
    durable_directory,
    file_version,
    safe_path,
    sync_directory,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.stock_period_silver import canonical_run_id


def read_json(path):
    return json.loads(safe_path(path).read_text())


def run_directory(staging, run_id):
    return safe_path(
        Path(staging) / "stock_period_silver" / f"run_id={canonical_run_id(run_id)}"
    )


def validate_roots(lake, staging):
    lake, staging = safe_path(lake), safe_path(staging)
    if lake == staging or lake in staging.parents or staging in lake.parents:
        raise ValueError("silver_roots_overlap")
    if "goldenshare-tushare-lake" in (*lake.parts, *staging.parts):
        raise ValueError("silver_retired_root")
    if (str(lake) == DEFAULT_LAKE_ROOT) != (str(staging) == DEFAULT_LAKE_STAGING_ROOT):
        raise ValueError("silver_formal_roots_must_pair")
    if not lake.is_dir() or not staging.is_dir():
        raise ValueError("silver_roots_unavailable")
    if lake.stat().st_dev != staging.stat().st_dev:
        raise ValueError("silver_cross_device")
    # A directory on the startup disk at the formal path is not a mounted Lake.
    if (
        str(lake) == "/Volumes/datasource/data_lake"
        and not Path("/Volumes/datasource").is_mount()
    ):
        raise ValueError("silver_mount_missing")
    return lake, staging


@contextmanager
def writer_lock(staging):
    # Kept outside the datasets; every Silver writer uses the same independent lock.
    path = safe_path(
        durable_directory(Path(staging) / "stock_period_silver") / "writer.lock"
    )
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("silver_writer_active") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def identity_after_rename(version):
    # rename can change ctime; device/inode/size/mtime identify this exact candidate.
    return version[:4]


def recover_committed(record, checkpoint, *, con=None):
    """Recognize a durable rename before consulting the possibly newer Raw input."""
    target = safe_path(record["target"])
    if record["state"] == "committed":
        if not target.exists() or file_version(target) != record["version"]:
            raise ValueError("silver_committed_target_changed")
        return record
    if record["state"] != "validated":
        raise ValueError("silver_candidate_not_validated")
    candidate = safe_path(record["candidate"])
    if candidate.exists():
        if file_version(candidate) != record["candidate_version"]:
            raise ValueError("silver_candidate_changed")
        if (file_version(target) if target.exists() else None) != record.get(
            "target_preimage"
        ):
            raise ValueError("silver_target_preimage_changed")
        return None
    if not target.exists() or identity_after_rename(
        file_version(target)
    ) != identity_after_rename(record["candidate_version"]):
        raise ValueError("silver_unknown_target")
    if con is None:
        from orchestrator.defs.duckdb_connection import (
            DuckDBConnectionSettings,
            connect_configured_duckdb,
        )

        with connect_configured_duckdb(
            DuckDBConnectionSettings(temp_directory=checkpoint.parent / "spill")
        ) as connection:
            return recover_committed(record, checkpoint, con=connection)
    rows = con.execute(
        "SELECT num_rows FROM parquet_file_metadata(?)", [str(target)]
    ).fetchone()[0]
    if rows != record["rows"]:
        raise ValueError("silver_published_footer_mismatch")
    sync_directory(target.parent)
    result = {**record, "state": "committed", "version": file_version(target)}
    atomic_json(checkpoint, result)
    return result


def publish(record, checkpoint, *, con, cancel=lambda: False):
    from orchestrator.defs.stock_period_silver import check_cancel

    began = time.monotonic()
    target = safe_path(record["target"])
    committed = recover_committed(record, checkpoint, con=con)
    if committed is not None:
        return committed
    source = safe_path(record["candidate"])
    if file_version(record["source"]) != record["source_version"]:
        raise ValueError("silver_source_changed")
    if record["state"] != "validated":
        raise ValueError("silver_candidate_not_validated")
    if source.exists():
        if file_version(source) != record["candidate_version"]:
            raise ValueError("silver_candidate_changed")
        current = file_version(target) if target.exists() else None
        if current != record.get("target_preimage"):
            raise ValueError(
                "silver_target_preimage_changed"
                if "target_preimage" in record
                else "silver_unknown_target"
            )
        check_cancel(cancel)
        durable_directory(target.parent)
        if source.stat().st_dev != target.parent.stat().st_dev:
            raise ValueError("silver_cross_device")
        if shutil.disk_usage(target.parent).free <= source.stat().st_size:
            raise ValueError("silver_space_insufficient")
        os.replace(source, target)
        sync_directory(target.parent)
    elif not target.exists() or identity_after_rename(
        file_version(target)
    ) != identity_after_rename(record["candidate_version"]):
        raise ValueError("silver_unknown_target")
    if identity_after_rename(file_version(target)) != identity_after_rename(
        record["candidate_version"]
    ):
        raise ValueError("silver_rename_identity_mismatch")
    rows = con.execute(
        "SELECT num_rows FROM parquet_file_metadata(?)", [str(target)]
    ).fetchone()[0]
    if rows != record["rows"]:
        raise ValueError("silver_published_footer_mismatch")
    result = {
        **record,
        "state": "committed",
        "version": file_version(target),
        "publish_seconds": time.monotonic() - began,
    }
    atomic_json(checkpoint, result)
    return result
