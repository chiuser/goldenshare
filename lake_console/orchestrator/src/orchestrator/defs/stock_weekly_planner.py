"""Pure bounded source-unit planning. Never opens DB, Lake or Dagster instance."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyScope,
    ProdWeeklyUnit,
    WeeklyPlanManifest,
    stable_weekly_hash,
    weekly_schema_hash,
)


def source_date_week_key(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 8
        or not value.isascii()
        or not value.isdigit()
    ):
        raise ValueError("source_date_must_be_yyyymmdd")
    parsed = date(int(value[:4]), int(value[4:6]), int(value[6:]))
    return (parsed + timedelta(days=4 - parsed.weekday())).isoformat()


def plan_prod_source_units(scope: ProdWeeklyScope) -> tuple[ProdWeeklyUnit, ...]:
    units = []
    schema_hash = weekly_schema_hash(scope.source)
    # Each code contributes at most 54 weekly rows in a calendar-year capture.
    batch_size = min(
        scope.budget.prod_code_batch, scope.budget.max_source_rows_per_prod_unit // 54
    )
    if batch_size < 1:
        raise ValueError("prod_unit_budget_cannot_fit_one_code")
    if len(scope.inventories) * 54 > scope.budget.max_phase_files:
        raise ValueError("phase_file_budget_exceeded")
    for inventory in scope.inventories:
        start, end = date(inventory.year, 1, 1), date(inventory.year + 1, 1, 1)
        for offset in range(0, len(inventory.codes), batch_size):
            codes = inventory.codes[offset : offset + batch_size]
            body = {
                "source": scope.source.value,
                "codes": codes,
                "start": start,
                "end": end,
                "schema_hash": schema_hash,
            }
            units.append(
                ProdWeeklyUnit(
                    unit_id=stable_weekly_hash(body),
                    source=scope.source,
                    sorted_codes=codes,
                    source_date_start=start,
                    source_date_end=end,
                    schema_hash=schema_hash,
                    max_rows=scope.budget.max_source_rows_per_prod_unit,
                )
            )
    return tuple(units)


def freeze_prod_weekly_plan(scope: ProdWeeklyScope) -> WeeklyPlanManifest:
    units = plan_prod_source_units(scope)
    body = {
        "source": scope.source.value,
        "evidence": (scope.inventory_ref, scope.inventory_hash),
        "inventories": [asdict(x) for x in scope.inventories],
        "units": [asdict(x) for x in units],
        "budget": asdict(scope.budget),
    }
    return WeeklyPlanManifest(
        plan_hash=stable_weekly_hash(body),
        source=scope.source,
        evidence_ref=scope.inventory_ref,
        evidence_hash=scope.inventory_hash,
        units=units,
        budget=scope.budget,
        request_cap=0,
        planned_key_count=sum(x.source_rows for x in scope.inventories),
        skipped_key_count=0,
        skipped_reason_counts=(),
    )
