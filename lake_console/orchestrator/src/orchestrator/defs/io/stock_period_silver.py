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


def count_retirement_rows(
    root, freq, codes, *, work, cancel=lambda: False, progress=lambda _: None
):
    """Read only codes from this frequency's existing canonical Silver files."""
    from orchestrator.defs import paths
    from orchestrator.defs.io.stock_period_raw import connection, execute
    from orchestrator.defs.run_contracts.stock_period_silver import (
        period_key,
        target_path,
    )

    if not codes:
        return {}
    path_for = (
        paths.silver_stock_weekly_path
        if freq == "week"
        else paths.silver_stock_monthly_path
    )
    dataset = path_for(root, paths.PATH_TEMPLATE_PARTITION_KEY).parent.parent
    pattern = (
        "week_end=*/part-000.parquet" if freq == "week" else "month=*/part-000.parquet"
    )
    files = {}
    for path in sorted(dataset.glob(pattern)):
        period = path.parent.name.split("=", 1)[1]
        try:
            period_key(period, freq)
        except ValueError:
            continue
        if path == target_path(root, freq, period):
            files[str(path)] = period
    if not files:
        return {}
    with connection(work) as con:
        counts = dict(
            execute(
                con,
                "SELECT filename,count(*) FILTER(WHERE list_contains(?,ts_code)) "
                "FROM read_parquet(?,hive_partitioning=false,filename=true) GROUP BY filename",
                [list(codes), list(files)],
                cancel=cancel,
                progress=progress,
                stage="silver_retirement_code_counts",
            ).fetchall()
        )
    return {period: counts.get(path, 0) for path, period in files.items()}


def assemble_retirement_period(
    con, unit, codes, *, work, cancel=lambda: False, progress=lambda _: None
):
    """Delete approved codes, preserve every other value, and run the original Silver validation."""
    from orchestrator.defs.io.stock_period_raw import (
        execute,
        file_digest,
        storage_record,
        storage_reserve,
    )
    from orchestrator.defs.run_contracts.stock_period_silver import COLUMNS
    from orchestrator.defs.stock_period_silver import (
        assert_schema,
        select_period,
        validate_projection,
    )

    target = safe_path(unit["target"])
    before = file_version(target)
    execute(
        con,
        "CREATE OR REPLACE TEMP TABLE retirement_prior AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
        [str(target)],
        cancel=cancel,
    )
    assert_schema(con, "retirement_prior")
    rows_before, removed = execute(
        con,
        "SELECT count(*),count(*) FILTER(WHERE list_contains(?,ts_code)) FROM retirement_prior",
        [codes],
        cancel=cancel,
    ).fetchone()
    path = target
    if removed:
        path = durable_directory(work) / "candidate.parquet"
        storage_reserve(before[2], spill=True)
        execute(
            con,
            f"COPY (SELECT {COLUMNS} FROM retirement_prior WHERE NOT list_contains(?,ts_code) ORDER BY ts_code) "
            "TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",
            [codes, str(path)],
            cancel=cancel,
            progress=progress,
            stage="silver_retirement_candidate",
        )
        storage_record(path)
    select_period(con, unit["source"], unit["freq"], unit["period"], asof=unit["asof"])
    rows = validate_projection(con, path, unit["freq"], unit["period"])
    execute(
        con,
        f"CREATE OR REPLACE TEMP TABLE retirement_kept AS SELECT {COLUMNS} FROM retirement_prior "
        "WHERE NOT list_contains(?,ts_code)",
        [codes],
        cancel=cancel,
    )
    differences = execute(
        con,
        f"SELECT "
        f"(SELECT count(*) FROM ((SELECT {COLUMNS} FROM retirement_kept) EXCEPT ALL (SELECT {COLUMNS} FROM silver_output)))+"
        f"(SELECT count(*) FROM ((SELECT {COLUMNS} FROM silver_output) EXCEPT ALL (SELECT {COLUMNS} FROM retirement_kept)))",
        cancel=cancel,
    ).fetchone()[0]
    residual = execute(
        con,
        "SELECT count(*) FROM silver_output WHERE list_contains(?,ts_code)",
        [codes],
        cancel=cancel,
    ).fetchone()[0]
    if differences or residual or rows_before - rows != removed:
        raise ValueError("silver_retirement_other_rows_changed")
    record = {
        **unit,
        "target_preimage": before,
        "rows_before": rows_before,
        "removed_rows": removed,
        "rewritten": bool(removed),
        "rows": rows,
        "sha256": file_digest(path),
        "version": before,
    }
    if removed:
        record.update(candidate=str(path), candidate_version=file_version(path))
    return record


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
    # Existing bootstrap and normal updates use this lock; DG serializes retirement cleanup.
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
