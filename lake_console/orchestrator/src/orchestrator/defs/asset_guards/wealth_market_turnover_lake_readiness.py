"""Lake readiness for gold wealth market turnover sensor hot paths."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from orchestrator.defs.paths import gold_wealth_market_turnover_path
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_CONTINUITY_WINDOW_LIMIT
from orchestrator.defs.wealth_market_turnover_contract import (
    WEALTH_MARKET_TURNOVER_CHECK_NAME,
    audit_gold_wealth_market_turnover_file_contract,
    audit_gold_wealth_market_turnover_recomputed_from_silver,
    wealth_market_turnover_input_paths,
)


@dataclass(frozen=True)
class WealthMarketTurnoverDateReadiness:
    trade_date: str
    ready: bool
    materialized: bool
    checks_passed: bool
    reason: str
    failed_check_names: tuple[str, ...] = ()
    missing_file_paths: tuple[str, ...] = ()
    checked_row_count: int = 0
    failed_row_count: int = 0
    sample_rows: tuple[dict[str, object], ...] = ()
    summary: Mapping[str, object] = field(default_factory=dict)

    def to_cursor_details(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "ready": self.ready,
            "materialized": self.materialized,
            "checks_passed": self.checks_passed,
            "reason": self.reason,
            "failed_check_names": list(self.failed_check_names),
            "missing_file_paths": list(self.missing_file_paths),
            "checked_row_count": self.checked_row_count,
            "failed_row_count": self.failed_row_count,
            "sample_rows": list(self.sample_rows),
            "summary": dict(self.summary),
        }


@dataclass(frozen=True)
class WealthMarketTurnoverBatchReadiness:
    dataset: str
    expected_start_date: str | None
    expected_end_date: str | None
    expected_count: int
    elapsed_ms: float
    statuses_by_trade_date: Mapping[str, WealthMarketTurnoverDateReadiness]

    def status_for_trade_date(self, trade_date: str) -> WealthMarketTurnoverDateReadiness:
        try:
            return self.statuses_by_trade_date[trade_date]
        except KeyError as error:
            raise KeyError(f"Unknown wealth market turnover trade date: {trade_date}") from error


def batch_gold_wealth_market_turnover_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
) -> WealthMarketTurnoverBatchReadiness:
    started_at = perf_counter()
    trade_dates = tuple(dict.fromkeys(str(date) for date in expected_trade_dates))
    if len(trade_dates) > STK_MINS_CONTINUITY_WINDOW_LIMIT:
        raise ValueError(
            "gold wealth market turnover readiness window exceeds "
            f"{STK_MINS_CONTINUITY_WINDOW_LIMIT} trade dates."
        )
    statuses = {
        trade_date: _status_for_trade_date(
            connection=connection,
            lake_root=lake_root,
            trade_date=trade_date,
        )
        for trade_date in trade_dates
    }
    elapsed_ms = (perf_counter() - started_at) * 1000
    return WealthMarketTurnoverBatchReadiness(
        dataset="gold_wealth_market_turnover",
        expected_start_date=trade_dates[0] if trade_dates else None,
        expected_end_date=trade_dates[-1] if trade_dates else None,
        expected_count=len(trade_dates),
        elapsed_ms=elapsed_ms,
        statuses_by_trade_date=statuses,
    )


def _status_for_trade_date(
    *,
    connection,
    lake_root: Path,
    trade_date: str,
) -> WealthMarketTurnoverDateReadiness:
    target_path = gold_wealth_market_turnover_path(lake_root, trade_date)
    input_paths = wealth_market_turnover_input_paths(lake_root, trade_date)
    file_audit = audit_gold_wealth_market_turnover_file_contract(
        connection=connection,
        target_path=target_path,
        partition_key=trade_date,
    )
    if not file_audit.passed:
        return WealthMarketTurnoverDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=target_path.exists(),
            checks_passed=False,
            reason=file_audit.reason_code or "file_contract_failed",
            failed_check_names=(WEALTH_MARKET_TURNOVER_CHECK_NAME,),
            missing_file_paths=file_audit.missing_file_paths,
            checked_row_count=file_audit.checked_row_count,
            failed_row_count=file_audit.failed_row_count,
            sample_rows=file_audit.sample_rows,
            summary=file_audit.metadata,
        )

    recompute_audit = audit_gold_wealth_market_turnover_recomputed_from_silver(
        connection=connection,
        target_path=target_path,
        input_paths=input_paths,
        partition_key=trade_date,
    )
    if not recompute_audit.passed:
        return WealthMarketTurnoverDateReadiness(
            trade_date=trade_date,
            ready=False,
            materialized=True,
            checks_passed=False,
            reason=recompute_audit.reason_code or "recomputed_from_silver_failed",
            failed_check_names=(WEALTH_MARKET_TURNOVER_CHECK_NAME,),
            missing_file_paths=recompute_audit.missing_file_paths,
            checked_row_count=recompute_audit.checked_row_count,
            failed_row_count=recompute_audit.failed_row_count,
            sample_rows=recompute_audit.sample_rows,
            summary=recompute_audit.metadata,
        )

    return WealthMarketTurnoverDateReadiness(
        trade_date=trade_date,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason="ready",
        checked_row_count=recompute_audit.checked_row_count,
        summary=recompute_audit.metadata,
    )
