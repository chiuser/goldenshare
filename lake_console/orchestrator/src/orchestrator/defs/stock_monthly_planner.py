"""Freeze bounded monthly bootstrap units from verified inventory; no IO."""

from dataclasses import asdict
from datetime import date

from orchestrator.defs.run_contracts.stock_monthly import (
    MonthlyBootstrapPlan,
    MonthlyDateDisposition,
    MonthlyProdUnit,
    MonthlyYearInventory,
    StockMonthlyPolicy,
    StockMonthlySource,
    classify_month_date,
    month_window,
    monthly_column_specs,
    monthly_contract_hash,
    normalize_month_key,
)


def plan_month_bootstrap(
    source: StockMonthlySource,
    inventories: tuple[MonthlyYearInventory, ...],
    *,
    first_month: str,
    last_month: str,
    inventory_ref: str,
    inventory_hash: str,
    policy: StockMonthlyPolicy | None = None,
) -> MonthlyBootstrapPlan:
    policy = policy if policy is not None else StockMonthlyPolicy()
    source = StockMonthlySource(source)
    normalize_month_key(first_month)
    normalize_month_key(last_month)
    if first_month > last_month:
        raise ValueError("reversed_month_scope")
    if (
        not inventory_ref
        or len(inventory_hash) != 64
        or any(c not in "0123456789abcdef" for c in inventory_hash)
    ):
        raise ValueError("monthly_inventory_evidence_required")
    inventories = tuple(sorted(inventories, key=lambda item: item.year))
    if tuple(i.year for i in inventories) != tuple(
        range(int(first_month[:4]), int(last_month[:4]) + 1)
    ):
        raise ValueError("monthly_year_inventory_missing_or_duplicate")
    if any(
        len(i.codes) > policy.max_codes or i.source_rows > policy.max_year_rows
        for i in inventories
    ):
        raise ValueError("monthly_year_budget_exceeded")
    source_rows = sum(i.source_rows for i in inventories)
    if source_rows > policy.max_capture_rows:
        raise ValueError("monthly_capture_row_budget_exceeded")
    months = set()
    for item in inventories:
        for value, _ in item.source_date_counts:
            month, disposition = classify_month_date(value)
            if not first_month <= month <= last_month:
                raise ValueError("monthly_inventory_outside_scope")
            if disposition is MonthlyDateDisposition.ACCEPTED:
                months.add(month)
    schema_hash = monthly_contract_hash(monthly_column_specs(source))
    body = {
        "version": "stock-monthly-bootstrap-v1",
        "source": source.value,
        "first_month": first_month,
        "last_month": last_month,
        "inventory_ref": inventory_ref,
        "inventory_hash": inventory_hash,
        "schema_hash": schema_hash,
        "policy": asdict(policy),
        "inventories": [asdict(i) for i in inventories],
    }
    plan_hash = monthly_contract_hash(body)
    lower, upper = month_window(first_month)[0], month_window(last_month)[1]
    units = []
    for item in inventories:
        start, end = (
            max(lower, date(item.year, 1, 1)),
            min(upper, date(item.year + 1, 1, 1)),
        )
        for offset in range(0, len(item.codes), policy.prod_code_batch):
            codes = item.codes[offset : offset + policy.prod_code_batch]
            max_rows = len(codes) * len(item.source_date_counts)
            if max_rows > policy.max_prod_unit_rows:
                raise ValueError("monthly_prod_unit_budget_exceeded")
            unit_id = monthly_contract_hash(
                {
                    "plan_hash": plan_hash,
                    "source": source.value,
                    "codes": codes,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                }
            )
            units.append(
                MonthlyProdUnit(
                    unit_id, source, codes, start.isoformat(), end.isoformat(), max_rows
                )
            )
    excluded = sum(i.excluded_rows for i in inventories)
    return MonthlyBootstrapPlan(
        plan_hash,
        source,
        inventory_ref,
        inventory_hash,
        schema_hash,
        policy,
        source_rows,
        excluded,
        source_rows - excluded,
        tuple(sorted(months)),
        tuple(units),
        first_month,
        last_month,
        inventories,
    )
