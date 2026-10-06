"""Read-only, bounded physical proof for weekly runless event plans."""

import json
import tempfile
import time
from pathlib import Path

from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    fingerprint,
    partition_path,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    check_capture_path,
)
from orchestrator.defs.bootstrap.stock_weekly_promote import read_audit
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_weekly_raw import (
    WEEK_SQL,
    load_relation,
    relation_hashes,
    validate_relation,
)
from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.stock_weekly import StockWeeklySource, WeeklyBudget


def verify_weekly_delivery_evidence(audit, budget=None):
    """Verify the same sealed source receipts once per bounded annual audit."""
    budget = budget or WeeklyBudget()
    if len(audit["source_evidence"]) > budget.max_phase_files:
        raise WeeklyCaptureError("delivery_evidence_budget_exceeded")
    control_count = 0
    receipts = 0
    for item in audit["source_evidence"]:
        reference = Path(item["path"])
        if fingerprint(reference) != item["sha256"]:
            raise WeeklyCaptureError("delivery_evidence_changed")
        if reference.name == "receipt.json":
            if reference.stat().st_size > 1024 * 1024:
                raise WeeklyCaptureError("delivery_receipt_budget_exceeded")
            receipt = json.loads(reference.read_text())
            if (
                receipt["status"] not in ("captured", "success_empty")
                or receipt["schema_hash"] != audit["schema_hash"]
            ):
                raise WeeklyCaptureError("delivery_receipt_invalid")
            control_count += receipt["source_rows"]
            receipts += 1
    if not receipts or control_count != audit["stats"]["source_rows"]:
        raise WeeklyCaptureError("delivery_control_count_mismatch")


def audit_weekly_event_files(references, *, metrics=None):
    """Only explicitly supplied sealed audits; never discover or expand scope."""
    budget = WeeklyBudget()
    started = time.monotonic()
    metrics = {} if metrics is None else metrics
    metrics.update(
        {"duckdb_connections": 0, "sql_calls": 0, "source_evidence_files": 0}
    )
    if not references or len(references) > 3 * 54:
        raise WeeklyCaptureError("event_audit_budget_exceeded")
    settings = DuckDBConnectionSettings(
        temp_directory=Path(tempfile.gettempdir()).resolve(),
        memory_limit=budget.duckdb_memory_limit,
        threads=budget.duckdb_threads,
        max_temp_directory_size=budget.duckdb_max_temp,
    )
    entries, seen, years = [], set(), set()
    for reference in references:
        path = Path(reference["path"])
        check_capture_path(path)
        if not any(
            path.is_relative_to(root)
            for root in (
                Path(DEFAULT_LAKE_STAGING_ROOT),
                Path("/private/tmp"),
                settings.temp_directory,
            )
        ):
            raise WeeklyCaptureError("delivery_path_forbidden")
        if fingerprint(path) != reference["sha256"]:
            raise WeeklyCaptureError("event_audit_changed")
        audit = read_audit(path)
        source = StockWeeklySource(audit["source"])
        root = Path(audit["target_root"])
        year_key = (source.value, audit["year"])
        if year_key in years or not audit["files"]:
            raise WeeklyCaptureError("event_audit_year_duplicate_or_empty")
        years.add(year_key)
        verify_weekly_delivery_evidence(audit, budget)
        metrics["source_evidence_files"] += len(audit["source_evidence"])
        files = audit["files"]
        paths = [Path(f["target"]) for f in files]
        for item, target in zip(files, paths, strict=True):
            key = (source.value, item["week"])
            if (
                key in seen
                or target != partition_path(root, source, item["week"])
                or fingerprint(target) != item["sha256"]
            ):
                raise WeeklyCaptureError("event_formal_identity_mismatch")
            seen.add(key)
        with connect_configured_duckdb(
            settings, temp_policy="existing_no_spill"
        ) as con:
            metrics["duckdb_connections"] += 1
            con = _CountedConnection(con, metrics)
            load_relation(con, "event_files", paths, source)
            validate_relation(con, "event_files", source, budget, unique=True)
            hashes = relation_hashes(con, "event_files", source, budget)
            # Verify physical placement, not merely the pooled set of weekly rows.
            placement = con.execute(
                f"SELECT filename,min({WEEK_SQL}),max({WEEK_SQL}) FROM "
                "read_parquet(?,hive_partitioning=false,union_by_name=false,filename=true) "
                "GROUP BY filename",
                [[str(p) for p in paths]],
            ).fetchall()
            expected = {f["target"]: (f["week"], f["week"]) for f in files}
            if {name: (lo, hi) for name, lo, hi in placement} != expected:
                raise WeeklyCaptureError("formal_week_mismatch")
            if hashes != {
                f["week"]: {"rows": f["rows"], "logical_hash": f["logical_hash"]}
                for f in files
            }:
                raise WeeklyCaptureError("delivery_hash_mismatch")
        for item in files:
            entries.append(
                {
                    "source": source.value,
                    "week": item["week"],
                    "path": item["target"],
                    "sha256": item["sha256"],
                    "logical_hash": item["logical_hash"],
                    "rows": item["rows"],
                    "audit_path": str(path),
                    "audit_hash": audit["audit_hash"],
                    "audit_sha256": reference["sha256"],
                }
            )
        if len(entries) * 4 > budget.event_write_cap:
            raise WeeklyCaptureError("event_write_budget_exceeded")
    metrics.update(
        {
            "formal_files": len(entries),
            "annual_audits": len(references),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    )
    return sorted(entries, key=lambda e: (e["source"], e["week"]))


class _CountedConnection:
    def __init__(self, connection, metrics):
        self.connection = connection
        self.metrics = metrics

    def execute(self, *args, **kwargs):
        self.metrics["sql_calls"] += 1
        return self.connection.execute(*args, **kwargs)
