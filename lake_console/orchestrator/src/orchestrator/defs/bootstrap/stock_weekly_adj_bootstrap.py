"""Pin adjusted Raw bootstrap capture to one real Prod business boundary."""

from __future__ import annotations

import json
import resource
import sys
from dataclasses import asdict
from pathlib import Path

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    _atomic_json,
    capture_file_hash,
    check_capture_path,
    check_weekly_cancel,
    weekly_unit_identity,
)
from orchestrator.defs.prod_db.stock_weekly_adj_delivery import (
    PsqlWeeklyAdjDeliveryReader,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyScope,
    ProdYearInventory,
    StockWeeklySource,
)
from orchestrator.defs.run_contracts.stock_weekly_adj_delivery import (
    DeliveryHeader,
    WeeklyAdjProdDeliveryBudget,
)
from orchestrator.defs.stock_weekly_planner import freeze_prod_weekly_plan


def validate_bootstrap_inventory(payload):
    source = StockWeeklySource(payload["source"])
    boundary = payload.get("bootstrap_boundary")
    if source is not StockWeeklySource.PRIMARY_ADJUSTED:
        if boundary is not None:
            raise WeeklyCaptureError("bootstrap_boundary_source_invalid")
        return None
    if not isinstance(boundary, dict):
        raise WeeklyCaptureError("adjusted_bootstrap_boundary_required")
    try:
        header = DeliveryHeader(**boundary)
        header.validate_budget(WeeklyAdjProdDeliveryBudget())
        if (
            header.record_kind != "bootstrap_closed"
            or header.header["bootstrap"] is not True
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise WeeklyCaptureError("adjusted_bootstrap_boundary_invalid") from None
    return header


def bootstrap_header_for_manifest(manifest):
    if manifest.source is not StockWeeklySource.PRIMARY_ADJUSTED:
        return None
    path = Path(manifest.evidence_ref)
    check_capture_path(path)
    if (
        path.suffix != ".json"
        or path.stat().st_size > 16 * 1024 * 1024
        or capture_file_hash(path) != manifest.evidence_hash
    ):
        raise WeeklyCaptureError("adjusted_bootstrap_inventory_invalid")
    try:
        payload = json.loads(path.read_text())
        if (
            type(payload["version"]) is not int
            or payload["version"] != 1
            or payload["kind"] != "prod_weekly_inventory"
            or payload["source"] != manifest.source.value
        ):
            raise ValueError
        frozen = freeze_prod_weekly_plan(
            ProdWeeklyScope(
                manifest.source,
                tuple(
                    ProdYearInventory(i["year"], tuple(i["codes"]), i["source_rows"])
                    for i in payload["inventories"]
                ),
                manifest.evidence_ref,
                manifest.evidence_hash,
                manifest.budget,
            )
        )
        if frozen != manifest:
            raise ValueError
        return validate_bootstrap_inventory(payload)
    except (ValueError, TypeError, KeyError):
        raise WeeklyCaptureError("adjusted_bootstrap_inventory_invalid") from None


class AdjustedWeeklyBootstrapGuard:
    def __init__(self, manifest, *, reader=None):
        self.header = bootstrap_header_for_manifest(manifest)
        if self.header is None:
            raise WeeklyCaptureError("bootstrap_boundary_source_invalid")
        self.plan_hash = manifest.plan_hash
        self.reader = reader if reader is not None else PsqlWeeklyAdjDeliveryReader()

    def validate_manifest(self, manifest):
        if (
            not manifest.units
            or manifest.plan_hash != self.plan_hash
            or bootstrap_header_for_manifest(manifest) != self.header
        ):
            raise WeeklyCaptureError("adjusted_bootstrap_inventory_changed")

    def check(self, *, cancel, progress, expected_raw_rows=None):
        check_weekly_cancel(cancel)
        self.reader.assert_bootstrap_current(
            self.header,
            cancel=cancel,
            progress=progress,
            expected_raw_rows=expected_raw_rows,
        )
        check_weekly_cancel(cancel)

    def seal(self, store, receipts, source_rows, *, cancel):
        """One capture-scoped completion; never a daily readiness dependency."""
        store._require_lock()
        check_weekly_cancel(cancel)
        if (
            len(receipts) != len(store.manifest.units)
            or [r["unit_id"] for r in receipts]
            != [u.unit_id for u in store.manifest.units]
            or sum(r["source_rows"] for r in receipts) != source_rows
            or source_rows != store.manifest.planned_key_count
        ):
            raise WeeklyCaptureError("adjusted_bootstrap_capture_incomplete")
        value = {
            "version": 1,
            "plan_hash": self.plan_hash,
            "bootstrap_boundary": asdict(self.header),
            "source_rows": source_rows,
            "receipts": receipts,
        }
        if (
            len(json.dumps(value, ensure_ascii=False).encode())
            > WeeklyAdjProdDeliveryBudget().max_plan_bytes
        ):
            raise WeeklyCaptureError("adjusted_bootstrap_capture_budget_exceeded")
        path = store.root / "bootstrap-capture.json"
        check_capture_path(path)
        if path.exists():
            if (
                path.stat().st_size > WeeklyAdjProdDeliveryBudget().max_plan_bytes
                or json.loads(path.read_text()) != value
            ):
                raise WeeklyCaptureError("adjusted_bootstrap_capture_changed")
        else:
            _atomic_json(path, value)


def read_complete_bootstrap_capture(store, *, cancel=lambda: False):
    """Validate this capture's completion locally; never query mutable Prod."""
    store._require_lock()
    check_weekly_cancel(cancel)
    header = bootstrap_header_for_manifest(store.manifest)
    if header is None or not store.manifest.units:
        raise WeeklyCaptureError("adjusted_bootstrap_boundary_required")
    path = store.root / "bootstrap-capture.json"
    check_capture_path(path)
    if not path.is_file():
        raise WeeklyCaptureError("adjusted_bootstrap_capture_required")
    if path.stat().st_size > WeeklyAdjProdDeliveryBudget().max_plan_bytes:
        raise WeeklyCaptureError("adjusted_bootstrap_capture_budget_exceeded")
    try:
        value = json.loads(path.read_text())
        receipts = value["receipts"]
        if (
            set(value)
            != {"version", "plan_hash", "bootstrap_boundary", "source_rows", "receipts"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["plan_hash"] != store.manifest.plan_hash
            or DeliveryHeader(**value["bootstrap_boundary"]) != header
            or type(value["source_rows"]) is not int
            or value["source_rows"] != store.manifest.planned_key_count
            or not isinstance(receipts, list)
            or len(receipts) != len(store.manifest.units)
        ):
            raise ValueError
        total = 0
        for unit, item in zip(store.manifest.units, receipts, strict=True):
            check_weekly_cancel(cancel)
            receipt_path = store.unit_directory(unit) / "receipt.json"
            check_capture_path(receipt_path)
            if (
                set(item) != {"unit_id", "sha256", "source_rows"}
                or item["unit_id"] != unit.unit_id
                or type(item["source_rows"]) is not int
                or item["source_rows"] < 0
                or receipt_path.stat().st_size > 1024 * 1024
                or capture_file_hash(receipt_path) != item["sha256"]
            ):
                raise ValueError
            receipt = json.loads(receipt_path.read_text())
            if (
                receipt["plan_hash"] != store.manifest.plan_hash
                or receipt["unit_hash"] != weekly_unit_identity(unit)
                or receipt["schema_hash"] != unit.schema_hash
                or receipt["status"] not in ("captured", "success_empty")
                or type(receipt["source_rows"]) is not int
                or receipt["source_rows"] != item["source_rows"]
            ):
                raise ValueError
            total += item["source_rows"]
        if total != value["source_rows"]:
            raise ValueError
    except (KeyError, TypeError, ValueError, OSError):
        raise WeeklyCaptureError("adjusted_bootstrap_capture_invalid") from None
    check_weekly_cancel(cancel)
    return header, {"path": str(path), "sha256": capture_file_hash(path)}


def check_bootstrap_process_budget():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    if peak_bytes > WeeklyAdjProdDeliveryBudget().max_process_rss_bytes:
        raise WeeklyCaptureError("adjusted_bootstrap_process_rss_budget_exceeded")


def check_bootstrap_staging_budget(root):
    check_bootstrap_process_budget()
    total = 0
    for path in root.rglob("*"):
        check_capture_path(path)
        if path.is_file():
            total += path.stat().st_size
            if total > WeeklyAdjProdDeliveryBudget().max_staging_bytes:
                raise WeeklyCaptureError("adjusted_bootstrap_staging_budget_exceeded")
