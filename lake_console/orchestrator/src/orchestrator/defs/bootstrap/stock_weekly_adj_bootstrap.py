"""Pin adjusted Raw bootstrap capture to one real Prod business boundary."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    _atomic_json,
    capture_file_hash,
    check_capture_path,
    check_weekly_cancel,
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
