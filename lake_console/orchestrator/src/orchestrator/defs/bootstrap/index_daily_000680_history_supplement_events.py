"""Runless materialization planning for the 000680.SH supplement."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_apply import (
    load_frozen_plan,
)
from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_plan import (
    TARGET_CODE,
    hash_payload,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes

RAW_ASSET_KEY = dg.AssetKey("raw_index_daily")
SILVER_ASSET_KEY = dg.AssetKey("silver_index_daily")
GOLD_ASSET_KEY = dg.AssetKey("gold_market_major_indices_daily")


class IndexDaily000680HistorySupplementEventsError(RuntimeError):
    """Raised before an unsafe partition or event write."""


@dataclass(frozen=True, slots=True)
class SupplementEventPlan:
    plan_hash: str
    physical_audit_hash: str
    missing_date_partitions: tuple[str, ...]
    target_code_registered: bool
    raw_materializations: tuple[str, ...]
    silver_materializations: tuple[str, ...]
    gold_materializations: tuple[str, ...]
    stop_reason_codes: tuple[str, ...]

    @property
    def planned_materialization_count(self) -> int:
        return (
            len(self.raw_materializations)
            + len(self.silver_materializations)
            + len(self.gold_materializations)
        )

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reason_codes)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "target_code": TARGET_CODE,
            "plan_hash": self.plan_hash,
            "physical_audit_hash": self.physical_audit_hash,
            "partition_registration": {
                "date_partition_set": cn_a_index_trade_days.name,
                "missing_dates": list(self.missing_date_partitions),
                "code_partition_set": cn_a_index_ts_codes.name,
                "target_code_registered": self.target_code_registered,
            },
            "materializations": {
                "raw_index_daily": list(self.raw_materializations),
                "silver_index_daily": list(self.silver_materializations),
                "gold_market_major_indices_daily": list(self.gold_materializations),
                "planned_count": self.planned_materialization_count,
            },
            "planned_check_event_count": 0,
            "should_stop": self.should_stop,
            "stop_reason_codes": list(self.stop_reason_codes),
            "writes": {
                "formal_lake": 0,
                "dagster_db": 0,
                "dynamic_partitions": 0,
                "dagster_events": 0,
            },
        }


@dataclass(frozen=True, slots=True)
class SupplementEventApplyReport:
    plan_hash: str
    physical_audit_hash: str
    registered_date_partition_count: int
    registered_code_partition_count: int
    reported_raw_materialization_count: int
    reported_silver_materialization_count: int
    reported_gold_materialization_count: int

    @property
    def reported_materialization_count(self) -> int:
        return (
            self.reported_raw_materialization_count
            + self.reported_silver_materialization_count
            + self.reported_gold_materialization_count
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "reported_materialization_count": self.reported_materialization_count,
            "reported_check_event_count": 0,
        }


def _dates_from_targets(plan: Mapping[str, Any], layer: str) -> tuple[str, ...]:
    targets = plan.get("targets")
    if not isinstance(targets, Mapping):
        raise IndexDaily000680HistorySupplementEventsError(
            "Frozen plan has no targets object."
        )
    values = targets.get(f"{layer}_files")
    if not isinstance(values, list):
        raise IndexDaily000680HistorySupplementEventsError(
            f"Frozen plan has no {layer} target files."
        )
    dates: list[str] = []
    for value in values:
        path = Path(str(value))
        partition = next(
            (
                part.removeprefix("trade_date=")
                for part in path.parts
                if part.startswith("trade_date=")
            ),
            None,
        )
        if partition is None:
            raise IndexDaily000680HistorySupplementEventsError(
                f"Target path has no trade_date partition: {path}"
            )
        dates.append(partition)
    return tuple(dates)


def _load_green_physical_audit(
    audit_path: Path,
    *,
    expected_plan_hash: str,
) -> Mapping[str, Any]:
    try:
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IndexDaily000680HistorySupplementEventsError(
            f"Cannot read physical audit: {audit_path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise IndexDaily000680HistorySupplementEventsError(
            "Physical audit must be a JSON object."
        )
    if payload.get("plan_hash") != expected_plan_hash or payload.get("passed") is not True:
        raise IndexDaily000680HistorySupplementEventsError(
            "Physical audit is not green for the expected plan hash."
        )
    layers = payload.get("layers")
    cross_layer = payload.get("cross_layer")
    if not isinstance(layers, Mapping) or not isinstance(cross_layer, Mapping):
        raise IndexDaily000680HistorySupplementEventsError(
            "Physical audit is missing layer or cross-layer evidence."
        )
    expected_audit_hash = hash_payload(
        {
            "plan_hash": expected_plan_hash,
            "raw": layers.get("raw"),
            "silver": layers.get("silver"),
            "gold": layers.get("gold"),
            "raw_silver_history_matches": cross_layer.get(
                "raw_silver_history_matches"
            ),
            "silver_gold_matches": cross_layer.get("silver_gold_matches"),
        }
    )
    if payload.get("audit_hash") != expected_audit_hash:
        raise IndexDaily000680HistorySupplementEventsError(
            "Physical audit hash does not match its evidence."
        )
    return payload


def plan_supplement_events(
    *,
    instance: Any,
    plan_path: Path,
    physical_audit_path: Path,
    expected_plan_hash: str,
) -> SupplementEventPlan:
    plan = load_frozen_plan(
        plan_path,
        expected_plan_hash=expected_plan_hash,
        require_green=True,
    )
    audit = _load_green_physical_audit(
        physical_audit_path,
        expected_plan_hash=expected_plan_hash,
    )
    raw_dates = _dates_from_targets(plan, "raw")
    silver_dates = _dates_from_targets(plan, "silver")
    gold_dates = _dates_from_targets(plan, "gold")
    expected_dates = set(raw_dates) | set(silver_dates) | set(gold_dates)
    registered_dates = set(
        instance.get_dynamic_partitions(cn_a_index_trade_days.name)
    )
    registered_codes = set(
        instance.get_dynamic_partitions(cn_a_index_ts_codes.name)
    )
    raw_materialized = set(instance.get_materialized_partitions(RAW_ASSET_KEY))
    silver_materialized = set(instance.get_materialized_partitions(SILVER_ASSET_KEY))
    gold_materialized = set(instance.get_materialized_partitions(GOLD_ASSET_KEY))
    stop_reason_codes: list[str] = []
    if audit.get("passed") is not True:
        stop_reason_codes.append("PHYSICAL_AUDIT_FAILED")
    return SupplementEventPlan(
        plan_hash=expected_plan_hash,
        physical_audit_hash=str(audit["audit_hash"]),
        missing_date_partitions=tuple(sorted(expected_dates - registered_dates)),
        target_code_registered=TARGET_CODE in registered_codes,
        raw_materializations=tuple(
            value for value in raw_dates if value not in raw_materialized
        ),
        silver_materializations=tuple(
            value for value in silver_dates if value not in silver_materialized
        ),
        gold_materializations=tuple(
            value for value in gold_dates if value not in gold_materialized
        ),
        stop_reason_codes=tuple(stop_reason_codes),
    )


def report_supplement_events(
    *,
    instance: Any,
    plan_path: Path,
    physical_audit_path: Path,
    expected_plan_hash: str,
    apply: bool,
    confirm_partition_write: bool,
    confirm_event_write: bool,
) -> SupplementEventApplyReport:
    if not apply:
        raise IndexDaily000680HistorySupplementEventsError(
            "Dagster writes require explicit apply=True."
        )
    plan = plan_supplement_events(
        instance=instance,
        plan_path=plan_path,
        physical_audit_path=physical_audit_path,
        expected_plan_hash=expected_plan_hash,
    )
    if plan.should_stop:
        raise IndexDaily000680HistorySupplementEventsError(
            f"Event plan is blocked: {plan.stop_reason_codes}"
        )
    if (
        plan.missing_date_partitions or not plan.target_code_registered
    ) and not confirm_partition_write:
        raise IndexDaily000680HistorySupplementEventsError(
            "Missing partitions require --confirm-partition-write."
        )
    if plan.planned_materialization_count and not confirm_event_write:
        raise IndexDaily000680HistorySupplementEventsError(
            "Runless materializations require --confirm-event-write."
        )
    registered_date_count = 0
    registered_code_count = 0
    if plan.missing_date_partitions or not plan.target_code_registered:
        if plan.missing_date_partitions:
            instance.add_dynamic_partitions(
                cn_a_index_trade_days.name,
                list(plan.missing_date_partitions),
            )
            registered_date_count = len(plan.missing_date_partitions)
        if not plan.target_code_registered:
            instance.add_dynamic_partitions(cn_a_index_ts_codes.name, [TARGET_CODE])
            registered_code_count = 1
    reported_counts: dict[str, int] = {"raw": 0, "silver": 0, "gold": 0}
    for layer, asset_key, partition_keys in (
        ("raw", RAW_ASSET_KEY, plan.raw_materializations),
        ("silver", SILVER_ASSET_KEY, plan.silver_materializations),
        ("gold", GOLD_ASSET_KEY, plan.gold_materializations),
    ):
        for partition_key in partition_keys:
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=asset_key,
                    partition=partition_key,
                    metadata={
                        "source_method": "direct_lake_history_supplement",
                        "target_code": TARGET_CODE,
                        "plan_hash": plan.plan_hash,
                        "physical_audit_hash": plan.physical_audit_hash,
                    },
                )
            )
            reported_counts[layer] += 1
    return SupplementEventApplyReport(
        plan_hash=plan.plan_hash,
        physical_audit_hash=plan.physical_audit_hash,
        registered_date_partition_count=registered_date_count,
        registered_code_partition_count=registered_code_count,
        reported_raw_materialization_count=reported_counts["raw"],
        reported_silver_materialization_count=reported_counts["silver"],
        reported_gold_materialization_count=reported_counts["gold"],
    )


def write_report(
    report: SupplementEventPlan | SupplementEventApplyReport,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
