"""Versioned Prod delivery identity and local budgets; no connections or IO."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from uuid import UUID

from orchestrator.defs.run_contracts.stock_weekly import (
    WeeklyBudget,
    normalize_week_key,
    stable_weekly_hash,
)

ADJUSTED_DELIVERY_TABLE = "core.stock_weekly_adj_delivery"
ADJUSTED_DELIVERY_ASSET = "raw_tushare_stk_period_bar_adj_week"
ADJUSTED_DELIVERY_VERSION = 1
# Approved one-time B0 annual replacement exception; daily delivery stays 500k.
ADJUSTED_BOOTSTRAP_MAX_PHASE_ROWS = 1_000_000
ADJUSTED_DELIVERY_BATCH_RUN_TAG = "goldenshare/weekly_adjusted_batch_id"
ADJUSTED_DELIVERY_REVISION_RUN_TAG = "goldenshare/weekly_adjusted_closure_revision"
ADJUSTED_DELIVERY_INTENT_RUN_TAG = "goldenshare/weekly_adjusted_intent_id"


def delivery_revision(value: int, *, allow_zero=False) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1):
        raise ValueError("invalid_adjusted_delivery_revision")
    return value


def delivery_batch_id(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("invalid_adjusted_delivery_batch_id")
    return value


def delivery_digest(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("invalid_adjusted_delivery_digest")
    return value


@dataclass(frozen=True)
class WeeklyAdjProdDeliveryBudget:
    max_units: int = 1000
    max_unit_rows: int = 12_000
    max_unit_payload_bytes: int = 8 * 1024 * 1024
    max_batch_payload_bytes: int = 256 * 1024 * 1024
    max_plan_bytes: int = 1024 * 1024
    max_control_bytes: int = 4096
    max_closure_bytes: int = 256 * 1024
    max_phase_rows: int = 500_000
    max_phase_files: int = 128
    max_phase_targets: int = 54
    max_target_files: int = 1000
    max_staging_bytes: int = 4 * 1024 * 1024 * 1024
    max_process_rss_bytes: int = 1024 * 1024 * 1024
    prod_statement_timeout_ms: int = 30_000
    prod_unit_seconds: int = 45
    progress_interval_seconds: int = 5

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in asdict(self).values()):
            raise ValueError("invalid_adjusted_delivery_budget")
        for name, value in asdict(self).items():
            ceiling = WeeklyAdjProdDeliveryBudget.__dataclass_fields__[name].default
            if value > ceiling:
                raise ValueError("adjusted_delivery_contract_budget_exceeded")
        if self.prod_statement_timeout_ms > self.prod_unit_seconds * 1000:
            raise ValueError("adjusted_delivery_deadline_invalid")

    def weekly_budget(self):
        return WeeklyBudget(
            max_phase_rows=self.max_phase_rows,
            max_phase_files=self.max_phase_files,
            prod_statement_timeout_ms=self.prod_statement_timeout_ms,
            prod_unit_seconds=self.prod_unit_seconds,
            progress_interval_seconds=self.progress_interval_seconds,
        )


@dataclass(frozen=True)
class DeliveryHeader:
    revision: int
    contract_version: int
    batch_id: str
    cutoff_week: str
    record_kind: str
    outcome: str
    rows_received: int
    rows_unique: int
    rows_written: int
    rows_preserved: int
    scope_digest: str
    payload_digest: str
    header: dict

    def __post_init__(self):
        delivery_revision(self.revision)
        delivery_batch_id(self.batch_id)
        normalize_week_key(self.cutoff_week)
        delivery_digest(self.scope_digest)
        delivery_digest(self.payload_digest)
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError("unknown_adjusted_delivery_version")
        if self.record_kind not in ("batch_closed", "bootstrap_closed"):
            raise ValueError("adjusted_delivery_not_closed")
        if self.outcome not in (
            "published",
            "partial_source_preserved",
            "source_empty_preserved",
            "no_trading_week",
        ):
            raise ValueError("adjusted_delivery_outcome_invalid")
        if (
            any(
                type(v) is not int or v < 0
                for v in (
                    self.rows_received,
                    self.rows_unique,
                    self.rows_written,
                    self.rows_preserved,
                )
            )
            or not self.rows_written == self.rows_unique <= self.rows_received
        ):
            raise ValueError("adjusted_delivery_counts_invalid")
        expected = {
            "unit_count",
            "total_payload_bytes",
            "units_digest",
            "bootstrap",
            "contract_digest",
            "max_input_week",
        }
        if not isinstance(self.header, dict) or set(self.header) != expected:
            raise ValueError("adjusted_delivery_header_invalid")
        for name in ("unit_count", "total_payload_bytes"):
            if type(self.header[name]) is not int or self.header[name] < 0:
                raise ValueError("adjusted_delivery_header_invalid")
        if type(self.header["bootstrap"]) is not bool:
            raise ValueError("adjusted_delivery_header_invalid")
        for name in ("units_digest", "contract_digest"):
            delivery_digest(self.header[name])
        anchor = self.anchor_partition
        if anchor is not None:
            normalize_week_key(anchor)
            if anchor > self.cutoff_week:
                raise ValueError("adjusted_delivery_anchor_outside_scope")
        if (anchor is None) != (self.rows_written == 0):
            raise ValueError("adjusted_delivery_empty_anchor_invalid")

    @property
    def anchor_partition(self):
        return self.header["max_input_week"]

    @property
    def intent_id(self):
        return stable_weekly_hash(
            {
                "contract_version": self.contract_version,
                "batch_id": self.batch_id,
                "closure_revision": self.revision,
                "asset": ADJUSTED_DELIVERY_ASSET,
            }
        )

    def validate_budget(self, budget: WeeklyAdjProdDeliveryBudget):
        if (
            self.header["unit_count"] > budget.max_units
            or self.header["total_payload_bytes"] > budget.max_batch_payload_bytes
            or self.rows_received > budget.max_units * budget.max_unit_rows
        ):
            raise ValueError("adjusted_delivery_batch_budget_exceeded")


def source_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("adjusted_delivery_source_date_invalid")
    day = date(int(value[:4]), int(value[4:6]), int(value[6:]))
    return day.isoformat()


def source_week(value: str) -> str:
    return normalize_week_key(source_date(value))


def build_adjusted_delivery_run_request(header):
    """The approved batch identity tags are registered here, never in the sensor."""
    from orchestrator.defs.run_contracts.configs import (
        build_stock_weekly_adj_prod_run_config,
    )
    from orchestrator.defs.run_contracts.requests import build_run_request
    from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key

    request = build_run_request(
        run_key=build_asset_update_run_key(
            subject=ADJUSTED_DELIVERY_ASSET, unit_id=header.intent_id
        ),
        job_name="raw_stk_period_bar_adj_week_update_job",
        partition_key=header.anchor_partition,
        run_config=build_stock_weekly_adj_prod_run_config(
            header.batch_id, header.revision
        ),
    )
    return request.with_replaced_attrs(
        tags={
            ADJUSTED_DELIVERY_BATCH_RUN_TAG: header.batch_id,
            ADJUSTED_DELIVERY_REVISION_RUN_TAG: str(header.revision),
            ADJUSTED_DELIVERY_INTENT_RUN_TAG: header.intent_id,
        }
    )
