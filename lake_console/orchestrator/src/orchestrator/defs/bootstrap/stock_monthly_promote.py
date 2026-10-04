"""Audited month files: per-target mutual exclusion, atomic install and recovery."""

from __future__ import annotations

import os
from pathlib import Path

from orchestrator.defs.bootstrap.stock_monthly_capture import monthly_target_path
from orchestrator.defs.bootstrap.stock_monthly_files import (
    check_monthly_cancel,
    check_monthly_free_space,
    check_monthly_path,
    check_monthly_root,
    monthly_file_hash,
    monthly_file_lock,
    read_monthly_json,
    sync_monthly_directory,
    write_monthly_json,
)
from orchestrator.defs.io.stock_monthly_raw import (
    canonical_month_hashes,
    load_monthly_parquets,
    validate_month_relation,
)


def promote_month_candidates(
    store,
    audit_path: Path,
    audit_hash: str,
    *,
    cancel=lambda: False,
    progress=lambda event: None,
):
    check_monthly_cancel(cancel)
    store.verify_plan()
    check_monthly_free_space(
        store.root,
        store.io_policy.duckdb_temp_mb * 1024 * 1024
        + store.io_policy.control_max_bytes,
    )
    check_monthly_path(audit_path)
    if (
        not audit_path.is_relative_to(store.root / "assemblies")
        or monthly_file_hash(audit_path, max_bytes=store.io_policy.control_max_bytes)
        != audit_hash
    ):
        raise ValueError("monthly_candidate_audit_changed")
    audit = read_monthly_json(audit_path, store.io_policy.control_max_bytes)
    if (
        audit.get("plan_hash") != store.plan.plan_hash
        or audit.get("io_hash") != store.io_hash
        or audit.get("source") != store.plan.source.value
    ):
        raise ValueError("monthly_candidate_identity_mismatch")
    lake_root = Path(audit["lake_root"])
    check_monthly_root(lake_root, staging=False)
    check_monthly_free_space(lake_root, store.io_policy.control_max_bytes + 12 * 4096)
    inventory = next(
        (i for i in store.plan.inventories if i.year == audit["year"]), None
    )
    if (
        inventory is None
        or audit["captured_rows"] != inventory.source_rows
        or audit["excluded_rows"] != inventory.excluded_rows
        or audit["accepted_rows"] != inventory.source_rows - inventory.excluded_rows
    ):
        raise ValueError("monthly_candidate_inventory_mismatch")
    directory = audit_path.parent
    records = audit["records"]
    if len(records) > 12 or len({r["month"] for r in records}) != len(records):
        raise ValueError("monthly_candidate_partition_invalid")
    expected_months = {
        d[:4] + "-" + d[4:6] for d, _ in inventory.source_date_counts if d != "20200229"
    }
    if {r["month"] for r in records} != expected_months:
        raise ValueError("monthly_candidate_partition_invalid")
    checkpoint_path = directory / "promoted.json"
    checkpoint = (
        read_monthly_json(checkpoint_path, store.io_policy.control_max_bytes)
        if checkpoint_path.exists()
        else {"audit_hash": audit_hash, "completed": {}}
    )
    if checkpoint.get("audit_hash") != audit_hash or not set(
        checkpoint["completed"]
    ).issubset(expected_months):
        raise ValueError("monthly_checkpoint_identity_mismatch")
    paths = []
    for record in records:
        path = directory / record["path"]
        if (
            path
            != directory / "candidates" / f"month={record['month']}" / "data.parquet"
        ):
            raise ValueError("monthly_candidate_path_invalid")
        check_monthly_path(path)
        target = monthly_target_path(lake_root, store.plan.source, record["month"])
        location = path if path.exists() else target
        if (
            monthly_file_hash(location, max_bytes=store.io_policy.prod_csv_max_bytes)
            != record["sha256"]
        ):
            raise ValueError("monthly_candidate_changed")
        paths.append(location)
    excluded = directory / "excluded_month_version.parquet"
    if (
        monthly_file_hash(excluded, max_bytes=store.io_policy.prod_csv_max_bytes)
        != audit["excluded_sha256"]
    ):
        raise ValueError("monthly_exclusion_changed")
    expected_units = [
        u for u in store.plan.units if int(u.source_date_start[:4]) == inventory.year
    ]
    if [r["unit_id"] for r in audit["receipts"]] != [u.unit_id for u in expected_units]:
        raise ValueError("monthly_candidate_receipts_invalid")
    capture_paths = []
    for unit, reference in zip(expected_units, audit["receipts"], strict=True):
        check_monthly_cancel(cancel)
        if (
            monthly_file_hash(
                store.unit_directory(unit) / "receipt.json",
                max_bytes=store.io_policy.control_max_bytes,
            )
            != reference["receipt_hash"]
        ):
            raise ValueError("monthly_candidate_receipt_changed")
        _, path = store.read_receipt(unit)
        capture_paths.append(path)
    with store.connection() as con:
        load_monthly_parquets(con, "monthly_candidate", paths, store.plan.source)
        validate_month_relation(
            con,
            "monthly_candidate",
            store.plan.source,
            store.plan.policy,
            max_rows=store.plan.policy.max_year_rows,
        )
        expected = {
            r["month"]: {"rows": r["rows"], "logical_hash": r["logical_hash"]}
            for r in records
        }
        if (
            canonical_month_hashes(con, "monthly_candidate", store.plan.source)
            != expected
        ):
            raise ValueError("monthly_candidate_readback_mismatch")
        load_monthly_parquets(con, "monthly_year", capture_paths, store.plan.source)
        validate_month_relation(
            con,
            "monthly_year",
            store.plan.source,
            store.plan.policy,
            max_rows=store.plan.policy.max_year_rows,
            allow_excluded=True,
        )
        # The policy exclusion ledger must contain precisely the captured 29th rows.
        difference = con.execute(
            "SELECT count(*) FROM ((SELECT * FROM monthly_year WHERE trade_date='20200229' EXCEPT ALL SELECT * FROM read_parquet(?,hive_partitioning=false)) UNION ALL (SELECT * FROM read_parquet(?,hive_partitioning=false) EXCEPT ALL SELECT * FROM monthly_year WHERE trade_date='20200229'))",
            [str(excluded), str(excluded)],
        ).fetchone()[0]
        difference += con.execute(
            "SELECT count(*) FROM ((SELECT * FROM monthly_year WHERE trade_date<>'20200229' EXCEPT ALL SELECT * FROM monthly_candidate) UNION ALL (SELECT * FROM monthly_candidate EXCEPT ALL SELECT * FROM monthly_year WHERE trade_date<>'20200229'))"
        ).fetchone()[0]
        if difference:
            raise ValueError("monthly_capture_candidate_difference")
    # Inspect all existing targets before the first install; recheck under each lock.
    for record in records:
        target = monthly_target_path(lake_root, store.plan.source, record["month"])
        current = monthly_file_hash(target) if target.exists() else None
        saved = checkpoint["completed"].get(record["month"])
        if saved is not None and current != saved["sha256"]:
            raise ValueError("monthly_promoted_target_changed")
        if saved is None and current not in (record["target_sha256"], record["sha256"]):
            raise ValueError("monthly_target_fingerprint_changed")
        if target.exists():
            with store.connection() as con:
                load_monthly_parquets(
                    con, "monthly_candidate", [target], store.plan.source
                )
                validate_month_relation(
                    con,
                    "monthly_candidate",
                    store.plan.source,
                    store.plan.policy,
                    max_rows=store.plan.policy.max_codes,
                )
                expected_file = {
                    record["month"]: {
                        "rows": record["rows"],
                        "logical_hash": record["logical_hash"],
                    }
                }
                if (
                    canonical_month_hashes(con, "monthly_candidate", store.plan.source)
                    != expected_file
                ):
                    raise ValueError("monthly_revision_required")
        elif (directory / record["path"]).stat().st_dev != lake_root.stat().st_dev:
            raise ValueError("monthly_cross_filesystem_forbidden")
    locks = store.root.parents[1] / "locks"
    check_monthly_path(locks)
    locks.mkdir(exist_ok=True)
    # Lock directory is common to all plans and execution-policy versions.
    for record in records:
        check_monthly_cancel(cancel)
        store.verify_plan()
        month = record["month"]
        target = monthly_target_path(lake_root, store.plan.source, month)
        candidate = directory / record["path"]
        with monthly_file_lock(locks / f"{store.plan.source.value}-{month}.lock"):
            current_hash = monthly_file_hash(target) if target.exists() else None
            saved = checkpoint["completed"].get(month)
            if saved is not None and current_hash != saved["sha256"]:
                raise ValueError("monthly_promoted_target_changed")
            if (
                saved is None
                and current_hash != record["target_sha256"]
                and current_hash != record["sha256"]
            ):
                raise ValueError("monthly_target_fingerprint_changed")
            if target.exists():
                with store.connection() as con:
                    load_monthly_parquets(
                        con, "monthly_candidate", [target], store.plan.source
                    )
                    validate_month_relation(
                        con,
                        "monthly_candidate",
                        store.plan.source,
                        store.plan.policy,
                        max_rows=store.plan.policy.max_codes,
                    )
                    if canonical_month_hashes(
                        con, "monthly_candidate", store.plan.source
                    ) != {
                        month: {
                            "rows": record["rows"],
                            "logical_hash": record["logical_hash"],
                        }
                    }:
                        raise ValueError("monthly_revision_required")
                outcome = (
                    "identical_reused" if candidate.exists() else "promotion_recovered"
                )
            else:
                if (
                    not candidate.exists()
                    or monthly_file_hash(candidate) != record["sha256"]
                ):
                    raise ValueError("monthly_candidate_changed")
                check_monthly_path(target.parent)
                target.parent.mkdir(parents=True, exist_ok=True)
                check_monthly_path(target)
                if candidate.stat().st_dev != target.parent.stat().st_dev:
                    raise ValueError("monthly_cross_filesystem_forbidden")
                check_monthly_cancel(cancel)
                os.replace(candidate, target)
                sync_monthly_directory(target.parent)
                sync_monthly_directory(candidate.parent)
                current_hash = monthly_file_hash(target)
                if current_hash != record["sha256"]:
                    raise ValueError("monthly_promoted_target_changed")
                outcome = "promoted"
            checkpoint["completed"][month] = {
                "sha256": current_hash,
                "outcome": outcome,
                "rows": record["rows"],
            }
            write_monthly_json(
                checkpoint_path, checkpoint, store.io_policy.control_max_bytes
            )
            progress(
                {
                    "phase": outcome,
                    "source": store.plan.source.value,
                    "month": month,
                    "completed": len(checkpoint["completed"]),
                    "total": len(records),
                    "rows": record["rows"],
                }
            )
    return checkpoint
