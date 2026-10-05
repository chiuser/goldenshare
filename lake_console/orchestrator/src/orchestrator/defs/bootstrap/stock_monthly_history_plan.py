"""Strict monthly inventory evidence and reproducible bootstrap plan serialization."""

import json
from dataclasses import asdict
from pathlib import Path

from orchestrator.defs.bootstrap.stock_monthly_files import (
    check_monthly_path,
    monthly_file_hash,
    read_monthly_json,
)
from orchestrator.defs.prod_db.stock_monthly import prod_monthly_table
from orchestrator.defs.run_contracts.stock_monthly import (
    MonthlyBootstrapIOPolicy,
    MonthlyYearInventory,
    StockMonthlyPolicy,
    StockMonthlySource,
)
from orchestrator.defs.stock_monthly_planner import plan_month_bootstrap


def freeze_monthly_history_plan(inventory, source, first_month, last_month):
    """The inventory contains only this exact scope, including rejected date versions."""
    inventory = Path(inventory)
    check_monthly_path(inventory)
    cap = MonthlyBootstrapIOPolicy().inventory_max_bytes
    digest = monthly_file_hash(inventory, max_bytes=cap)
    with inventory.open("rb") as stream:
        records = [json.loads(line) for line in stream if line.strip()]
    if monthly_file_hash(inventory, max_bytes=cap) != digest:
        raise ValueError("monthly_inventory_changed")
    snapshots = [r for r in records if r.get("section") == "snapshot"]
    if len(snapshots) != 1 or snapshots[0].get("readonly") != "on":
        raise ValueError("monthly_inventory_readonly_evidence_required")
    if not snapshots[0].get("snapshot") or not snapshots[0].get("audited_at"):
        raise ValueError("monthly_inventory_snapshot_missing")
    source = StockMonthlySource(source)
    table = prod_monthly_table(source).split(".")[1]
    years = [r for r in records if r.get("section") == "year" and r.get("table") == table]
    dates = [r for r in records if r.get("section") == "date" and r.get("table") == table]
    if not years or not dates or len(dates) > 12 * len(years) + 1:
        raise ValueError("monthly_inventory_scope_invalid")
    if len({r["date"] for r in dates}) != len(dates):
        raise ValueError("monthly_inventory_date_duplicate")
    if {r["date"][:4] for r in dates} != {str(r["year"]) for r in years} or sum(r["rows"] for r in dates) != sum(r["rows"] for r in years):
        raise ValueError("monthly_inventory_unaccounted_date")
    inventories = []
    for row in years:
        counts = tuple(sorted(
            (r["date"].replace("-", ""), r["rows"])
            for r in dates if r["date"][:4] == str(row["year"])
        ))
        item = MonthlyYearInventory(row["year"], tuple(row["codes"]), counts)
        if item.source_rows != row["rows"]:
            raise ValueError("monthly_inventory_count_mismatch")
        inventories.append(item)
    return plan_month_bootstrap(
        source, tuple(inventories), first_month=first_month, last_month=last_month,
        inventory_ref=str(inventory), inventory_hash=digest,
    )


def monthly_history_plan_payload(plan):
    return {"kind": "monthly_history_plan", "version": 1, "plan": asdict(plan)}


def load_monthly_history_plan(path):
    payload = read_monthly_json(Path(path), MonthlyBootstrapIOPolicy().inventory_max_bytes)
    if set(payload) != {"kind", "version", "plan"} or payload["kind"] != "monthly_history_plan" or payload["version"] != 1:
        raise ValueError("monthly_history_plan_format_invalid")
    frozen = payload["plan"]
    plan = freeze_monthly_history_plan(
        frozen["inventory_ref"], frozen["source"], frozen["first_month"], frozen["last_month"],
    )
    # Recompute from the physical inventory, never trust serialized units or row counts.
    expected = json.loads(json.dumps(asdict(plan)))
    if frozen != expected or plan.policy != StockMonthlyPolicy():
        raise ValueError("monthly_history_plan_changed")
    return plan
