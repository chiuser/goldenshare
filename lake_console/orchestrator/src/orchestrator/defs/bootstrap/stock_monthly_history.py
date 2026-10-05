"""Monthly file bootstrap: frozen preflight, annual resume and aggregate readback."""

import shutil
from dataclasses import asdict
from pathlib import Path
from time import monotonic

from orchestrator.defs.bootstrap.stock_monthly_capture import (
    MonthlyCaptureStore,
    build_month_candidates,
)
from orchestrator.defs.bootstrap.stock_monthly_delivery import (
    read_month_bootstrap_delivery,
)
from orchestrator.defs.bootstrap.stock_monthly_files import (
    check_monthly_cancel,
    check_monthly_path,
    check_monthly_root,
    monthly_file_hash,
    monthly_file_lock,
    read_monthly_json,
    write_monthly_json,
)
from orchestrator.defs.bootstrap.stock_monthly_promote import promote_month_candidates
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_monthly_raw import (
    MONTH_SQL,
    canonical_month_hashes,
    load_monthly_parquets,
    validate_month_relation,
)
from orchestrator.defs.paths import raw_stock_monthly_path
from orchestrator.defs.prod_db.stock_monthly import PsqlMonthlyExporter
from orchestrator.defs.run_contracts.stock_monthly import (
    MonthlyBootstrapIOPolicy,
    monthly_contract_hash,
)


def monthly_history_preflight(plan, lake_root, staging_root):
    """Pure read-only preflight; no capture store, mkdir, instance or network."""
    lake_root, staging_root = Path(lake_root), Path(staging_root)
    for root, staging in ((lake_root, False), (staging_root, True)):
        check_monthly_root(root, staging=staging)
    io = MonthlyBootstrapIOPolicy()
    required = 2 * io.prod_csv_max_bytes + io.control_max_bytes + io.duckdb_temp_mb * 1024**2
    if lake_root.stat().st_dev != staging_root.stat().st_dev:
        raise ValueError("monthly_cross_filesystem_forbidden")
    if shutil.disk_usage(staging_root).free < required:
        raise ValueError("monthly_disk_budget_exceeded")
    files = []
    for month in plan.months:
        path = raw_stock_monthly_path(lake_root, plan.source, month)
        check_monthly_path(path)
        files.append({"month": month, "path": str(path), "sha256": monthly_file_hash(path, max_bytes=io.prod_csv_max_bytes) if path.exists() else None})
    body = {
        "kind": "monthly_history_preflight", "version": 1,
        "plan_hash": plan.plan_hash, "io_policy": asdict(io),
        "lake_root": str(lake_root), "staging_root": str(staging_root),
        "source": plan.source.value, "files": files,
        "counts": {"source_rows": plan.source_rows, "excluded_rows": plan.excluded_rows,
                   "accepted_rows": plan.accepted_rows, "units": len(plan.units),
                   "years": len(plan.inventories), "files": len(files)},
        "required_staging_bytes": required,
    }
    return {**body, "preflight_hash": monthly_contract_hash(body)}


def _execution_index(store):
    path = store.root / "history_execution.json"
    identity = {"version": 1, "plan_hash": store.plan.plan_hash, "io_hash": store.io_hash}
    index = read_monthly_json(path, store.io_policy.control_max_bytes) if path.exists() else {**identity, "years": {}}
    if any(index.get(k) != v for k, v in identity.items()) or not set(index["years"]).issubset({str(i.year) for i in store.plan.inventories}):
        raise ValueError("monthly_execution_identity_invalid")
    return path, index


def _read_assembly(store, reference):
    path = Path(reference["path"])
    check_monthly_path(path)
    if not path.is_relative_to(store.root / "assemblies") or monthly_file_hash(path, max_bytes=store.io_policy.control_max_bytes) != reference["sha256"]:
        raise ValueError("monthly_execution_audit_changed")
    return path, read_monthly_json(path, store.io_policy.control_max_bytes)


def execute_monthly_history(plan, preflight, *, exporter=None, cancel=lambda: False, progress=lambda event: None):
    """Explicit APPLY only; receipts and annual assembly references survive cancellation."""
    check_monthly_cancel(cancel)
    root, stage = Path(preflight["lake_root"]), Path(preflight["staging_root"])
    actual = monthly_history_preflight(plan, root, stage)
    # Target bytes may differ on a resumed run only if owned by its committed checkpoint.
    if {k: v for k, v in actual.items() if k not in ("files", "preflight_hash")} != {k: v for k, v in preflight.items() if k not in ("files", "preflight_hash")}:
        raise ValueError("monthly_preflight_identity_changed")
    body = {k: v for k, v in preflight.items() if k != "preflight_hash"}
    if monthly_contract_hash(body) != preflight.get("preflight_hash"):
        raise ValueError("monthly_preflight_hash_invalid")
    if [(r["month"], r["path"]) for r in actual["files"]] != [(r["month"], r["path"]) for r in preflight["files"]]:
        raise ValueError("monthly_preflight_scope_changed")
    store = MonthlyCaptureStore(plan, stage)
    exporter = exporter if exporter is not None else PsqlMonthlyExporter()
    with monthly_file_lock(store.root / "history_writer.lock"):
        index_path, index = _execution_index(store)
        owned = {}
        for reference in index["years"].values():
            path, audit = _read_assembly(store, reference)
            checkpoint = path.parent / "promoted.json"
            if checkpoint.exists():
                saved = read_monthly_json(checkpoint, store.io_policy.control_max_bytes)
                if saved.get("audit_hash") != reference["sha256"]:
                    raise ValueError("monthly_execution_checkpoint_changed")
                expected = {r["month"]: r for r in audit["records"]}
                for month, record in saved["completed"].items():
                    if month not in expected or record["rows"] != expected[month]["rows"]:
                        raise ValueError("monthly_execution_checkpoint_changed")
                    owned[month] = record["sha256"]
            # An interrupted rename precedes checkpoint; the sealed candidate hash is sufficient.
            for record in audit["records"]:
                if record["month"] in owned:
                    continue
                owned[record["month"]] = record["sha256"]
        for now, before in zip(actual["files"], preflight["files"], strict=True):
            if now["sha256"] != before["sha256"] and (
                now["month"] not in owned or now["sha256"] != owned[now["month"]]
            ):
                raise ValueError("monthly_preflight_target_changed")
        total = len(plan.units)
        completed = 0
        for inventory in plan.inventories:
            year = str(inventory.year)
            check_monthly_cancel(cancel)
            for unit in plan.units:
                if unit.source_date_start[:4] != year:
                    continue
                check_monthly_cancel(cancel)
                store.capture_unit(unit, exporter, cancel=cancel, progress=progress)
                completed += 1
                progress({"phase": "history_capture", "year": inventory.year,
                          "completed_units": completed, "total_units": total})
            if year not in index["years"]:
                path, digest = build_month_candidates(store, inventory.year, root, cancel=cancel)
                index["years"][year] = {"path": str(path), "sha256": digest}
                write_monthly_json(index_path, index, store.io_policy.control_max_bytes)
            path, _audit = _read_assembly(store, index["years"][year])
            promote_month_candidates(store, path, index["years"][year]["sha256"], cancel=cancel, progress=progress)
            progress({"phase": "history_year_committed", "year": inventory.year})
        return audit_monthly_history(plan, root, stage, cancel=cancel)


def audit_monthly_history(plan, lake_root, staging_root, *, cancel=lambda: False):
    """Read-only yearly sets replicate all three formal checks; no capture store construction."""
    started = monotonic()
    root, stage = Path(lake_root), Path(staging_root)
    check_monthly_root(root, staging=False)
    check_monthly_root(stage, staging=True)
    io = MonthlyBootstrapIOPolicy()
    base = stage / "stock_monthly_raw" / plan.plan_hash / monthly_contract_hash(asdict(io))
    check_monthly_path(base)
    index = read_monthly_json(base / "history_execution.json", io.control_max_bytes)
    if index.get("plan_hash") != plan.plan_hash or index.get("io_hash") != monthly_contract_hash(asdict(io)) or set(index["years"]) != {str(i.year) for i in plan.inventories}:
        raise ValueError("monthly_history_not_complete")
    entries = []
    settings = DuckDBConnectionSettings(temp_directory=stage, memory_limit=f"{io.duckdb_memory_mb}MB", threads=io.duckdb_threads, max_temp_directory_size=f"{io.duckdb_temp_mb}MB")
    sql_calls = 0
    for inventory in plan.inventories:
        check_monthly_cancel(cancel)
        reference = index["years"][str(inventory.year)]
        path = Path(reference["path"])
        check_monthly_path(path)
        if not path.is_relative_to(base / "assemblies") or monthly_file_hash(path, max_bytes=io.control_max_bytes) != reference["sha256"]:
            raise ValueError("monthly_execution_audit_changed")
        audit = read_monthly_json(path, io.control_max_bytes)
        if audit.get("plan_hash") != plan.plan_hash or audit.get("io_hash") != index["io_hash"] or audit.get("year") != inventory.year or audit.get("captured_rows") != inventory.source_rows or audit.get("excluded_rows") != inventory.excluded_rows:
            raise ValueError("monthly_history_inventory_mismatch")
        if monthly_file_hash(path.parent / "excluded_month_version.parquet", max_bytes=io.prod_csv_max_bytes) != audit["excluded_sha256"]:
            raise ValueError("monthly_history_exclusion_changed")
        files = [raw_stock_monthly_path(root, plan.source, r["month"]) for r in audit["records"]]
        with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as con:
            con = _CountedConnection(con)
            con.execute("SET autoload_known_extensions=false")
            con.execute("SET autoinstall_known_extensions=false")
            load_monthly_parquets(con, "monthly_candidate", files, plan.source)
            rows = validate_month_relation(con, "monthly_candidate", plan.source, plan.policy, max_rows=plan.policy.max_year_rows)
            expected = {r["month"]: {"rows": r["rows"], "logical_hash": r["logical_hash"]} for r in audit["records"]}
            if len(expected) != len(files) or rows != inventory.source_rows - inventory.excluded_rows or canonical_month_hashes(con, "monthly_candidate", plan.source) != expected:
                raise ValueError("monthly_history_formal_difference")
            placement = con.execute(f"SELECT filename,min({MONTH_SQL}),max({MONTH_SQL}),count(*) FROM read_parquet(?,hive_partitioning=false,filename=true) GROUP BY filename", [[str(p) for p in files]]).fetchall()
            if {p: (lo, hi, n) for p, lo, hi, n in placement} != {str(p): (r["month"], r["month"], r["rows"]) for p, r in zip(files, audit["records"], strict=True)}:
                raise ValueError("monthly_history_placement_invalid")
            sql_calls += con.calls
        for record, target in zip(audit["records"], files, strict=True):
            check_monthly_cancel(cancel)
            delivery = {"delivery_method": "prod_month_bootstrap", "source": plan.source.value,
                        "month": record["month"], "path": str(target), "rows": record["rows"],
                        "audit_path": str(path), "audit_hash": reference["sha256"]}
            read_month_bootstrap_delivery(delivery, root, plan.source, record["month"])
            entries.append({**delivery, "sha256": monthly_file_hash(target, max_bytes=io.prod_csv_max_bytes), "logical_hash": record["logical_hash"]})
    if tuple(sorted(e["month"] for e in entries)) != plan.months or sum(e["rows"] for e in entries) != plan.accepted_rows:
        raise ValueError("monthly_history_scope_difference")
    return {"kind": "monthly_history_file_audit", "version": 1, "plan_hash": plan.plan_hash,
            "source": plan.source.value, "files": len(entries), "rows": plan.accepted_rows,
            "source_rows": plan.source_rows, "excluded_rows": plan.excluded_rows,
            "year_scans": len(plan.inventories), "sql_calls": sql_calls,
            "elapsed_seconds": round(monotonic() - started, 3), "entries": entries}


class _CountedConnection:
    def __init__(self, connection):
        self.connection = connection
        self.calls = 0

    def execute(self, *args, **kwargs):
        self.calls += 1
        return self.connection.execute(*args, **kwargs)
