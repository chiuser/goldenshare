"""Bounded Lake readiness for QFQ nine-turn Gold partitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Mapping, Sequence

from orchestrator.defs.asset_guards.stk_mins_lake_readiness import (
    StkMinsBatchReadiness,
    StkMinsDateReadiness,
    batch_gold_stk_mins_qfq_nineturn_upstream_lake_readiness,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_nineturn_path,
    gold_stock_daily_qfq_nineturn_path,
)
from orchestrator.defs.qfq_nineturn_integrity import (
    QfqNineturnIntegrityDiagnostics,
    audit_qfq_nineturn_integrity,
    qfq_nineturn_source_paths_for_partition,
)
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_MINUTE_FREQS,
    QFQ_NINETURN_SENSOR_WINDOW_DAILY,
    QFQ_NINETURN_SENSOR_WINDOW_MINUTE,
)


@dataclass(frozen=True, slots=True)
class QfqNineturnReadinessSpec:
    asset_key: str
    check_names: tuple[str, ...]
    freq: int | None


GOLD_STOCK_DAILY_QFQ_NINETURN_READINESS_SPEC = QfqNineturnReadinessSpec(
    asset_key="gold_stock_daily_qfq_nineturn",
    check_names=("gold_stock_daily_qfq_nineturn_integrity_check",),
    freq=None,
)
GOLD_STK_MINS_QFQ_NINETURN_READINESS_SPECS = tuple(
    QfqNineturnReadinessSpec(
        asset_key=f"gold_stk_mins_qfq_nineturn_{freq}m",
        check_names=(f"gold_stk_mins_qfq_nineturn_{freq}m_integrity_check",),
        freq=freq,
    )
    for freq in QFQ_NINETURN_MINUTE_FREQS
)


def batch_gold_stock_daily_qfq_nineturn_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
) -> StkMinsBatchReadiness:
    return _batch_qfq_nineturn_readiness(
        connection=connection,
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
        specs=(GOLD_STOCK_DAILY_QFQ_NINETURN_READINESS_SPEC,),
        max_trade_dates=QFQ_NINETURN_SENSOR_WINDOW_DAILY,
        dataset="gold_stock_daily_qfq_nineturn",
    )


def batch_gold_stk_mins_qfq_nineturn_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
) -> StkMinsBatchReadiness:
    return _batch_qfq_nineturn_readiness(
        connection=connection,
        lake_root=lake_root,
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
        specs=GOLD_STK_MINS_QFQ_NINETURN_READINESS_SPECS,
        max_trade_dates=QFQ_NINETURN_SENSOR_WINDOW_MINUTE,
        dataset="gold_stk_mins_qfq_nineturn",
    )


def _batch_qfq_nineturn_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    specs: Sequence[QfqNineturnReadinessSpec],
    max_trade_dates: int,
    dataset: str,
) -> StkMinsBatchReadiness:
    started_at = perf_counter()
    dates = tuple(sorted(set(str(value) for value in expected_trade_dates)))
    if len(dates) > max_trade_dates:
        raise ValueError(
            f"{dataset} readiness accepts at most {max_trade_dates} trade dates."
        )
    registered = set(str(value) for value in registered_trade_days)
    source_relations = _prepare_source_relations(
        connection,
        lake_root=lake_root,
        expected_trade_dates=dates,
        specs=specs,
    )
    statuses: dict[str, StkMinsDateReadiness] = {}
    for trade_date in dates:
        if trade_date not in registered:
            statuses[trade_date] = StkMinsDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason=f"{dataset} partition is not registered for {trade_date}",
                failed_check_names=(f"{dataset}_partition_not_registered",),
                missing_file_paths=(),
                expected_file_count=len(specs),
                existing_file_count=0,
            )
            continue
        diagnostics_by_spec = {
            spec: _audit_spec(
                connection,
                lake_root=lake_root,
                trade_date=trade_date,
                spec=spec,
                source_relation=source_relations[spec.freq],
            )
            for spec in specs
        }
        statuses[trade_date] = _status_from_diagnostics(
            trade_date=trade_date,
            diagnostics_by_spec=diagnostics_by_spec,
        )
    return StkMinsBatchReadiness(
        dataset=dataset,
        expected_start_date=dates[0] if dates else None,
        expected_end_date=dates[-1] if dates else None,
        expected_count=len(dates),
        freq_count=len(specs),
        elapsed_ms=(perf_counter() - started_at) * 1000,
        statuses_by_trade_date=statuses,
    )


def _prepare_source_relations(
    connection,
    *,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    specs: Sequence[QfqNineturnReadinessSpec],
) -> Mapping[int | None, str]:
    relations: dict[int | None, str] = {}
    date_values = ", ".join(
        f"DATE {duckdb_string(trade_date)}" for trade_date in expected_trade_dates
    )
    for spec in specs:
        source_paths = _source_paths_for_expected_dates(
            lake_root=lake_root,
            expected_trade_dates=expected_trade_dates,
            freq=spec.freq,
        )
        relation_name = (
            "qfq_nineturn_daily_source"
            if spec.freq is None
            else f"qfq_nineturn_{spec.freq}m_source"
        )
        if source_paths:
            path_values = ", ".join(duckdb_string(path) for path in source_paths)
            source_columns = (
                "ts_code, trade_date"
                if spec.freq is None
                else "ts_code, freq, trade_date, trade_time"
            )
            freq_predicate = (
                ""
                if spec.freq is None
                else f"AND CAST(freq AS INTEGER) = {spec.freq}"
            )
            connection.execute(
                f"""
                CREATE OR REPLACE TEMP TABLE {relation_name} AS
                SELECT {source_columns} FROM read_parquet(
                  [{path_values}],
                  hive_partitioning=false,
                  union_by_name=true
                )
                WHERE CAST(trade_date AS DATE) IN ({date_values})
                  {freq_predicate}
                """
            )
        else:
            empty_columns = (
                "NULL::VARCHAR AS ts_code, NULL::DATE AS trade_date"
                if spec.freq is None
                else "NULL::VARCHAR AS ts_code, NULL::INTEGER AS freq, "
                "NULL::DATE AS trade_date, NULL::TIMESTAMP AS trade_time"
            )
            connection.execute(
                f"""
                CREATE OR REPLACE TEMP TABLE {relation_name} AS
                SELECT {empty_columns}
                WHERE false
                """
            )
        relations[spec.freq] = relation_name
    return relations


def _source_paths_for_expected_dates(
    *,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    freq: int | None,
) -> tuple[Path, ...]:
    if freq is None:
        partition_keys = expected_trade_dates
    else:
        partition_keys = tuple(
            f"{year}-01-01"
            for year in sorted({trade_date[:4] for trade_date in expected_trade_dates})
        )
    return tuple(
        sorted(
            {
                path
                for partition_key in partition_keys
                for path in qfq_nineturn_source_paths_for_partition(
                    lake_root=lake_root,
                    partition_key=partition_key,
                    freq=freq,
                )
                if path.is_file()
            }
        )
    )


def _audit_spec(
    connection,
    *,
    lake_root: Path,
    trade_date: str,
    spec: QfqNineturnReadinessSpec,
    source_relation: str,
) -> QfqNineturnIntegrityDiagnostics:
    target_path = (
        gold_stock_daily_qfq_nineturn_path(lake_root, trade_date)
        if spec.freq is None
        else gold_stk_mins_qfq_nineturn_path(lake_root, spec.freq, trade_date)
    )
    return audit_qfq_nineturn_integrity(
        connection,
        target_path=target_path,
        source_paths=(),
        partition_key=trade_date,
        freq=spec.freq,
        source_relation=source_relation,
    )


def _status_from_diagnostics(
    *,
    trade_date: str,
    diagnostics_by_spec: Mapping[
        QfqNineturnReadinessSpec, QfqNineturnIntegrityDiagnostics
    ],
) -> StkMinsDateReadiness:
    failed_check_names = tuple(
        check_name
        for spec, diagnostics in diagnostics_by_spec.items()
        if not diagnostics.passed
        for check_name in spec.check_names
    )
    existing_file_count = sum(
        diagnostics.checked_row_count > 0
        for diagnostics in diagnostics_by_spec.values()
    )
    checked_row_count = sum(
        diagnostics.checked_row_count for diagnostics in diagnostics_by_spec.values()
    )
    failed_row_count = sum(
        diagnostics.failed_row_count for diagnostics in diagnostics_by_spec.values()
    )
    ready = not failed_check_names
    return StkMinsDateReadiness(
        trade_date=trade_date,
        ready=ready,
        materialized=existing_file_count == len(diagnostics_by_spec),
        checks_passed=ready,
        reason=(
            "ready"
            if ready
            else "qfq nine-turn integrity checks failed for "
            f"{trade_date}: {', '.join(failed_check_names)}"
        ),
        failed_check_names=failed_check_names,
        missing_file_paths=(),
        expected_file_count=len(diagnostics_by_spec),
        existing_file_count=existing_file_count,
        checked_row_count=checked_row_count,
        failed_row_count=failed_row_count,
    )


__all__ = [
    "GOLD_STK_MINS_QFQ_NINETURN_READINESS_SPECS",
    "GOLD_STOCK_DAILY_QFQ_NINETURN_READINESS_SPEC",
    "batch_gold_stk_mins_qfq_nineturn_readiness",
    "batch_gold_stk_mins_qfq_nineturn_upstream_lake_readiness",
    "batch_gold_stock_daily_qfq_nineturn_readiness",
]
