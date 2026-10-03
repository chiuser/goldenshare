"""Freeze bounded annual candidates and physical evidence; no promotion."""

from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    WeeklyCaptureStore,
    _atomic_json,
    _sync_directory,
    capture_file_hash,
    check_capture_path,
    check_weekly_cancel,
    verify_weekly_plan_evidence,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_weekly_raw import (
    WEEK_SQL,
    assemble_relation,
    load_relation,
    write_and_audit_candidates,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyUnit,
    normalize_week_key,
    stable_weekly_hash,
    weekly_dataset_id,
    weekly_schema_hash,
)


def validate_root(root: Path, *, staging: bool):
    check_capture_path(root)
    canonical = Path(DEFAULT_LAKE_STAGING_ROOT if staging else DEFAULT_LAKE_ROOT)
    temporary = (Path(tempfile.gettempdir()).resolve(), Path("/private/tmp"))
    if root != canonical and not any(root.is_relative_to(p) for p in temporary):
        raise WeeklyCaptureError("weekly_root_forbidden")


def partition_path(root, source, week):
    normalize_week_key(week)
    result = (
        root
        / "raw"
        / "tushare"
        / weekly_dataset_id(source)
        / f"week_end={week}"
        / "part-000.parquet"
    )
    check_capture_path(result)
    return result


def fingerprint(path):
    check_capture_path(path)
    return capture_file_hash(path) if path.exists() else None


def year_window(year):
    start = date(year, 1, 1)
    first = start + timedelta(days=(4 - start.weekday()) % 7)
    end = date(year, 12, 31)
    last = end - timedelta(days=(end.weekday() - 4) % 7)
    return first - timedelta(days=4), last + timedelta(days=3)


def unit_window(unit):
    if isinstance(unit, ProdWeeklyUnit):
        return unit.source_date_start, unit.source_date_end
    return unit.request_start, unit.request_end + timedelta(days=1)


def audit_expected_source_keys(connection, manifest, units, assembly, year):
    """Verify frozen logical keys and persist per-key outcomes outside JSON."""
    path = Path(manifest.evidence_ref)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[6] / path
    if path.suffix == ".parquet":
        reader = "read_parquet(?, hive_partitioning=false)"
    else:
        reader = "read_csv(?, header=true, all_varchar=true)"
    count = connection.execute(
        f"SELECT count(*) FROM {reader}", [str(path)]
    ).fetchone()[0]
    if count > manifest.budget.max_candidate_keys:
        raise WeeklyCaptureError("expected_key_budget_exceeded")
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE weekly_expected_inventory AS SELECT DISTINCT ts_code, week_key FROM {reader}",
        [str(path)],
    )
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE weekly_expected_selected(ts_code VARCHAR, week_key VARCHAR)"
    )
    for unit in units:
        keys = [
            r[0]
            for r in connection.execute(
                "SELECT week_key FROM weekly_expected_inventory WHERE ts_code=? AND week_key BETWEEN ? AND ? ORDER BY week_key LIMIT 55",
                [unit.ts_code, unit.anchor_start, unit.anchor_end],
            ).fetchall()
        ]
        if (
            len(keys) != unit.expected_key_count
            or stable_weekly_hash(keys) != unit.expected_key_hash
        ):
            raise WeeklyCaptureError("expected_key_identity_mismatch")
        connection.executemany(
            "INSERT INTO weekly_expected_selected VALUES (?,?)",
            [(unit.ts_code, k) for k in keys],
        )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE weekly_key_outcomes AS SELECT e.ts_code, e.week_key, CASE WHEN p.ts_code IS NULL THEN 'source_key_absent_confirmed' ELSE 'source_key_present' END AS status FROM weekly_expected_selected e LEFT JOIN (SELECT DISTINCT ts_code, {WEEK_SQL} AS week_key FROM weekly_unique) p USING(ts_code,week_key) WHERE substr(e.week_key,1,4)=?",
        [str(year)],
    )
    path = assembly / "source-key-outcomes.parquet"
    connection.execute(
        "COPY weekly_key_outcomes TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(path)]
    )
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
    counts = dict(
        connection.execute(
            "SELECT status,count(*) FROM weekly_key_outcomes GROUP BY status"
        ).fetchall()
    )
    return {"path": str(path), "sha256": capture_file_hash(path), "counts": counts}


def build_weekly_partition_candidates(
    manifest,
    *,
    capture_root,
    target_root,
    year,
    excluded_week_keys=(),
    partial_scope=False,
    cancel=lambda: False,
    progress=lambda payload: None,
):
    """partial_scope permits isolated, explicitly incomplete inventories only.

    It is recorded in the audit; this never asserts global historical coverage.
    Missing receipts for planned intersecting units always fail.
    """
    validate_root(capture_root, staging=True)
    validate_root(target_root, staging=False)
    if (
        capture_root == target_root
        or capture_root.is_relative_to(target_root)
        or target_root.is_relative_to(capture_root)
    ):
        raise WeeklyCaptureError("weekly_roots_overlap")
    if partial_scope and target_root == Path(DEFAULT_LAKE_ROOT):
        raise WeeklyCaptureError("partial_scope_formal_forbidden")
    verify_weekly_plan_evidence(manifest)
    start, end = year_window(year)
    units = [
        u
        for u in manifest.units
        if unit_window(u)[0] < end and unit_window(u)[1] > start
    ]
    if not units:
        raise WeeklyCaptureError("year_inventory_missing")
    # Adjacent calendar-year units must be included when the scope is full.
    if not partial_scope and isinstance(units[0], ProdWeeklyUnit):
        intervals = sorted({unit_window(u) for u in units})
        cursor = start
        for lo, hi in intervals:
            if lo > cursor:
                break
            cursor = max(cursor, hi)
        if cursor < end:
            raise WeeklyCaptureError("year_boundary_inventory_missing")
    exclusions = tuple(sorted({normalize_week_key(w) for w in excluded_week_keys}))
    if exclusions and manifest.source.value != "weekly":
        raise WeeklyCaptureError("primary_exclusion_forbidden")
    if any(w[:4] != str(year) for w in exclusions):
        raise WeeklyCaptureError("exclusion_year_mismatch")
    budget = manifest.budget
    store = WeeklyCaptureStore(capture_root, manifest)
    assembly = store.root / "assemblies" / f"{year}-{uuid.uuid4().hex}"
    check_capture_path(assembly)
    assembly.mkdir(parents=True)
    settings = DuckDBConnectionSettings(
        temp_directory=assembly / "spill",
        memory_limit=budget.duckdb_memory_limit,
        threads=budget.duckdb_threads,
        max_temp_directory_size=budget.duckdb_max_temp,
    )
    with store.locked(), connect_configured_duckdb(settings) as connection:
        connection.execute("SET autoinstall_known_extensions=false")
        connection.execute("SET autoload_known_extensions=false")
        repo = Path(__file__).resolve().parents[6]
        proof = Path(manifest.evidence_ref)
        if not proof.is_absolute():
            proof = repo / proof
        evidence = [{"path": str(proof), "sha256": manifest.evidence_hash}]
        evidence.append(
            {
                "path": str(store.root / "plan.json"),
                "sha256": capture_file_hash(store.root / "plan.json"),
            }
        )
        inputs = []
        for unit in units:
            check_weekly_cancel(cancel)
            receipt_path, receipt = store.validated_receipt(connection, unit)
            evidence.append(
                {"path": str(receipt_path), "sha256": capture_file_hash(receipt_path)}
            )
            for reference, digest in getattr(unit, "source_evidence", ()):
                proof_path = Path(reference)
                if not proof_path.is_absolute():
                    proof_path = repo / proof_path
                evidence.append({"path": str(proof_path), "sha256": digest})
            directory = receipt_path.parent
            for chunk in receipt["chunks"]:
                path = directory / chunk["path"]
                inputs.append(path)
                evidence.append({"path": str(path), "sha256": chunk["sha256"]})
        if len(inputs) > budget.max_phase_files:
            raise WeeklyCaptureError("assembly_file_budget_exceeded")
        source_count = (
            connection.execute(
                "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)",
                [[str(p) for p in inputs]],
            ).fetchone()[0]
            if inputs
            else 0
        )
        if source_count > budget.max_phase_rows:
            raise WeeklyCaptureError("raw_row_budget_exceeded")
        load_relation(connection, "weekly_input", inputs, manifest.source)
        parent = target_root / "raw" / "tushare" / weekly_dataset_id(manifest.source)
        check_capture_path(parent)
        existing = sorted(parent.glob(f"week_end={year}-*/*.parquet"))
        if len(existing) + len(inputs) > budget.max_phase_files:
            raise WeeklyCaptureError("assembly_file_budget_exceeded")
        baselines = {}
        for path in existing:
            week = path.parent.name.removeprefix("week_end=")
            expected = partition_path(target_root, manifest.source, week)
            if path != expected:
                raise WeeklyCaptureError("target_layout_mismatch")
            baselines[week] = fingerprint(path)
            if connection.execute(
                f"SELECT count(*) FROM read_parquet(?,hive_partitioning=false) WHERE {WEEK_SQL}<>?",
                [str(path), week],
            ).fetchone()[0]:
                raise WeeklyCaptureError("target_partition_mismatch")
        existing_count = (
            connection.execute(
                "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)",
                [[str(p) for p in existing]],
            ).fetchone()[0]
            if existing
            else 0
        )
        if source_count + existing_count > budget.max_phase_rows:
            raise WeeklyCaptureError("raw_row_budget_exceeded")
        load_relation(connection, "weekly_existing", existing, manifest.source)
        progress(
            {
                "stage": "merge",
                "year": year,
                "source_files": len(inputs),
                "existing_files": len(existing),
            }
        )
        check_weekly_cancel(cancel)
        stats = assemble_relation(connection, manifest.source, year, budget, exclusions)
        key_outcomes = (
            audit_expected_source_keys(connection, manifest, units, assembly, year)
            if manifest.source.value == "weekly"
            else None
        )
        expected, paths = write_and_audit_candidates(
            connection, manifest.source, budget, assembly / "candidate"
        )
        files = []
        for path in paths:
            check_weekly_cancel(cancel)
            week = path.parent.name.removeprefix("week_end=")
            target = partition_path(target_root, manifest.source, week)
            baseline = baselines.get(week)
            if fingerprint(target) != baseline:
                raise WeeklyCaptureError("target_changed_during_assembly")
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
            _sync_directory(path.parent)
            files.append(
                {
                    "week": week,
                    "candidate": str(path),
                    "target": str(target),
                    "baseline": baseline,
                    "sha256": capture_file_hash(path),
                    **expected[week],
                }
            )
        if paths:
            _sync_directory(assembly / "candidate")
        for item in evidence:
            if fingerprint(Path(item["path"])) != item["sha256"]:
                raise WeeklyCaptureError("source_changed_during_assembly")
        payload = {
            "version": 1,
            "plan_hash": manifest.plan_hash,
            "source": manifest.source.value,
            "schema_hash": weekly_schema_hash(manifest.source),
            "year": year,
            "capture_root": str(capture_root),
            "target_root": str(target_root),
            "assembly": str(assembly),
            "partial_scope": partial_scope,
            "excluded_week_keys": exclusions,
            "budget": asdict(budget),
            "source_evidence": evidence,
            "files": files,
            "stats": stats,
            "value_difference_rows": 0,
            "source_key_outcomes": key_outcomes,
        }
        payload["manifest_hash"] = stable_weekly_hash(asdict(manifest))
        payload["candidate_manifest_hash"] = stable_weekly_hash(files)
        payload["target_baseline_hash"] = stable_weekly_hash(
            [(f["target"], f["baseline"]) for f in files]
        )
        payload["source_evidence_hash"] = stable_weekly_hash(evidence)
        payload["audit_hash"] = stable_weekly_hash(payload)
        _atomic_json(assembly / "audit.json", payload)
        progress(
            {
                "stage": "audited",
                "year": year,
                "files": len(files),
                "rows": stats["candidate_rows"],
            }
        )
        return assembly / "audit.json"
