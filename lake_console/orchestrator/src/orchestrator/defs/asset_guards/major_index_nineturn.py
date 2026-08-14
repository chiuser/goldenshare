"""Bounded physical readiness for major-index nine-turn targets."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.major_index_nineturn_integrity import (
    audit_major_index_nineturn_integrity,
)
from orchestrator.defs.paths import (
    gold_major_index_daily_nineturn_path,
    gold_major_index_mins_nineturn_path,
    gold_major_index_mins_path,
    gold_market_major_indices_daily_path,
)
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_MINUTE_FREQS,
)

MAX_MAJOR_INDEX_NINETURN_READINESS_DATES = 10


def batch_gold_major_index_nineturn_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    minute: bool,
) -> ContinuityBatchReadiness:
    dates = tuple(sorted(set(expected_trade_dates)))
    if len(dates) > MAX_MAJOR_INDEX_NINETURN_READINESS_DATES:
        raise ValueError("Major-index nine-turn readiness is limited to 10 dates.")
    started = perf_counter()
    statuses: dict[str, ContinuityDateReadiness] = {}
    scanned_file_count = 0
    for trade_date in dates:
        specs = (
            tuple(
                (
                    gold_major_index_mins_nineturn_path(lake_root, freq, trade_date),
                    gold_major_index_mins_path(lake_root, freq, trade_date),
                    freq,
                )
                for freq in MAJOR_INDEX_NINETURN_MINUTE_FREQS
            )
            if minute
            else (
                (
                    gold_major_index_daily_nineturn_path(lake_root, trade_date),
                    gold_market_major_indices_daily_path(lake_root, trade_date),
                    None,
                ),
            )
        )
        missing_targets = tuple(
            str(target) for target, _source, _freq in specs if not target.is_file()
        )
        scanned_file_count += sum(target.is_file() for target, _source, _freq in specs)
        if missing_targets:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="target_files_missing",
                missing_file_paths=missing_targets,
            )
            continue
        failed_names: list[str] = []
        for target, source, freq in specs:
            diagnostics = audit_major_index_nineturn_integrity(
                connection,
                target_path=target,
                source_paths=(source,),
                partition_key=trade_date,
                freq=freq,
            )
            if not diagnostics.passed:
                suffix = "daily" if freq is None else f"{freq}m"
                failed_names.extend(
                    f"{suffix}:{rule}" for rule in diagnostics.failed_rule_names
                )
        statuses[trade_date] = ContinuityDateReadiness(
            trade_date=trade_date,
            ready=not failed_names,
            materialized=True,
            checks_passed=not failed_names,
            reason="ready" if not failed_names else "target_integrity_failed",
            failed_check_names=tuple(failed_names),
        )
    return ContinuityBatchReadiness(
        expected_trade_dates=dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=int((perf_counter() - started) * 1000),
        scanned_file_count=scanned_file_count,
    )


__all__ = ["batch_gold_major_index_nineturn_readiness"]
