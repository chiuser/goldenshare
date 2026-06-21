"""Repair-aware gold qfq readiness helpers for downstream consumers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsDateReadiness,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
)
from orchestrator.defs.checks.stk_mins_checks import (
    GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK,
    GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE,
    _gold_qfq_expected_paths,
    _read_parquet_paths,
)
from orchestrator.defs.paths import silver_adj_factor_path, silver_stk_mins_path
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_QFQ_NATIVE_FREQS
from orchestrator.defs.stk_mins_qfq import build_daily_qfq_select_sql


QFQ_EFFECTIVE_READINESS_FORMULA_MISMATCH_CODE_LIMIT = 1000
QFQ_EFFECTIVE_READINESS_REASON = "ready_after_qfq_factor_repair"


@dataclass(frozen=True)
class GoldQfqEffectiveReadinessResult:
    status: StkMinsDateReadiness
    repair_adjusted: bool = False
    covering_repair_trade_dates: tuple[str, ...] = ()
    covering_upstream_batch_ids: tuple[str, ...] = ()
    formula_mismatch_code_count: int = 0
    formula_mismatch_code_samples: tuple[str, ...] = ()
    failure_reason: str | None = None

    @property
    def ready(self) -> bool:
        return self.status.ready


def _normalize_trade_dates(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _only_same_day_formula_check_failed(status: StkMinsDateReadiness) -> bool:
    return (
        status.materialized
        and not status.ready
        and set(status.failed_check_names)
        == {GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK}
    )


def gold_qfq_status_requires_repair_aware_check(
    status: StkMinsDateReadiness,
) -> bool:
    return _only_same_day_formula_check_failed(status)


def _effective_ready_status(
    status: StkMinsDateReadiness,
    *,
    repair_trade_dates: Sequence[str],
    upstream_batch_ids: Sequence[str],
    mismatch_codes: Sequence[str],
) -> StkMinsDateReadiness:
    return StkMinsDateReadiness(
        trade_date=status.trade_date,
        ready=True,
        materialized=status.materialized,
        checks_passed=True,
        reason=QFQ_EFFECTIVE_READINESS_REASON,
        failed_check_names=(),
        missing_file_paths=status.missing_file_paths,
        expected_file_count=status.expected_file_count,
        existing_file_count=status.existing_file_count,
        checked_row_count=status.checked_row_count,
        failed_row_count=0,
        sample_rows=(
            {
                "effective_readiness": QFQ_EFFECTIVE_READINESS_REASON,
                "covering_repair_trade_dates": list(repair_trade_dates),
                "covering_upstream_batch_ids": list(upstream_batch_ids),
                "formula_mismatch_code_count": len(mismatch_codes),
                "formula_mismatch_code_samples": list(mismatch_codes[:10]),
            },
        ),
    )


def _status_with_effective_failure_reason(
    status: StkMinsDateReadiness,
    reason: str,
) -> StkMinsDateReadiness:
    return StkMinsDateReadiness(
        trade_date=status.trade_date,
        ready=False,
        materialized=status.materialized,
        checks_passed=False,
        reason=reason,
        failed_check_names=status.failed_check_names,
        missing_file_paths=status.missing_file_paths,
        expected_file_count=status.expected_file_count,
        existing_file_count=status.existing_file_count,
        checked_row_count=status.checked_row_count,
        failed_row_count=status.failed_row_count,
        sample_rows=status.sample_rows,
    )


def _formula_mismatch_codes_for_freq(
    connection,
    *,
    lake_root: Path,
    trade_date: str,
    freq: int,
    limit: int,
) -> tuple[str, ...]:
    silver_path = silver_stk_mins_path(lake_root, freq, trade_date)
    trade_adj_factor_path = silver_adj_factor_path(lake_root, trade_date)
    if not silver_path.exists() or not trade_adj_factor_path.exists():
        return ()

    gold_paths = tuple(
        path
        for path in _gold_qfq_expected_paths(
            connection,
            lake_root=lake_root,
            freq=freq,
            partition_key=trade_date,
            silver_path=silver_path,
        )
        if path.exists()
    )
    if not gold_paths:
        return ()

    gold_source = _read_parquet_paths(gold_paths, filename=True)
    qfq_select_sql = build_daily_qfq_select_sql(
        silver_paths=[silver_path],
        trade_adj_factor_paths=[trade_adj_factor_path],
        as_of_adj_factor_paths=[trade_adj_factor_path],
    )
    rows = connection.execute(
        f"""
        WITH gold_rows AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close
          FROM {gold_source}
          WHERE CAST(freq AS INTEGER) = {int(freq)}
            AND CAST(trade_date AS DATE) = CAST('{trade_date}' AS DATE)
        ),
        expected_rows AS (
          {qfq_select_sql}
        ),
        compared_rows AS (
          SELECT
            coalesce(gold_rows.ts_code, expected_rows.ts_code) AS ts_code,
            gold_rows.ts_code IS NULL AS missing_gold_row,
            expected_rows.ts_code IS NULL AS unexpected_gold_row,
            gold_rows.open AS gold_open,
            expected_rows.open AS expected_open,
            gold_rows.high AS gold_high,
            expected_rows.high AS expected_high,
            gold_rows.low AS gold_low,
            expected_rows.low AS expected_low,
            gold_rows.close AS gold_close,
            expected_rows.close AS expected_close
          FROM gold_rows
          FULL OUTER JOIN expected_rows
            ON gold_rows.ts_code = expected_rows.ts_code
           AND gold_rows.trade_time = expected_rows.trade_time
        )
        SELECT DISTINCT ts_code
        FROM compared_rows
        WHERE missing_gold_row
           OR unexpected_gold_row
           OR (
             NOT missing_gold_row
             AND NOT unexpected_gold_row
             AND (
               abs(gold_open - expected_open) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
               OR abs(gold_high - expected_high) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
               OR abs(gold_low - expected_low) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
               OR abs(gold_close - expected_close) > {GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE}
             )
           )
        ORDER BY ts_code
        LIMIT {int(limit) + 1}
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows if row[0] is not None)


def gold_qfq_formula_mismatch_codes(
    connection,
    *,
    lake_root: Path,
    trade_date: str,
    limit: int = QFQ_EFFECTIVE_READINESS_FORMULA_MISMATCH_CODE_LIMIT,
) -> tuple[str, ...]:
    mismatch_codes: set[str] = set()
    for freq in STK_MINS_QFQ_NATIVE_FREQS:
        for code in _formula_mismatch_codes_for_freq(
            connection,
            lake_root=lake_root,
            trade_date=trade_date,
            freq=freq,
            limit=limit,
        ):
            mismatch_codes.add(code)
            if len(mismatch_codes) > limit:
                return tuple(sorted(mismatch_codes))
    return tuple(sorted(mismatch_codes))


def _repair_status_covers_trade_date(
    status: GoldStkMinsQfqFactorRepairStatus,
    trade_date: str,
) -> bool:
    return (
        status.ready
        and status.repair_required
        and status.repair_required_codes_hash is not None
        and not status.repair_required_codes_truncated
        and status.repair_start_trade_date is not None
        and status.repair_end_trade_date is not None
        and status.repair_start_trade_date <= trade_date <= status.repair_end_trade_date
    )


def effective_gold_qfq_readiness_for_trade_date(
    *,
    connection,
    lake_root: Path,
    trade_date: str,
    lake_status: StkMinsDateReadiness,
    candidate_repair_trade_dates: Sequence[str],
    repair_status_for_trade_date: Callable[[str], GoldStkMinsQfqFactorRepairStatus],
    mismatch_code_limit: int = QFQ_EFFECTIVE_READINESS_FORMULA_MISMATCH_CODE_LIMIT,
) -> GoldQfqEffectiveReadinessResult:
    if lake_status.ready:
        return GoldQfqEffectiveReadinessResult(status=lake_status)
    if not _only_same_day_formula_check_failed(lake_status):
        return GoldQfqEffectiveReadinessResult(status=lake_status)

    mismatch_codes = gold_qfq_formula_mismatch_codes(
        connection,
        lake_root=lake_root,
        trade_date=trade_date,
        limit=mismatch_code_limit,
    )
    if len(mismatch_codes) > mismatch_code_limit:
        reason = (
            "gold qfq formula mismatch code count exceeds repair-aware "
            f"limit for {trade_date}: limit={mismatch_code_limit}"
        )
        return GoldQfqEffectiveReadinessResult(
            status=_status_with_effective_failure_reason(lake_status, reason),
            formula_mismatch_code_count=len(mismatch_codes),
            formula_mismatch_code_samples=mismatch_codes[:10],
            failure_reason=reason,
        )
    if not mismatch_codes:
        reason = f"gold qfq formula mismatch codes are empty for {trade_date}"
        return GoldQfqEffectiveReadinessResult(
            status=_status_with_effective_failure_reason(lake_status, reason),
            failure_reason=reason,
        )

    covering_statuses: list[GoldStkMinsQfqFactorRepairStatus] = []
    covered_codes: set[str] = set()
    for repair_trade_date in _normalize_trade_dates(candidate_repair_trade_dates):
        if repair_trade_date < trade_date:
            continue
        repair_status = repair_status_for_trade_date(repair_trade_date)
        if not _repair_status_covers_trade_date(repair_status, trade_date):
            continue
        covering_statuses.append(repair_status)
        covered_codes.update(repair_status.repair_required_codes)

    uncovered_codes = tuple(sorted(set(mismatch_codes) - covered_codes))
    if uncovered_codes:
        reason = (
            "gold qfq formula mismatch codes are not covered by ready "
            f"qfq factor repair metadata for {trade_date}"
        )
        return GoldQfqEffectiveReadinessResult(
            status=_status_with_effective_failure_reason(lake_status, reason),
            formula_mismatch_code_count=len(mismatch_codes),
            formula_mismatch_code_samples=mismatch_codes[:10],
            failure_reason=reason,
        )

    repair_trade_dates = tuple(status.trade_date for status in covering_statuses)
    upstream_batch_ids = tuple(
        status.upstream_batch_id
        for status in covering_statuses
        if status.upstream_batch_id is not None
    )
    effective_status = _effective_ready_status(
        lake_status,
        repair_trade_dates=repair_trade_dates,
        upstream_batch_ids=upstream_batch_ids,
        mismatch_codes=mismatch_codes,
    )
    return GoldQfqEffectiveReadinessResult(
        status=effective_status,
        repair_adjusted=True,
        covering_repair_trade_dates=repair_trade_dates,
        covering_upstream_batch_ids=upstream_batch_ids,
        formula_mismatch_code_count=len(mismatch_codes),
        formula_mismatch_code_samples=mismatch_codes[:10],
    )
