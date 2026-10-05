"""Read bounded bootstrap provenance sealed by the annual audit and promotion."""

import re
import tempfile
from pathlib import Path

from orchestrator.defs.bootstrap.stock_monthly_files import (
    check_monthly_path,
    monthly_file_hash,
    read_monthly_json,
)
from orchestrator.defs.io.stock_monthly_raw import (
    canonical_month_hashes,
    load_monthly_parquets,
    validate_month_relation,
)
from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT, raw_stock_monthly_path
from orchestrator.defs.run_contracts.stock_monthly import (
    MonthlyBootstrapIOPolicy,
    StockMonthlyPolicy,
)


def read_month_bootstrap_delivery(delivery, root, source, month, *, connection=None):
    path = Path(delivery["audit_path"])
    check_monthly_path(path)
    allowed = (
        Path(DEFAULT_LAKE_STAGING_ROOT),
        Path("/private/tmp"),
        Path(tempfile.gettempdir()).resolve(),
    )
    io = MonthlyBootstrapIOPolicy()
    policy = StockMonthlyPolicy()
    if (
        path.name != "audit.json"
        or path.parent.parent.name != "assemblies"
        or not any(path.is_relative_to(p) for p in allowed)
    ):
        raise ValueError("monthly_bootstrap_delivery_path_forbidden")
    if (
        monthly_file_hash(path, max_bytes=io.control_max_bytes)
        != delivery["audit_hash"]
    ):
        raise ValueError("monthly_bootstrap_audit_changed")
    audit = read_monthly_json(path, io.control_max_bytes)
    target = raw_stock_monthly_path(root, source, month)
    if (
        audit["source"] != source.value
        or audit["lake_root"] != str(root)
        or delivery["source"] != source.value
        or delivery["month"] != month
        or delivery["path"] != str(target)
    ):
        raise ValueError("monthly_bootstrap_delivery_identity_invalid")
    if (
        not 0
        <= audit["excluded_rows"]
        <= audit["captured_rows"]
        <= policy.max_year_rows + policy.max_codes
        or audit["captured_rows"] != audit["excluded_rows"] + audit["accepted_rows"]
        or audit["accepted_rows"] > policy.max_year_rows
    ):
        raise ValueError("monthly_bootstrap_conservation_invalid")
    records = audit["records"]
    receipts = audit["receipts"]
    if (
        not records
        or len(records) > 12
        or len({r["month"] for r in records}) != len(records)
        or sum(r["rows"] for r in records) != audit["accepted_rows"]
        or not receipts
        or len(receipts) > 34
        or len({r["unit_id"] for r in receipts}) != len(receipts)
    ):
        raise ValueError("monthly_bootstrap_evidence_budget_invalid")
    selected = [item for item in records if item["month"] == month]
    if (
        len(selected) != 1
        or not 0 < selected[0]["rows"] <= policy.max_codes
        or selected[0]["rows"] != delivery["rows"]
        or selected[0]["path"] != f"candidates/month={month}/data.parquet"
    ):
        raise ValueError("monthly_bootstrap_month_invalid")
    checkpoint = read_monthly_json(path.parent / "promoted.json", io.control_max_bytes)
    completed = checkpoint["completed"].get(month)
    if (
        checkpoint["audit_hash"] != delivery["audit_hash"]
        or not completed
        or completed["rows"] != selected[0]["rows"]
        or monthly_file_hash(target, max_bytes=io.prod_csv_max_bytes)
        != completed["sha256"]
    ):
        raise ValueError("monthly_bootstrap_promoted_file_changed")
    # Controls pin original annual capture identity; no annual business-file rescan.
    for item in receipts:
        if not re.fullmatch("[a-f0-9]{64}", item["unit_id"]):
            raise ValueError("monthly_bootstrap_receipt_identity_invalid")
        receipt_path = (
            path.parent.parent.parent / "units" / item["unit_id"] / "receipt.json"
        )
        if (
            monthly_file_hash(receipt_path, max_bytes=io.control_max_bytes)
            != item["receipt_hash"]
        ):
            raise ValueError("monthly_bootstrap_receipt_changed")
    if connection is not None:
        count = connection.execute(
            "SELECT count(*) FROM (SELECT 1 FROM read_parquet(?,hive_partitioning=false) LIMIT ?)",
            [str(target), policy.max_codes + 1],
        ).fetchone()[0]
        if count != selected[0]["rows"]:
            raise ValueError("monthly_bootstrap_formal_row_budget_invalid")
        load_monthly_parquets(connection, "monthly_candidate", [target], source)
        validate_month_relation(
            connection, "monthly_candidate", source, policy, max_rows=policy.max_codes
        )
        if canonical_month_hashes(connection, "monthly_candidate", source) != {
            month: {
                "rows": selected[0]["rows"],
                "logical_hash": selected[0]["logical_hash"],
            }
        }:
            raise ValueError("monthly_bootstrap_formal_values_changed")
    return {
        "rows": selected[0]["rows"],
        "source_rows": selected[0]["rows"] + (audit["excluded_rows"] if month == "2020-02" else 0),
        "excluded_source_rows": audit["excluded_rows"] if month == "2020-02" else 0,
        "source_method": "prod_month_bootstrap",
        "annual_captured_rows": audit["captured_rows"],
        "annual_excluded_rows": audit["excluded_rows"],
        "annual_accepted_rows": audit["accepted_rows"],
    }
