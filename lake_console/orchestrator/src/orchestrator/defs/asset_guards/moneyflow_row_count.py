"""Bounded, verified Raw row-count baselines before daily publication."""

from pathlib import Path
from statistics import median

import dagster as dg

from orchestrator.defs.asset_guards.moneyflow_delivery_readiness import (
    batch_moneyflow_readiness,
)
from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_file,
    daily_file_scope_counts,
)
from orchestrator.defs.io.moneyflow_candidates import candidate_file_hash
from orchestrator.defs.paths import raw_moneyflow_path
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_MAX_DATE_FACTS,
    MONEYFLOW_ROW_COUNT_BASELINE_DAYS,
    MONEYFLOW_ROW_COUNT_FALLBACK_DATE,
    MONEYFLOW_ROW_COUNT_MAX_DROP_PERCENT,
    MoneyflowContractError,
    market_moneyflow_day,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    BOARD_DC_MONEYFLOW_AUTOMATION,
    CONCEPT_THS_MONEYFLOW_AUTOMATION,
    INDUSTRY_THS_MONEYFLOW_AUTOMATION,
    STOCK_DC_MONEYFLOW_AUTOMATION,
    STOCK_MONEYFLOW_AUTOMATION,
    STOCK_THS_MONEYFLOW_AUTOMATION,
)


class _BaselineQueries:
    """Use the caller's connection and check each bounded SQL operation."""

    def __init__(self, connection, check):
        self.connection = connection
        self.check = check

    def execute(self, *args):
        self.check()
        result = self.connection.execute(*args)
        self.check()
        return result


def moneyflow_row_count_baseline(
    *,
    instance,
    connection,
    lake_root: Path,
    dataset: str,
    trade_date: str,
    check=lambda: None,
) -> dict:
    """Never skip an invalid recent baseline to find a more permissive old count."""
    day = market_moneyflow_day(trade_date)
    contract = next(
        (
            c
            for c in (
                INDUSTRY_THS_MONEYFLOW_AUTOMATION,
                CONCEPT_THS_MONEYFLOW_AUTOMATION,
                BOARD_DC_MONEYFLOW_AUTOMATION,
                STOCK_DC_MONEYFLOW_AUTOMATION,
                STOCK_THS_MONEYFLOW_AUTOMATION,
                STOCK_MONEYFLOW_AUTOMATION,
            )
            if c.dataset == dataset
        ),
        None,
    )
    if contract is None:
        raise MoneyflowContractError("row_count_dataset")
    check()
    partitions = instance.get_materialized_partitions(dg.AssetKey(contract.raw_asset))
    check()
    if len(partitions) > MONEYFLOW_HISTORY_MAX_DATE_FACTS:
        raise MoneyflowContractError("row_count_baseline_date_budget")
    previous = sorted(
        (market_moneyflow_day(d) for d in partitions if d < day), reverse=True
    )
    dates = tuple(sorted(previous[:MONEYFLOW_ROW_COUNT_BASELINE_DAYS]))
    mode = "previous_five"
    if len(dates) < MONEYFLOW_ROW_COUNT_BASELINE_DAYS:
        if day <= MONEYFLOW_ROW_COUNT_FALLBACK_DATE:
            raise MoneyflowContractError("row_count_baseline_missing")
        dates = (MONEYFLOW_ROW_COUNT_FALLBACK_DATE,)
        mode = "bootstrap_cutoff"
    check()
    deliveries = batch_moneyflow_readiness(
        instance, lake_root, dates, contract=contract, layers=("raw",)
    )["raw"]
    check()
    queries = _BaselineQueries(connection, check)
    references = []
    for reference_day in dates:
        delivery = deliveries[reference_day]
        if not delivery.ready:
            raise MoneyflowContractError(
                "row_count_baseline_not_ready:" + delivery.reason
            )
        path = raw_moneyflow_path(lake_root, dataset, reference_day)
        check()
        count = audit_daily_moneyflow_file(
            queries, path, reference_day, dataset=dataset
        )
        counts = daily_file_scope_counts(queries, path, dataset=dataset)
        check()
        recorded = delivery.record.asset_materialization.metadata.get(
            "dagster/row_count"
        )
        if (
            recorded is None
            or type(recorded.value) is not int
            or recorded.value != count
        ):
            raise MoneyflowContractError("row_count_baseline_count")
        if (
            dataset == "moneyflow_ind_dc"
            and delivery.metadata.get("scope_row_counts") != counts
        ):
            raise MoneyflowContractError("row_count_baseline_scopes")
        if candidate_file_hash(path) != delivery.metadata["file_sha256"]:
            raise MoneyflowContractError("row_count_baseline_changed")
        check()
        references.append(
            {
                "date": reference_day,
                "row_count": count,
                "scope_row_counts": counts,
                "file_sha256": delivery.metadata["file_sha256"],
                "materialization_storage_id": delivery.record.storage_id,
            }
        )
    return {
        "mode": mode,
        "references": references,
        "baseline_scope_counts": {
            scope: int(median(r["scope_row_counts"][scope] for r in references))
            for scope in references[0]["scope_row_counts"]
        },
    }


def moneyflow_row_count_decision(baseline: dict, candidate_counts: dict) -> dict:
    expected = baseline["baseline_scope_counts"]
    if set(candidate_counts) != set(expected) or any(
        type(n) is not int or n <= 0 for n in candidate_counts.values()
    ):
        raise MoneyflowContractError("row_count_candidate_scopes")
    declined = sorted(
        scope
        for scope, n in candidate_counts.items()
        if n * 100 < expected[scope] * (100 - MONEYFLOW_ROW_COUNT_MAX_DROP_PERCENT)
    )
    return {
        "revision": "moneyflow_row_count_v1",
        **baseline,
        "max_drop_percent": MONEYFLOW_ROW_COUNT_MAX_DROP_PERCENT,
        "candidate_scope_counts": candidate_counts,
        "declined_scopes": declined,
        "passed": not declined,
        "reason_code": "row_count_drop" if declined else "passed",
    }
