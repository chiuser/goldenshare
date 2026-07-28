"""Prod source-completion gates for the daily stock-minute raw path."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from orchestrator.defs.asset_guards.stk_mins_stock_universe import (
    stk_mins_stock_code_set_hash,
)
from orchestrator.defs.prod_db.stk_mins import (
    ProdStkMinsCodeCoverageProbe,
    ProdStkMinsFrequencyCoverage,
    load_prod_stk_mins_code_coverage,
    probe_prod_stk_mins_code_coverage,
)
from orchestrator.defs.prod_db.stk_mins_task_run import (
    ProdStkMinsTaskRunProbe,
    probe_full_market_stk_mins_task_run,
    probe_full_market_stk_mins_task_run_by_id,
)
from orchestrator.defs.resources import ProdPostgresResource
from orchestrator.defs.run_contracts.stk_mins import (
    ProdStkMinsCompletionReference,
    build_prod_stk_mins_completion_reference,
    normalize_stk_mins_freq,
)


@dataclass(frozen=True, slots=True)
class StkMinsProdSourceReadiness:
    ready: bool
    reason_code: str
    task_run_status: ProdStkMinsTaskRunProbe
    coverage_status: ProdStkMinsCodeCoverageProbe | None
    completion_reference: ProdStkMinsCompletionReference | None


def stk_mins_prod_source_ready_for_trade_date(
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    stock_codes: Sequence[str],
    observed_at: datetime,
) -> StkMinsProdSourceReadiness:
    """Prove prod completion once before the sensor submits all five raw assets."""

    task_run_status = probe_full_market_stk_mins_task_run(
        prod_postgres=prod_postgres,
        trade_date=trade_date,
    )
    if not task_run_status.ready or task_run_status.task_run is None:
        return StkMinsProdSourceReadiness(
            ready=False,
            reason_code=task_run_status.reason_code,
            task_run_status=task_run_status,
            coverage_status=None,
            completion_reference=None,
        )

    coverage_status = probe_prod_stk_mins_code_coverage(
        prod_postgres=prod_postgres,
        trade_date=trade_date,
        stock_codes=stock_codes,
    )
    if not coverage_status.ready:
        return StkMinsProdSourceReadiness(
            ready=False,
            reason_code=coverage_status.reason_code,
            task_run_status=task_run_status,
            coverage_status=coverage_status,
            completion_reference=None,
        )

    reference = build_prod_stk_mins_completion_reference(
        task_run_id=task_run_status.task_run.task_run_id,
        trade_date=trade_date,
        ended_at=task_run_status.task_run.ended_at,
        expected_code_count=len(stock_codes),
        expected_code_hash=stk_mins_stock_code_set_hash(stock_codes),
        frequency_code_counts={
            coverage.freq: coverage.present_code_count
            for coverage in coverage_status.frequency_coverages
        },
        coverage_observed_at=observed_at.isoformat(),
    )
    return StkMinsProdSourceReadiness(
        ready=True,
        reason_code="prod_source_ready",
        task_run_status=task_run_status,
        coverage_status=coverage_status,
        completion_reference=reference,
    )


def validate_stk_mins_prod_completion_reference(
    *,
    prod_postgres: ProdPostgresResource,
    partition_key: str,
    freq: int | str,
    stock_codes: Sequence[str],
    completion_reference: ProdStkMinsCompletionReference,
) -> ProdStkMinsFrequencyCoverage:
    """Fail before any raw write when the sensor's prod fact is no longer true."""

    normalized_freq = normalize_stk_mins_freq(freq)
    completion_reference.validate()
    if completion_reference.trade_date != partition_key:
        raise RuntimeError(
            "prod_completion_reference trade_date does not match asset partition."
        )
    expected_code_hash = stk_mins_stock_code_set_hash(stock_codes)
    if (
        completion_reference.expected_code_count != len(stock_codes)
        or completion_reference.expected_code_hash != expected_code_hash
    ):
        raise RuntimeError(
            "prod_completion_reference does not match the current stk_mins stock universe."
        )

    task_run_status = probe_full_market_stk_mins_task_run_by_id(
        prod_postgres=prod_postgres,
        task_run_id=completion_reference.task_run_id,
        trade_date=partition_key,
    )
    task_run = task_run_status.task_run
    if (
        not task_run_status.ready
        or task_run is None
        or task_run.ended_at != completion_reference.ended_at
    ):
        raise RuntimeError(
            "prod_completion_reference TaskRun is missing, invalid, or changed."
        )

    frequency_coverages = load_prod_stk_mins_code_coverage(
        prod_postgres=prod_postgres,
        trade_date=partition_key,
        stock_codes=stock_codes,
        freqs=(normalized_freq,),
    )
    coverage = frequency_coverages[0]
    expected_reference_counts = dict(completion_reference.frequency_code_counts)
    if (
        not coverage.ready
        or coverage.present_code_count != expected_reference_counts[normalized_freq]
    ):
        raise RuntimeError(
            "prod_completion_reference source coverage is incomplete or changed."
        )
    return coverage
