"""Offline bootstrap for the QFQ as-of-factor audit sidecar.

This module is intentionally not imported by Dagster definitions.  Its default
operation is a read-only plan; callers must explicitly request apply before it
can write any Lake file.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stk_mins_qfq_as_of_basis_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.stk_mins_qfq import build_daily_qfq_select_sql_from_as_of_basis
from orchestrator.defs.stk_mins_qfq_as_of_basis import (
    GOLD_STK_MINS_QFQ_AS_OF_BASIS_FACTOR_TOLERANCE,
    write_gold_stk_mins_qfq_as_of_basis,
)


QFQ_AS_OF_BASIS_BOOTSTRAP_FORMULA_TOLERANCE = 1e-6


@dataclass(frozen=True)
class StkMinsQfqAsOfBasisBootstrapYearPlan:
    year: str
    trade_date_count: int
    silver_file_count: int
    qfq_file_count: int
    adj_factor_file_count: int
    source_code_day_count: int
    candidate_basis_row_count: int
    invalid_code_day_count: int
    silver_row_count: int
    qfq_row_count: int
    planned_replacement_row_count: int
    existing_basis_file: bool
    missing_input_samples: tuple[str, ...]


@dataclass(frozen=True)
class StkMinsQfqAsOfBasisBootstrapPlan:
    selected_trade_dates: tuple[str, ...]
    year_plans: tuple[StkMinsQfqAsOfBasisBootstrapYearPlan, ...]
    stop_reasons: tuple[str, ...]
    plan_fingerprint: str

    @property
    def planned_replacement_row_count(self) -> int:
        return sum(
            year_plan.planned_replacement_row_count
            for year_plan in self.year_plans
        )

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    def to_report(self) -> dict[str, object]:
        return {
            "selected_trade_dates": list(self.selected_trade_dates),
            "year_plans": [asdict(year_plan) for year_plan in self.year_plans],
            "planned_replacement_row_count": self.planned_replacement_row_count,
            "should_stop": self.should_stop,
            "stop_reasons": list(self.stop_reasons),
            "plan_fingerprint": self.plan_fingerprint,
        }


@dataclass(frozen=True)
class StkMinsQfqAsOfBasisBootstrapAudit:
    selected_trade_dates: tuple[str, ...]
    expected_qfq_row_count: int
    actual_qfq_row_count: int
    missing_gold_row_count: int
    unexpected_gold_row_count: int
    formula_mismatch_row_count: int

    @property
    def passed(self) -> bool:
        return (
            self.expected_qfq_row_count > 0
            and self.expected_qfq_row_count == self.actual_qfq_row_count
            and self.missing_gold_row_count == 0
            and self.unexpected_gold_row_count == 0
            and self.formula_mismatch_row_count == 0
        )

    def to_report(self) -> dict[str, object]:
        return {
            **asdict(self),
            "selected_trade_dates": list(self.selected_trade_dates),
            "passed": self.passed,
        }


@dataclass(frozen=True)
class StkMinsQfqAsOfBasisBootstrapApplyReport:
    plan: StkMinsQfqAsOfBasisBootstrapPlan
    written_years: tuple[str, ...]
    audit: StkMinsQfqAsOfBasisBootstrapAudit

    def to_report(self) -> dict[str, object]:
        return {
            "plan": self.plan.to_report(),
            "written_years": list(self.written_years),
            "audit": self.audit.to_report(),
        }


def plan_stk_mins_qfq_as_of_basis_bootstrap(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    partition_keys: Sequence[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> StkMinsQfqAsOfBasisBootstrapPlan:
    """Build a read-only, annual bootstrap plan from actual 1m Lake files."""

    selected_trade_dates = _select_trade_dates(
        lake_root=lake_root,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
    )
    year_plans: list[StkMinsQfqAsOfBasisBootstrapYearPlan] = []
    stop_reasons: list[str] = []
    for year, trade_dates in _group_trade_dates_by_year(selected_trade_dates).items():
        year_plan = _plan_year(
            lake_root=lake_root,
            year=year,
            trade_dates=trade_dates,
        )
        year_plans.append(year_plan)
        if year_plan.existing_basis_file:
            stop_reasons.append(f"basis_target_already_exists:{year}")
        if year_plan.missing_input_samples:
            stop_reasons.append(f"missing_inputs:{year}")
        if year_plan.invalid_code_day_count:
            stop_reasons.append(f"invalid_reconstruction_rows:{year}")
        if (
            not year_plan.missing_input_samples
            and year_plan.candidate_basis_row_count
            != year_plan.source_code_day_count
        ):
            stop_reasons.append(f"basis_coverage_incomplete:{year}")

    normalized_year_plans = tuple(year_plans)
    return StkMinsQfqAsOfBasisBootstrapPlan(
        selected_trade_dates=selected_trade_dates,
        year_plans=normalized_year_plans,
        stop_reasons=tuple(stop_reasons),
        plan_fingerprint=_plan_fingerprint(
            selected_trade_dates=selected_trade_dates,
            year_plans=normalized_year_plans,
        ),
    )


def apply_stk_mins_qfq_as_of_basis_bootstrap(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    partition_keys: Sequence[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    expected_plan_fingerprint: str,
) -> StkMinsQfqAsOfBasisBootstrapApplyReport:
    """Write a previously reviewed plan, then audit the real QFQ formula."""

    plan = plan_stk_mins_qfq_as_of_basis_bootstrap(
        lake_root=lake_root,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
    )
    if plan.plan_fingerprint != expected_plan_fingerprint:
        raise RuntimeError(
            "QFQ as-of basis bootstrap plan changed before apply; refusing write."
        )
    if plan.should_stop:
        raise RuntimeError(
            "QFQ as-of basis bootstrap plan is blocked: "
            f"{plan.stop_reasons}."
        )

    written_years: list[str] = []
    for year_plan in plan.year_plans:
        year_dates = tuple(
            trade_date
            for trade_date in plan.selected_trade_dates
            if trade_date.startswith(year_plan.year)
        )
        result = write_gold_stk_mins_qfq_as_of_basis(
            lake_root=lake_root,
            replacement_rows_sql=build_qfq_as_of_basis_history_reconstruction_sql(
                lake_root=lake_root,
                year=year_plan.year,
                trade_dates=year_dates,
            ),
        )
        if len(result) != 1 or result[0].year != year_plan.year:
            raise RuntimeError(
                "QFQ as-of basis bootstrap wrote an unexpected year result: "
                f"expected={year_plan.year}, observed={result}."
            )
        written_years.append(year_plan.year)

    audit = audit_stk_mins_qfq_as_of_basis_bootstrap(
        lake_root=lake_root,
        partition_keys=plan.selected_trade_dates,
    )
    if not audit.passed:
        raise RuntimeError(
            "QFQ as-of basis bootstrap formula audit failed after write: "
            f"{audit.to_report()}."
        )
    return StkMinsQfqAsOfBasisBootstrapApplyReport(
        plan=plan,
        written_years=tuple(written_years),
        audit=audit,
    )


def audit_stk_mins_qfq_as_of_basis_bootstrap(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    partition_keys: Sequence[str],
) -> StkMinsQfqAsOfBasisBootstrapAudit:
    """Compare native 1m QFQ files with the real formula based on the sidecar."""

    selected_trade_dates = _normalize_trade_dates(partition_keys)
    source_paths = _source_paths_by_year(
        lake_root=lake_root,
        trade_dates=selected_trade_dates,
    )
    with connect_configured_duckdb() as connection:
        row = connection.execute(
            _formula_audit_sql(
                silver_paths=source_paths.silver_paths,
                qfq_paths=source_paths.qfq_paths,
                trade_adj_factor_paths=source_paths.adj_factor_paths,
                basis_paths=source_paths.basis_paths,
                trade_dates=selected_trade_dates,
            )
        ).fetchone()
    if row is None:
        raise RuntimeError("QFQ as-of basis formula audit returned no row.")
    return StkMinsQfqAsOfBasisBootstrapAudit(
        selected_trade_dates=selected_trade_dates,
        expected_qfq_row_count=int(row[0] or 0),
        actual_qfq_row_count=int(row[1] or 0),
        missing_gold_row_count=int(row[2] or 0),
        unexpected_gold_row_count=int(row[3] or 0),
        formula_mismatch_row_count=int(row[4] or 0),
    )


def build_qfq_as_of_basis_history_reconstruction_sql(
    *,
    lake_root: Path,
    year: str,
    trade_dates: Sequence[str],
) -> str:
    """Return only complete, stable code-day basis facts for one annual batch."""

    normalized_dates = _normalize_trade_dates(trade_dates)
    paths = _source_paths_for_year(
        lake_root=lake_root,
        year=year,
        trade_dates=normalized_dates,
        include_basis=False,
    )
    return _history_reconstruction_sql(
        silver_paths=paths.silver_paths,
        qfq_paths=paths.qfq_paths,
        adj_factor_paths=paths.adj_factor_paths,
        trade_dates=normalized_dates,
        select_mode="replacement_rows",
    )


@dataclass(frozen=True)
class _SourcePaths:
    silver_paths: tuple[Path, ...]
    qfq_paths: tuple[Path, ...]
    adj_factor_paths: tuple[Path, ...]
    basis_paths: tuple[Path, ...]


def _plan_year(
    *,
    lake_root: Path,
    year: str,
    trade_dates: tuple[str, ...],
) -> StkMinsQfqAsOfBasisBootstrapYearPlan:
    paths = _source_paths_for_year(
        lake_root=lake_root,
        year=year,
        trade_dates=trade_dates,
        include_basis=True,
    )
    missing_inputs = _missing_year_inputs(paths=paths, year=year)
    if missing_inputs:
        return StkMinsQfqAsOfBasisBootstrapYearPlan(
            year=year,
            trade_date_count=len(trade_dates),
            silver_file_count=len(paths.silver_paths),
            qfq_file_count=len(paths.qfq_paths),
            adj_factor_file_count=len(paths.adj_factor_paths),
            source_code_day_count=0,
            candidate_basis_row_count=0,
            invalid_code_day_count=0,
            silver_row_count=0,
            qfq_row_count=0,
            planned_replacement_row_count=0,
            existing_basis_file=bool(paths.basis_paths),
            missing_input_samples=tuple(missing_inputs[:20]),
        )
    with connect_configured_duckdb() as connection:
        row = connection.execute(
            _history_reconstruction_sql(
                silver_paths=paths.silver_paths,
                qfq_paths=paths.qfq_paths,
                adj_factor_paths=paths.adj_factor_paths,
                trade_dates=trade_dates,
                select_mode="plan_counts",
            )
        ).fetchone()
    if row is None:
        raise RuntimeError(f"QFQ as-of basis plan query returned no row: year={year}.")
    return StkMinsQfqAsOfBasisBootstrapYearPlan(
        year=year,
        trade_date_count=len(trade_dates),
        silver_file_count=len(paths.silver_paths),
        qfq_file_count=len(paths.qfq_paths),
        adj_factor_file_count=len(paths.adj_factor_paths),
        source_code_day_count=int(row[0] or 0),
        candidate_basis_row_count=int(row[1] or 0),
        invalid_code_day_count=int(row[2] or 0),
        silver_row_count=int(row[3] or 0),
        qfq_row_count=int(row[4] or 0),
        planned_replacement_row_count=int(row[1] or 0),
        existing_basis_file=bool(paths.basis_paths),
        missing_input_samples=(),
    )


def _history_reconstruction_sql(
    *,
    silver_paths: Sequence[Path],
    qfq_paths: Sequence[Path],
    adj_factor_paths: Sequence[Path],
    trade_dates: Sequence[str],
    select_mode: str,
) -> str:
    if select_mode not in {"plan_counts", "replacement_rows"}:
        raise ValueError(f"Unsupported QFQ basis reconstruction mode: {select_mode}.")
    selected_dates = _date_values_sql(trade_dates)
    silver_source = _read_parquet_paths(silver_paths)
    qfq_source = _read_parquet_paths(qfq_paths)
    factor_source = _read_parquet_paths(adj_factor_paths)
    common = f"""
WITH selected_dates(trade_date) AS (VALUES {selected_dates}),
silver_rows AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(trade_time AS TIMESTAMP) AS trade_time,
    CAST(open AS DOUBLE) AS open,
    CAST(high AS DOUBLE) AS high,
    CAST(low AS DOUBLE) AS low,
    CAST(close AS DOUBLE) AS close
  FROM {silver_source}
  WHERE CAST(trade_date AS DATE) IN (SELECT trade_date FROM selected_dates)
),
qfq_rows AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(trade_time AS TIMESTAMP) AS trade_time,
    CAST(open AS DOUBLE) AS open,
    CAST(high AS DOUBLE) AS high,
    CAST(low AS DOUBLE) AS low,
    CAST(close AS DOUBLE) AS close
  FROM {qfq_source}
  WHERE CAST(trade_date AS DATE) IN (SELECT trade_date FROM selected_dates)
),
factor_rows AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(adj_factor AS DOUBLE) AS adj_factor
  FROM {factor_source}
  WHERE CAST(trade_date AS DATE) IN (SELECT trade_date FROM selected_dates)
),
silver_code_days AS (
  SELECT ts_code, trade_date, count(*) AS silver_row_count,
         count(*) - count(DISTINCT trade_time) AS duplicate_silver_time_count
  FROM silver_rows
  GROUP BY ts_code, trade_date
),
qfq_code_days AS (
  SELECT ts_code, trade_date, count(*) AS qfq_row_count,
         count(*) - count(DISTINCT trade_time) AS duplicate_qfq_time_count
  FROM qfq_rows
  GROUP BY ts_code, trade_date
),
factor_code_days AS (
  SELECT ts_code, trade_date, count(*) AS factor_row_count,
         min(adj_factor) AS trade_adj_factor,
         count(*) FILTER (
           WHERE adj_factor IS NULL OR NOT isfinite(adj_factor) OR adj_factor = 0
         ) AS invalid_factor_row_count
  FROM factor_rows
  GROUP BY ts_code, trade_date
),
joined_rows AS (
  SELECT
    silver_rows.ts_code,
    silver_rows.trade_date,
    silver_rows.open AS silver_open,
    silver_rows.high AS silver_high,
    silver_rows.low AS silver_low,
    silver_rows.close AS silver_close,
    qfq_rows.open AS qfq_open,
    qfq_rows.high AS qfq_high,
    qfq_rows.low AS qfq_low,
    qfq_rows.close AS qfq_close,
    factor_code_days.trade_adj_factor
  FROM silver_rows
  LEFT JOIN qfq_rows
    ON silver_rows.ts_code = qfq_rows.ts_code
   AND silver_rows.trade_date = qfq_rows.trade_date
   AND silver_rows.trade_time = qfq_rows.trade_time
  LEFT JOIN factor_code_days
    ON silver_rows.ts_code = factor_code_days.ts_code
   AND silver_rows.trade_date = factor_code_days.trade_date
),
inferred_values AS (
  SELECT joined_rows.ts_code, joined_rows.trade_date, inferred_value
  FROM joined_rows
  CROSS JOIN LATERAL (
    VALUES
      (CASE WHEN qfq_open IS NOT NULL AND qfq_open <> 0
                  AND silver_open IS NOT NULL AND trade_adj_factor IS NOT NULL
             THEN silver_open * trade_adj_factor / qfq_open END),
      (CASE WHEN qfq_high IS NOT NULL AND qfq_high <> 0
                  AND silver_high IS NOT NULL AND trade_adj_factor IS NOT NULL
             THEN silver_high * trade_adj_factor / qfq_high END),
      (CASE WHEN qfq_low IS NOT NULL AND qfq_low <> 0
                  AND silver_low IS NOT NULL AND trade_adj_factor IS NOT NULL
             THEN silver_low * trade_adj_factor / qfq_low END),
      (CASE WHEN qfq_close IS NOT NULL AND qfq_close <> 0
                  AND silver_close IS NOT NULL AND trade_adj_factor IS NOT NULL
             THEN silver_close * trade_adj_factor / qfq_close END)
  ) inferred(inferred_value)
  WHERE inferred_value IS NOT NULL
    AND isfinite(inferred_value)
    AND inferred_value <> 0
),
inferred_code_days AS (
  SELECT
    ts_code,
    trade_date,
    count(*) AS inferred_value_count,
    min(inferred_value) AS inferred_as_of_adj_factor,
    max(inferred_value) AS max_inferred_as_of_adj_factor
  FROM inferred_values
  GROUP BY ts_code, trade_date
),
candidate_basis AS (
  SELECT
    silver_code_days.ts_code,
    silver_code_days.trade_date,
    inferred_code_days.inferred_as_of_adj_factor AS as_of_adj_factor
  FROM silver_code_days
  LEFT JOIN qfq_code_days
    ON silver_code_days.ts_code = qfq_code_days.ts_code
   AND silver_code_days.trade_date = qfq_code_days.trade_date
  LEFT JOIN factor_code_days
    ON silver_code_days.ts_code = factor_code_days.ts_code
   AND silver_code_days.trade_date = factor_code_days.trade_date
  LEFT JOIN inferred_code_days
    ON silver_code_days.ts_code = inferred_code_days.ts_code
   AND silver_code_days.trade_date = inferred_code_days.trade_date
  WHERE silver_code_days.duplicate_silver_time_count = 0
    AND coalesce(qfq_code_days.qfq_row_count, 0) = silver_code_days.silver_row_count
    AND coalesce(qfq_code_days.duplicate_qfq_time_count, 0) = 0
    AND coalesce(factor_code_days.factor_row_count, 0) = 1
    AND coalesce(factor_code_days.invalid_factor_row_count, 0) = 0
    AND coalesce(inferred_code_days.inferred_value_count, 0)
          = silver_code_days.silver_row_count * 4
    AND abs(
          inferred_code_days.max_inferred_as_of_adj_factor
          - inferred_code_days.inferred_as_of_adj_factor
        ) <= {GOLD_STK_MINS_QFQ_AS_OF_BASIS_FACTOR_TOLERANCE}
)
"""
    if select_mode == "replacement_rows":
        return common + """
SELECT
  ts_code,
  trade_date,
  CAST(as_of_adj_factor AS DOUBLE) AS as_of_adj_factor,
  CAST(NULL AS DATE) AS as_of_trade_date,
  'history_reconstruction' AS basis_origin
FROM candidate_basis
ORDER BY trade_date, ts_code
"""
    return common + """
SELECT
  (SELECT count(*) FROM silver_code_days) AS source_code_day_count,
  (SELECT count(*) FROM candidate_basis) AS candidate_basis_row_count,
  (SELECT count(*) FROM silver_code_days)
    - (SELECT count(*) FROM candidate_basis) AS invalid_code_day_count,
  (SELECT count(*) FROM silver_rows) AS silver_row_count,
  (SELECT count(*) FROM qfq_rows) AS qfq_row_count
"""


def _formula_audit_sql(
    *,
    silver_paths: Sequence[Path],
    qfq_paths: Sequence[Path],
    trade_adj_factor_paths: Sequence[Path],
    basis_paths: Sequence[Path],
    trade_dates: Sequence[str],
) -> str:
    selected_dates = _date_values_sql(trade_dates)
    expected_rows_sql = build_daily_qfq_select_sql_from_as_of_basis(
        silver_paths=silver_paths,
        trade_adj_factor_paths=trade_adj_factor_paths,
        as_of_basis_paths=basis_paths,
    )
    return f"""
WITH selected_dates(trade_date) AS (VALUES {selected_dates}),
expected_rows AS (
  SELECT *
  FROM ({expected_rows_sql})
  WHERE trade_date IN (SELECT trade_date FROM selected_dates)
),
gold_rows AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(trade_time AS TIMESTAMP) AS trade_time,
    CAST(open AS DOUBLE) AS open,
    CAST(high AS DOUBLE) AS high,
    CAST(low AS DOUBLE) AS low,
    CAST(close AS DOUBLE) AS close
  FROM {_read_parquet_paths(qfq_paths)}
  WHERE CAST(trade_date AS DATE) IN (SELECT trade_date FROM selected_dates)
),
compared_rows AS (
  SELECT
    expected_rows.ts_code AS expected_ts_code,
    gold_rows.ts_code AS gold_ts_code,
    expected_rows.open AS expected_open,
    expected_rows.high AS expected_high,
    expected_rows.low AS expected_low,
    expected_rows.close AS expected_close,
    gold_rows.open AS gold_open,
    gold_rows.high AS gold_high,
    gold_rows.low AS gold_low,
    gold_rows.close AS gold_close
  FROM expected_rows
  FULL OUTER JOIN gold_rows
    ON expected_rows.ts_code = gold_rows.ts_code
   AND expected_rows.trade_date = gold_rows.trade_date
   AND expected_rows.trade_time = gold_rows.trade_time
)
SELECT
  (SELECT count(*) FROM expected_rows) AS expected_qfq_row_count,
  (SELECT count(*) FROM gold_rows) AS actual_qfq_row_count,
  count(*) FILTER (WHERE expected_ts_code IS NOT NULL AND gold_ts_code IS NULL)
    AS missing_gold_row_count,
  count(*) FILTER (WHERE expected_ts_code IS NULL AND gold_ts_code IS NOT NULL)
    AS unexpected_gold_row_count,
  count(*) FILTER (
    WHERE expected_ts_code IS NOT NULL
      AND gold_ts_code IS NOT NULL
      AND (
        abs(expected_open - gold_open) > {QFQ_AS_OF_BASIS_BOOTSTRAP_FORMULA_TOLERANCE}
        OR abs(expected_high - gold_high) > {QFQ_AS_OF_BASIS_BOOTSTRAP_FORMULA_TOLERANCE}
        OR abs(expected_low - gold_low) > {QFQ_AS_OF_BASIS_BOOTSTRAP_FORMULA_TOLERANCE}
        OR abs(expected_close - gold_close) > {QFQ_AS_OF_BASIS_BOOTSTRAP_FORMULA_TOLERANCE}
      )
  ) AS formula_mismatch_row_count
FROM compared_rows
"""


def _source_paths_by_year(
    *,
    lake_root: Path,
    trade_dates: Sequence[str],
) -> _SourcePaths:
    silver_paths: list[Path] = []
    qfq_paths: list[Path] = []
    adj_factor_paths: list[Path] = []
    basis_paths: list[Path] = []
    for year, year_dates in _group_trade_dates_by_year(trade_dates).items():
        paths = _source_paths_for_year(
            lake_root=lake_root,
            year=year,
            trade_dates=year_dates,
            include_basis=True,
        )
        silver_paths.extend(paths.silver_paths)
        qfq_paths.extend(paths.qfq_paths)
        adj_factor_paths.extend(paths.adj_factor_paths)
        basis_paths.extend(paths.basis_paths)
    missing = _missing_year_inputs(
        paths=_SourcePaths(
            silver_paths=tuple(silver_paths),
            qfq_paths=tuple(qfq_paths),
            adj_factor_paths=tuple(adj_factor_paths),
            basis_paths=tuple(basis_paths),
        ),
        year="selected",
        require_basis=True,
    )
    if missing:
        raise FileNotFoundError(
            "QFQ as-of basis bootstrap audit inputs are missing: "
            f"{tuple(missing[:20])}."
        )
    return _SourcePaths(
        silver_paths=tuple(silver_paths),
        qfq_paths=tuple(qfq_paths),
        adj_factor_paths=tuple(adj_factor_paths),
        basis_paths=tuple(basis_paths),
    )


def _source_paths_for_year(
    *,
    lake_root: Path,
    year: str,
    trade_dates: Sequence[str],
    include_basis: bool,
) -> _SourcePaths:
    qfq_root = lake_root / "gold" / "quote" / "stk_mins_qfq" / "freq=1"
    basis_path = gold_stk_mins_qfq_as_of_basis_path(lake_root, year)
    return _SourcePaths(
        silver_paths=tuple(
            silver_stk_mins_path(lake_root, 1, trade_date)
            for trade_date in trade_dates
        ),
        qfq_paths=tuple(sorted(qfq_root.glob(f"ts_code=*/year={year}/part-000.parquet"))),
        adj_factor_paths=tuple(
            silver_adj_factor_path(lake_root, trade_date)
            for trade_date in trade_dates
        ),
        basis_paths=(basis_path,) if include_basis and basis_path.exists() else (),
    )


def _missing_year_inputs(
    *,
    paths: _SourcePaths,
    year: str,
    require_basis: bool = False,
) -> list[str]:
    missing = [
        str(path)
        for path in (*paths.silver_paths, *paths.adj_factor_paths)
        if not path.exists()
    ]
    if not paths.qfq_paths:
        missing.append(f"gold_stk_mins_qfq_1m:{year}")
    if require_basis and not paths.basis_paths:
        missing.append(f"gold_stk_mins_qfq_as_of_basis:{year}")
    return missing


def _select_trade_dates(
    *,
    lake_root: Path,
    partition_keys: Sequence[str] | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, ...]:
    if partition_keys is not None:
        selected = _normalize_trade_dates(partition_keys)
    else:
        available = sorted(
            path.parent.name.removeprefix("trade_date=")
            for path in (
                lake_root / "silver" / "quote" / "stk_mins" / "freq=1"
            ).glob("trade_date=*/part-000.parquet")
        )
        selected = _normalize_trade_dates(available)
    normalized_start = _normalize_trade_date(start_date) if start_date else None
    normalized_end = _normalize_trade_date(end_date) if end_date else None
    selected = tuple(
        trade_date
        for trade_date in selected
        if (normalized_start is None or trade_date >= normalized_start)
        and (normalized_end is None or trade_date <= normalized_end)
    )
    if not selected:
        raise ValueError("No 1m silver trade dates selected for QFQ as-of bootstrap.")
    return selected


def _group_trade_dates_by_year(
    trade_dates: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for trade_date in _normalize_trade_dates(trade_dates):
        grouped.setdefault(trade_date[:4], []).append(trade_date)
    return {year: tuple(values) for year, values in grouped.items()}


def _plan_fingerprint(
    *,
    selected_trade_dates: Sequence[str],
    year_plans: Sequence[StkMinsQfqAsOfBasisBootstrapYearPlan],
) -> str:
    payload = {
        "selected_trade_dates": list(selected_trade_dates),
        "year_plans": [asdict(year_plan) for year_plan in year_plans],
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise ValueError("QFQ as-of basis bootstrap source paths must not be empty.")
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False)
    return "read_parquet([" + ", ".join(
        duckdb_string(path) for path in paths
    ) + "], hive_partitioning=false, union_by_name=true)"


def _date_values_sql(trade_dates: Sequence[str]) -> str:
    return ", ".join(
        f"(DATE {duckdb_string(trade_date)})" for trade_date in _normalize_trade_dates(trade_dates)
    )


def _normalize_trade_dates(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({_normalize_trade_date(value) for value in values}))
    if not normalized:
        raise ValueError("QFQ as-of basis bootstrap requires at least one trade date.")
    return normalized


def _normalize_trade_date(value: str | None) -> str:
    if value is None:
        raise ValueError("trade date must not be empty.")
    return date.fromisoformat(str(value).strip()).isoformat()
