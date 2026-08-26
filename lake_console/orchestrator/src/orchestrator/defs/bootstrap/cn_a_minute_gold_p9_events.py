"""P9 runless events for canonical China-A minute Gold rebuilds."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import dagster as dg
import sqlalchemy as db
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.storage.event_log.schema import AssetCheckExecutionsTable

from orchestrator.defs.bootstrap.major_index_mins_technical_history import (
    load_major_index_mins_technical_bootstrap_plan,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_bootstrap_events import (
    audit_stk_mins_qfq_bootstrap_batch,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_history import StkMinsQfqHistoryBatch
from orchestrator.defs.bootstrap.stk_mins_qfq_macd_kdj_history import (
    _read_parquet_paths,
)
from orchestrator.defs.checks.cn_a_gold_minute_checks import (
    evaluate_canonical_gold_minute_core_check,
)
from orchestrator.defs.checks.major_index_mins_technical_checks import (
    evaluate_major_index_mins_technical_check,
    evaluate_major_index_mins_technical_state_check,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.partitions import (
    cn_a_index_mins_trade_days,
    cn_a_stock_mins_silver_trade_days,
    cn_major_index_mins_trade_days,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_index_mins_path,
    gold_major_index_mins_path,
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_state_path,
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    gold_stk_mins_qfq_path,
    silver_index_mins_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_INDEX_MINS_SCHEMA,
    GOLD_MAJOR_INDEX_MINS_SCHEMA,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_SCHEMA,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
    GOLD_STK_MINS_QFQ_SCHEMA,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_FREQS,
    CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET,
)
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_GOLD_ASSET_NAMES,
    INDEX_MINS_GOLD_CHECKS,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_GOLD_ASSET_KEYS,
    MAJOR_INDEX_MINS_GOLD_CHECKS,
    effective_silver_codes_for_date,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    major_index_mins_technical_asset_key,
    major_index_mins_technical_checks,
    major_index_mins_technical_state_asset_key,
    major_index_mins_technical_state_checks,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMN_TYPES,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMN_TYPES,
    discover_gold_stk_mins_qfq_source_year_paths,
)

P9_FREQUENCIES = (5, 15, 30, 60)
P9_CHECK_WINDOW = 20
P9_REVISION = "cn_a_minute_gold_p9_v1"
P9_FAMILIES = (
    "index_gold",
    "major_index_gold",
    "major_index_technical_state",
    "stock_qfq",
    "stock_indicator_state",
)
_TECHNICAL_CHECK_KINDS = (
    "contract",
    "source_coverage",
    "partition_frequency",
    "key_integrity",
    "warmup_and_finite",
    "no_future_input",
)
_STATE_CHECK_KINDS = ("contract", "coverage", "last_trade_time", "continuity")
_ACTIVE_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)


class MinuteGoldP9EventError(RuntimeError):
    """Raised before an unsafe P9 event write."""


@dataclass(frozen=True, slots=True)
class P9Evidence:
    p6_summary: Path
    index_plan: Path
    index_formal_audit: Path
    major_plan: Path
    major_formal_audit: Path
    major_technical_plan: Path
    major_technical_promote: Path
    major_technical_formal_audit: Path
    stock_plan: Path
    stock_formal_audits: tuple[Path, ...]
    stock_indicator_audits: tuple[Path, ...]
    stock_indicator_checkpoints: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class P9AssetSpec:
    family: str
    asset_key: str
    freq: int
    partition_set: str
    trade_dates: tuple[str, ...]
    check_names: tuple[str, ...]
    observed_columns: tuple[str, ...]
    uri_builder: Callable[[str], Path]
    row_count_by_date: Mapping[str, int | None]
    source_method: str


@dataclass(frozen=True, slots=True)
class P9Plan:
    plan_hash: str
    evidence_hashes: Mapping[str, str]
    assets: tuple[P9AssetSpec, ...]
    recent_dates_by_partition_set: Mapping[str, tuple[str, ...]]
    missing_registered: Mapping[str, tuple[str, ...]]
    active_run_count: int
    check_audits: Mapping[str, tuple[dg.AssetCheckResult, ...]]
    elapsed_ms: float

    @property
    def planned_materialization_count(self) -> int:
        return sum(len(asset.trade_dates) for asset in self.assets)

    @property
    def planned_check_count(self) -> int:
        return sum(
            len(asset.check_names)
            * len(self.recent_dates_by_partition_set[asset.partition_set])
            for asset in self.assets
        )

    @property
    def should_stop(self) -> bool:
        return (
            self.active_run_count > 0
            or any(self.missing_registered.values())
            or any(
                not result.passed
                for results in self.check_audits.values()
                for result in results
            )
        )

    def to_dict(self) -> dict[str, object]:
        failures = [
            key
            for key, results in self.check_audits.items()
            if any(not result.passed for result in results)
        ]
        return {
            "schema_version": 1,
            "revision": P9_REVISION,
            "plan_hash": self.plan_hash,
            "evidence_hashes": dict(self.evidence_hashes),
            "active_run_count": self.active_run_count,
            "asset_count": len(self.assets),
            "planned_materialization_event_count": self.planned_materialization_count,
            "planned_check_event_count": self.planned_check_count,
            "planned_event_count": self.planned_materialization_count
            + self.planned_check_count,
            "recent_dates_by_partition_set": {
                key: list(value)
                for key, value in self.recent_dates_by_partition_set.items()
            },
            "missing_registered": {
                key: list(value[:10]) for key, value in self.missing_registered.items()
            },
            "failed_check_partition_count": len(failures),
            "failed_check_partition_samples": failures[:10],
            "families": {
                family: {
                    "asset_count": sum(asset.family == family for asset in self.assets),
                    "materialization_count": sum(
                        len(asset.trade_dates)
                        for asset in self.assets
                        if asset.family == family
                    ),
                    "check_count": sum(
                        len(asset.check_names)
                        * len(self.recent_dates_by_partition_set[asset.partition_set])
                        for asset in self.assets
                        if asset.family == family
                    ),
                }
                for family in P9_FAMILIES
            },
            "elapsed_ms": round(self.elapsed_ms, 3),
            "should_stop": self.should_stop,
            "writes": {"formal_lake": 0, "dynamic_partitions": 0, "dagster_events": 0},
        }


@dataclass(frozen=True, slots=True)
class P9EventReport:
    mode: str
    family: str | None
    plan: P9Plan
    reported_materializations: int = 0
    reported_checks: int = 0
    refreshed_runless_check_indexes: int = 0
    skipped_checkpoint_items: int = 0
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": self.mode,
            "family": self.family,
            "reported_materialization_count": self.reported_materializations,
            "reported_check_count": self.reported_checks,
            "refreshed_runless_check_index_count": self.refreshed_runless_check_indexes,
            "reported_event_count": self.reported_materializations
            + self.reported_checks,
            "skipped_checkpoint_item_count": self.skipped_checkpoint_items,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "plan": self.plan.to_dict(),
        }


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MinuteGoldP9EventError(f"P9 evidence is unreadable: {path}") from error
    if not isinstance(value, Mapping):
        raise MinuteGoldP9EventError(f"P9 evidence must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_payload(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_green_report(
    path: Path, *, plan_hash: str | None = None
) -> Mapping[str, Any]:
    value = _load_json(path)
    if value.get("should_stop") is not False or value.get("ready") is not True:
        raise MinuteGoldP9EventError(f"P9 evidence is not green: {path}")
    if plan_hash is not None and value.get("plan_hash") != plan_hash:
        raise MinuteGoldP9EventError(f"P9 evidence plan hash mismatch: {path}")
    return value


def _load_python_dict(path: Path) -> Mapping[str, Any]:
    import ast

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise MinuteGoldP9EventError(f"P8 audit is empty: {path}")
    value = ast.literal_eval(lines[-1])
    if not isinstance(value, Mapping) or value.get("passed") is not True:
        raise MinuteGoldP9EventError(f"P8 audit is not green: {path}")
    return value


def _footer_counts(paths: Sequence[Path]) -> dict[str, int]:
    if not paths:
        return {}
    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            """
            SELECT file_name, CAST(sum(num_rows) AS BIGINT)
            FROM parquet_file_metadata(?)
            GROUP BY file_name
            """,
            [[str(path) for path in paths]],
        ).fetchall()
    return {str(Path(name).resolve()): int(count) for name, count in rows}


def _single_file_counts(
    dates: Sequence[str],
    freqs: Sequence[int],
    builder: Callable[[int, str], Path],
) -> dict[tuple[int, str], int]:
    paths = [builder(freq, trade_date) for freq in freqs for trade_date in dates]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise MinuteGoldP9EventError(f"P9 target files are missing: {missing[:10]}")
    counts = _footer_counts(paths)
    if len(counts) != len(paths) or any(count <= 0 for count in counts.values()):
        raise MinuteGoldP9EventError(
            "P9 footer inventory is incomplete or non-positive"
        )
    return {
        (freq, trade_date): counts[str(builder(freq, trade_date).resolve())]
        for freq in freqs
        for trade_date in dates
    }


def _stock_indicator_date_counts(
    *,
    lake_root: Path,
    freq: int,
    dates: Sequence[str],
) -> dict[tuple[int, str], int]:
    expected = set(dates)
    counts: dict[tuple[int, str], int] = {}
    for year in sorted({date[:4] for date in dates}):
        year_dates = tuple(date for date in dates if date.startswith(year))
        root = gold_stk_mins_qfq_macd_kdj_path(
            lake_root,
            freq,
            "{ts_code}",
            year,
        ).parents[2]
        paths = tuple(sorted(root.glob(f"ts_code=*/year={year}/part-000.parquet")))
        if not paths:
            raise MinuteGoldP9EventError(
                f"P9 stock indicator files are missing: freq={freq}, year={year}"
            )
        with connect_configured_duckdb() as connection:
            rows = connection.execute(
                f"""
                SELECT CAST(trade_date AS DATE)::VARCHAR, count(*)::BIGINT
                FROM {_read_parquet_paths(paths)}
                WHERE CAST(freq AS INTEGER) = {freq}
                  AND CAST(trade_date AS DATE)::VARCHAR BETWEEN ? AND ?
                GROUP BY CAST(trade_date AS DATE)
                """,
                [year_dates[0], year_dates[-1]],
            ).fetchall()
        counts.update(((freq, str(date)), int(row_count)) for date, row_count in rows)
    missing = expected - {date for current_freq, date in counts if current_freq == freq}
    if missing or any(value <= 0 for value in counts.values()):
        raise MinuteGoldP9EventError(
            f"P9 stock indicator row-count inventory is incomplete: "
            f"freq={freq}, missing={sorted(missing)[:10]}"
        )
    return counts


def _date_values_sql(dates: Sequence[str]) -> str:
    return "VALUES " + ", ".join(f"(DATE {duckdb_string(date)})" for date in dates)


def _schema_matches_sample(
    connection: Any,
    *,
    paths: Sequence[Path],
    expected_types: Mapping[str, str],
) -> bool:
    expected = {name: type_name.upper() for name, type_name in expected_types.items()}
    for path in paths[:20]:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM {_read_parquet_paths((path,))}"
        ).fetchall()
        if {str(row[0]): str(row[1]).upper() for row in rows} != expected:
            return False
    return True


def audit_stock_indicator_state_partitions(
    *,
    lake_root: Path,
    freq: int,
    dates: Sequence[str],
) -> dict[str, tuple[dg.AssetCheckResult, ...]]:
    selected_dates = tuple(sorted(set(dates)))
    source_paths = discover_gold_stk_mins_qfq_source_year_paths(
        lake_root,
        freq=freq,
        trade_dates=selected_dates,
    )
    if not source_paths:
        raise MinuteGoldP9EventError(
            f"P9 stock indicator source is missing: freq={freq}"
        )
    values_sql = _date_values_sql(selected_dates)
    source_relation = _read_parquet_paths(source_paths)
    with connect_configured_duckdb() as connection:
        source_rows = connection.execute(
            f"""
            SELECT
              CAST(trade_date AS DATE)::VARCHAR AS trade_date,
              CAST(ts_code AS VARCHAR) AS ts_code,
              strftime(CAST(trade_date AS DATE), '%Y') AS year,
              count(*)::BIGINT AS row_count
            FROM {source_relation}
            WHERE CAST(freq AS INTEGER) = {freq}
              AND CAST(trade_date AS DATE) IN (
                SELECT trade_date FROM ({values_sql}) AS selected(trade_date)
              )
            GROUP BY 1, 2, 3
            ORDER BY 1, 2
            """
        ).fetchall()
        expected_paths_by_date: dict[str, tuple[Path, ...]] = {}
        source_counts = dict.fromkeys(selected_dates, 0)
        for trade_date in selected_dates:
            scoped = [row for row in source_rows if str(row[0]) == trade_date]
            source_counts[trade_date] = sum(int(row[3]) for row in scoped)
            expected_paths_by_date[trade_date] = tuple(
                gold_stk_mins_qfq_macd_kdj_path(
                    lake_root,
                    freq,
                    str(ts_code),
                    str(year),
                )
                for _, ts_code, year, _ in scoped
            )
        all_indicator_paths = tuple(
            sorted(
                {
                    path
                    for paths in expected_paths_by_date.values()
                    for path in paths
                    if path.is_file()
                }
            )
        )
        indicator_rows = (
            connection.execute(
                f"""
                SELECT
                  CAST(trade_date AS DATE)::VARCHAR AS trade_date,
                  count(*)::BIGINT AS row_count
                FROM {_read_parquet_paths(all_indicator_paths)}
                WHERE CAST(freq AS INTEGER) = {freq}
                  AND CAST(trade_date AS DATE) IN (
                    SELECT trade_date FROM ({values_sql}) AS selected(trade_date)
                  )
                GROUP BY 1
                """
            ).fetchall()
            if all_indicator_paths
            else ()
        )
        indicator_counts = dict.fromkeys(selected_dates, 0)
        indicator_counts.update(
            {str(date): int(count) for date, count in indicator_rows}
        )
        state_paths = {
            trade_date: gold_stk_mins_qfq_macd_kdj_state_path(
                lake_root, freq, trade_date
            )
            for trade_date in selected_dates
        }
        existing_state_paths = tuple(
            path for path in state_paths.values() if path.is_file()
        )
        coverage_rows = (
            connection.execute(
                f"""
                WITH indicator_latest AS (
                  SELECT
                    CAST(trade_date AS DATE) AS trade_date,
                    CAST(ts_code AS VARCHAR) AS ts_code,
                    max(trade_time) AS last_trade_time
                  FROM {_read_parquet_paths(all_indicator_paths)}
                  WHERE CAST(freq AS INTEGER) = {freq}
                    AND CAST(trade_date AS DATE) IN (
                      SELECT trade_date FROM ({values_sql}) AS selected(trade_date)
                    )
                  GROUP BY 1, 2
                ),
                state_rows AS (
                  SELECT
                    CAST(trade_date AS DATE) AS trade_date,
                    CAST(ts_code AS VARCHAR) AS ts_code,
                    last_trade_time
                  FROM {_read_parquet_paths(existing_state_paths)}
                  WHERE CAST(freq AS INTEGER) = {freq}
                    AND CAST(trade_date AS DATE) IN (
                      SELECT trade_date FROM ({values_sql}) AS selected(trade_date)
                    )
                ),
                joined AS (
                  SELECT
                    coalesce(indicator_latest.trade_date, state_rows.trade_date) AS trade_date,
                    coalesce(indicator_latest.ts_code, state_rows.ts_code) AS ts_code,
                    indicator_latest.last_trade_time AS indicator_last_trade_time,
                    state_rows.last_trade_time AS state_last_trade_time
                  FROM indicator_latest
                  FULL OUTER JOIN state_rows USING (trade_date, ts_code)
                )
                SELECT
                  dates.trade_date::VARCHAR,
                  count(DISTINCT joined.ts_code) FILTER (
                    WHERE joined.indicator_last_trade_time IS NOT NULL
                  )::BIGINT AS indicator_stock_count,
                  count(DISTINCT joined.ts_code) FILTER (
                    WHERE joined.state_last_trade_time IS NOT NULL
                  )::BIGINT AS state_row_count,
                  count(*) FILTER (
                    WHERE joined.indicator_last_trade_time IS NOT NULL
                      AND (
                        joined.state_last_trade_time IS NULL
                        OR joined.indicator_last_trade_time != joined.state_last_trade_time
                      )
                  )::BIGINT AS current_mismatch_count,
                  count(*) FILTER (
                    WHERE joined.state_last_trade_time IS NOT NULL
                      AND CAST(joined.state_last_trade_time AS DATE) > dates.trade_date
                  )::BIGINT AS future_mismatch_count
                FROM ({values_sql}) AS dates(trade_date)
                LEFT JOIN joined USING (trade_date)
                GROUP BY dates.trade_date
                ORDER BY dates.trade_date
                """
            ).fetchall()
            if all_indicator_paths and existing_state_paths
            else ()
        )
        coverage = {
            str(date): tuple(int(value or 0) for value in row[1:])
            for row in coverage_rows
            for date in (row[0],)
        }

        results: dict[str, tuple[dg.AssetCheckResult, ...]] = {}
        indicator_asset = f"gold_stk_mins_qfq_macd_kdj_{freq}m"
        state_asset = f"gold_stk_mins_qfq_macd_kdj_state_{freq}m"
        for trade_date in selected_dates:
            expected_paths = expected_paths_by_date[trade_date]
            existing_paths = tuple(path for path in expected_paths if path.is_file())
            contract_ok = (
                bool(expected_paths)
                and len(existing_paths) == len(expected_paths)
                and _schema_matches_sample(
                    connection,
                    paths=existing_paths,
                    expected_types=GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMN_TYPES,
                )
            )
            source_count = int(source_counts[trade_date])
            indicator_count = int(indicator_counts[trade_date])
            coverage_ok = source_count > 0 and source_count == indicator_count
            results[f"{indicator_asset}|{trade_date}"] = (
                dg.AssetCheckResult(
                    passed=contract_ok,
                    metadata=build_check_metadata(
                        check_scope=CheckScope.SCHEMA,
                        checked_row_count=len(expected_paths),
                        failed_row_count=len(expected_paths) - len(existing_paths)
                        if contract_ok
                        else max(1, len(expected_paths) - len(existing_paths)),
                        input_file_paths=existing_paths[:20],
                        missing_file_paths=tuple(
                            path for path in expected_paths if not path.is_file()
                        )[:20],
                        extra_metadata={
                            "expected_file_count": len(expected_paths),
                            "existing_file_count": len(existing_paths),
                            "reason_code": "ready"
                            if contract_ok
                            else "contract_failed",
                        },
                    ),
                ),
                dg.AssetCheckResult(
                    passed=coverage_ok,
                    metadata=build_check_metadata(
                        check_scope=CheckScope.RECONCILIATION,
                        checked_row_count=source_count,
                        failed_row_count=abs(source_count - indicator_count),
                        input_file_paths=existing_paths[:20],
                        extra_metadata={
                            "source_row_count": source_count,
                            "indicator_row_count": indicator_count,
                            "reason_code": "ready"
                            if coverage_ok
                            else "coverage_failed",
                        },
                    ),
                ),
            )
            state_path = state_paths[trade_date]
            state_contract_ok = state_path.is_file() and _schema_matches_sample(
                connection,
                paths=(state_path,) if state_path.is_file() else (),
                expected_types=GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMN_TYPES,
            )
            (
                indicator_stock_count,
                state_row_count,
                current_mismatch,
                future_mismatch,
            ) = coverage.get(trade_date, (0, 0, 1, 0))
            state_coverage_ok = (
                indicator_stock_count > 0
                and state_row_count >= indicator_stock_count
                and current_mismatch == 0
                and future_mismatch == 0
            )
            results[f"{state_asset}|{trade_date}"] = (
                dg.AssetCheckResult(
                    passed=state_contract_ok,
                    metadata=build_check_metadata(
                        check_scope=CheckScope.SCHEMA,
                        file_path=state_path,
                        failed_row_count=0 if state_contract_ok else 1,
                        extra_metadata={
                            "reason_code": "ready"
                            if state_contract_ok
                            else "contract_failed",
                        },
                    ),
                ),
                dg.AssetCheckResult(
                    passed=state_coverage_ok,
                    metadata=build_check_metadata(
                        check_scope=CheckScope.RECONCILIATION,
                        checked_row_count=indicator_stock_count,
                        failed_row_count=current_mismatch + future_mismatch,
                        file_path=state_path,
                        input_file_paths=existing_paths[:20],
                        extra_metadata={
                            "indicator_stock_count": indicator_stock_count,
                            "state_row_count": state_row_count,
                            "current_indicator_mismatch_count": current_mismatch,
                            "future_state_mismatch_count": future_mismatch,
                            "reason_code": "ready"
                            if state_coverage_ok
                            else "coverage_failed",
                        },
                    ),
                ),
            )
    return results


def _active_run_count(instance: Any) -> int:
    return len(
        instance.get_runs(
            filters=dg.RunsFilter(statuses=list(_ACTIVE_STATUSES)), limit=1
        )
    )


def _checkpoint(path: Path, *, plan_hash: str) -> set[str]:
    if not path.exists():
        return set()
    value = _load_json(path)
    if value.get("plan_hash") != plan_hash:
        raise MinuteGoldP9EventError("P9 checkpoint belongs to another plan")
    completed = value.get("completed_items", [])
    if not isinstance(completed, list):
        raise MinuteGoldP9EventError("P9 checkpoint completed_items is invalid")
    return {str(item) for item in completed}


def _write_checkpoint(path: Path, *, plan_hash: str, completed: set[str]) -> None:
    _atomic_json(
        path,
        {
            "schema_version": 1,
            "revision": P9_REVISION,
            "plan_hash": plan_hash,
            "completed_items": sorted(completed),
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


def _latest_materialization(instance: Any, asset_key: str, partition: str) -> object:
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key),
            asset_partitions=[partition],
        ),
        limit=1,
    ).records
    if not records:
        raise MinuteGoldP9EventError(
            f"missing reported materialization: {asset_key}:{partition}"
        )
    return records[0]


def _metadata_value(metadata: Mapping[str, object], key: str) -> object | None:
    value = metadata.get(key)
    return getattr(value, "value", value)


def _latest_materialization_for_p9(
    instance: Any,
    *,
    asset_key: str,
    partition: str,
    plan_hash: str,
) -> object | None:
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key),
            asset_partitions=[partition],
        ),
        limit=1,
    ).records
    if not records:
        return None
    record = records[0]
    metadata = record.asset_materialization.metadata
    if (
        _metadata_value(metadata, "goldenshare/p9_revision") != P9_REVISION
        or _metadata_value(metadata, "goldenshare/p9_plan_hash") != plan_hash
    ):
        return None
    return record


def _release_stale_runless_check_index(
    instance: Any,
    *,
    asset_key: str,
    check_name: str,
    partition: str,
    target_materialization_storage_id: int,
) -> str:
    """Release Dagster's unique runless check index row without deleting its event log."""

    table = AssetCheckExecutionsTable
    asset_key_value = dg.AssetKey(asset_key).to_string()
    with instance.event_log_storage.index_connection() as connection:
        rows = connection.execute(
            db.select(
                table.c.id,
                table.c.execution_status,
                table.c.materialization_event_storage_id,
            ).where(
                db.and_(
                    table.c.asset_key == asset_key_value,
                    table.c.check_name == check_name,
                    table.c.partition == partition,
                    table.c.run_id == "",
                )
            )
        ).fetchall()
        if len(rows) > 1:
            raise MinuteGoldP9EventError(
                "P9 found duplicate runless check index rows: "
                f"{asset_key}:{check_name}:{partition}"
            )
        if not rows:
            return "missing"
        row = rows[0]
        if (
            str(row.execution_status) == "SUCCEEDED"
            and int(row.materialization_event_storage_id or -1)
            == target_materialization_storage_id
        ):
            return "ready"
        connection.execute(table.delete().where(table.c.id == row.id))
    return "released"


def _materializations_by_partition(
    instance: Any,
    *,
    asset_key: str,
    partitions: Sequence[str],
) -> dict[str, object]:
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset_key),
            asset_partitions=list(partitions),
        ),
        limit=max(1, len(partitions)),
    ).records
    return {
        str(record.partition_key): record
        for record in records
        if getattr(record, "partition_key", None) is not None
    }


def _assert_latest_bound_checks(
    instance: Any,
    *,
    spec: P9AssetSpec,
    partitions: Sequence[str],
) -> None:
    materializations = _materializations_by_partition(
        instance,
        asset_key=spec.asset_key,
        partitions=partitions,
    )
    missing_materializations = set(partitions) - set(materializations)
    if missing_materializations:
        raise MinuteGoldP9EventError(
            "P9 post-audit recent materializations are incomplete: "
            f"{spec.asset_key}:{sorted(missing_materializations)[:10]}"
        )
    expected_ids = {
        partition: int(record.storage_id)
        for partition, record in materializations.items()
    }
    for check_name in spec.check_names:
        ready: set[str] = set()
        history = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(dg.AssetKey(spec.asset_key), check_name),
            limit=max(100, len(partitions) * 3),
        )
        for record in history:
            partition = str(getattr(record, "partition", ""))
            if partition not in expected_ids or partition in ready:
                continue
            event = getattr(record, "event", None)
            dagster_event = getattr(event, "dagster_event", None) if event else None
            evaluation = (
                getattr(dagster_event, "event_specific_data", None)
                if dagster_event
                else None
            )
            target = getattr(evaluation, "target_materialization_data", None)
            if (
                target is not None
                and int(target.storage_id) == expected_ids[partition]
                and bool(getattr(evaluation, "passed", False))
                and bool(getattr(evaluation, "blocking", False))
            ):
                ready.add(partition)
        missing_checks = set(partitions) - ready
        if missing_checks:
            raise MinuteGoldP9EventError(
                "P9 post-audit latest-bound checks are incomplete: "
                f"{spec.asset_key}:{check_name}:{sorted(missing_checks)[:10]}"
            )


def _check_result_metadata(result: dg.AssetCheckResult) -> Mapping[str, object]:
    return result.metadata or {}


def _report_materialization(
    instance: Any, *, plan: P9Plan, spec: P9AssetSpec, date: str
) -> None:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=dg.AssetKey(spec.asset_key),
            partition=date,
            metadata=build_materialization_metadata(
                uri=spec.uri_builder(date),
                row_count=spec.row_count_by_date.get(date),
                observed_columns=spec.observed_columns,
                extra_metadata={
                    "source_method": spec.source_method,
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "full_rebuilt_history",
                    "p9_revision": P9_REVISION,
                    "p9_plan_hash": plan.plan_hash,
                    "frequency": spec.freq,
                    "partition_key": date,
                },
            ),
        )
    )


def _report_checks(
    instance: Any,
    *,
    plan: P9Plan,
    spec: P9AssetSpec,
    date: str,
) -> tuple[int, int]:
    materialization = _latest_materialization(instance, spec.asset_key, date)
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=materialization.storage_id,
        run_id=materialization.run_id,
        timestamp=materialization.timestamp,
    )
    results = plan.check_audits[f"{spec.asset_key}|{date}"]
    if len(results) != len(spec.check_names):
        raise MinuteGoldP9EventError(
            f"P9 check audit count mismatch: {spec.asset_key}:{date}"
        )
    reported = 0
    refreshed_indexes = 0
    for check_name, result in zip(spec.check_names, results, strict=True):
        if not result.passed:
            raise MinuteGoldP9EventError(
                f"P9 refuses a failed check: {spec.asset_key}:{check_name}:{date}"
            )
        metadata = dict(_check_result_metadata(result))
        metadata.update(
            build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                file_path=spec.uri_builder(date),
                extra_metadata={
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "recent_20_expected_trade_dates",
                    "p9_revision": P9_REVISION,
                    "p9_plan_hash": plan.plan_hash,
                    "partition_key": date,
                    "reason_code": "ready",
                },
            )
        )
        index_status = _release_stale_runless_check_index(
            instance,
            asset_key=spec.asset_key,
            check_name=check_name,
            partition=date,
            target_materialization_storage_id=int(materialization.storage_id),
        )
        if index_status == "ready":
            continue
        refreshed_indexes += int(index_status == "released")
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=dg.AssetKey(spec.asset_key),
                check_name=check_name,
                passed=True,
                blocking=True,
                partition=date,
                target_materialization_data=target,
                metadata=metadata,
            )
        )
        reported += 1
    return reported, refreshed_indexes


def _asset_spec(
    *,
    family: str,
    asset_key: str,
    freq: int,
    partition_set: str,
    dates: tuple[str, ...],
    check_names: tuple[str, ...],
    columns: Sequence[object],
    uri_builder: Callable[[str], Path],
    counts: Mapping[tuple[int, str], int] | Mapping[str, int],
    source_method: str,
) -> P9AssetSpec:
    return P9AssetSpec(
        family=family,
        asset_key=asset_key,
        freq=freq,
        partition_set=partition_set,
        trade_dates=dates,
        check_names=check_names,
        observed_columns=tuple(
            str(getattr(column, "name", column)) for column in columns
        ),
        uri_builder=uri_builder,
        row_count_by_date={
            date: (
                int(counts[(freq, date)])
                if (freq, date) in counts
                else int(counts[date])
                if date in counts
                else None
            )
            for date in dates
            if (freq, date) in counts or date in counts
        },
        source_method=source_method,
    )


def _stock_dates(plan: Mapping[str, Any]) -> tuple[str, ...]:
    start = str(plan.get("start_date") or "")
    end = str(plan.get("end_date") or "")
    if not start or not end:
        raise MinuteGoldP9EventError("P7 plan has no frozen date range")
    return start, end


def _stock_dates_hash(dates: Sequence[str]) -> str:
    return hashlib.sha256(
        json.dumps(
            list(dates), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _validate_evidence(evidence: P9Evidence) -> tuple[dict[str, str], dict[str, Any]]:
    paths = (
        evidence.p6_summary,
        evidence.index_plan,
        evidence.index_formal_audit,
        evidence.major_plan,
        evidence.major_formal_audit,
        evidence.major_technical_plan,
        evidence.major_technical_promote,
        evidence.major_technical_formal_audit,
        evidence.stock_plan,
        *evidence.stock_formal_audits,
        *evidence.stock_indicator_audits,
        *evidence.stock_indicator_checkpoints,
    )
    hashes = {str(path): _sha256(path) for path in paths}
    p6 = _validate_green_report(evidence.p6_summary)
    if p6.get("report_type") != "cn_a_minute_gold_p6_execution_summary":
        raise MinuteGoldP9EventError("P6 execution summary identity is invalid")
    index_plan = _load_json(evidence.index_plan)
    major_plan = _load_json(evidence.major_plan)
    stock_plan = _load_json(evidence.stock_plan)
    index_hash = str(index_plan.get("plan_hash") or "")
    major_hash = str(major_plan.get("plan_hash") or "")
    stock_hash = str(stock_plan.get("plan_hash") or "")
    _validate_green_report(evidence.index_formal_audit, plan_hash=index_hash)
    _validate_green_report(evidence.major_formal_audit, plan_hash=major_hash)
    technical_plan = load_major_index_mins_technical_bootstrap_plan(
        evidence.major_technical_plan,
        expected_plan_hash=str(p6["major_index_rebuilt_technical_state"]["plan_hash"]),
    )
    technical_promote = _load_json(evidence.major_technical_promote)
    promote_results = technical_promote.get("results")
    if (
        technical_promote.get("should_stop") is not False
        or technical_promote.get("plan_hash") != technical_plan.plan_hash
        or not isinstance(promote_results, list)
        or len(promote_results)
        != len(technical_plan.trade_dates) * len(P9_FREQUENCIES) * 2
        or {int(result.get("freq") or 0) for result in promote_results}
        != set(P9_FREQUENCIES)
        or {str(result.get("layer") or "") for result in promote_results}
        != {"technical", "state"}
    ):
        raise MinuteGoldP9EventError(
            "P6 major-index technical promote evidence is invalid"
        )
    _validate_green_report(
        evidence.major_technical_formal_audit,
        plan_hash=technical_plan.plan_hash,
    )
    if stock_hash != "c8b53c333d5a969488171b4da4eca9a444aaba54c1a69e113464773f831ea099":
        raise MinuteGoldP9EventError(
            "P7 stock plan identity is not the frozen completed plan"
        )
    for path, freq in zip(evidence.stock_formal_audits, P9_FREQUENCIES, strict=True):
        report = _validate_green_report(path, plan_hash=stock_hash)
        if int(report.get("freq") or 0) != freq:
            raise MinuteGoldP9EventError(f"P7 formal audit frequency mismatch: {path}")
    audited_years: dict[int, set[str]] = {freq: set() for freq in P9_FREQUENCIES}
    audited_date_count: dict[int, int] = {freq: 0 for freq in P9_FREQUENCIES}
    for path in evidence.stock_indicator_audits:
        report = _load_python_dict(path)
        selected_freqs = report.get("selected_freqs")
        if not isinstance(selected_freqs, list) or len(selected_freqs) != 1:
            raise MinuteGoldP9EventError(f"P8 audit scope mismatch: {path}")
        freq = int(selected_freqs[0])
        if freq not in audited_years:
            raise MinuteGoldP9EventError(f"P8 audit frequency is outside P9: {path}")
        selected_years = {str(year) for year in report.get("selected_years", ())}
        new_years = selected_years - audited_years[freq]
        if new_years != selected_years:
            raise MinuteGoldP9EventError(f"P8 audit years overlap: {path}")
        audited_years[freq].update(new_years)
        audited_date_count[freq] += int(report.get("selected_partition_count") or 0)
    expected_years = {str(year) for year in range(2014, 2027)}
    if any(
        audited_years[freq] != expected_years or audited_date_count[freq] != 3066
        for freq in P9_FREQUENCIES
    ):
        raise MinuteGoldP9EventError(
            "P8 audit evidence does not cover all four frequencies"
        )
    for path, freq in zip(
        evidence.stock_indicator_checkpoints, P9_FREQUENCIES, strict=True
    ):
        checkpoint = _load_json(path)
        keys = tuple(str(key) for key in checkpoint.get("completed_batch_keys", ()))
        years = {key.split(":", 2)[1] for key in keys if key.startswith(f"{freq}:")}
        if years != {str(year) for year in range(2014, 2027)}:
            raise MinuteGoldP9EventError(f"P8 checkpoint is incomplete: {path}")
    return hashes, {
        "index_plan": index_plan,
        "major_plan": major_plan,
        "technical_plan": technical_plan,
        "stock_plan": stock_plan,
    }


def build_p9_plan(
    *,
    instance: Any,
    evidence: P9Evidence,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    families: Sequence[str] = P9_FAMILIES,
) -> P9Plan:
    started = perf_counter()
    selected_families = tuple(dict.fromkeys(families))
    unsupported = set(selected_families) - set(P9_FAMILIES)
    if not selected_families or unsupported:
        raise MinuteGoldP9EventError(
            f"P9 selected families are invalid: {sorted(unsupported)}"
        )
    evidence_hashes, values = _validate_evidence(evidence)
    index_dates = tuple(str(value) for value in values["index_plan"]["trade_dates"])
    major_dates = tuple(str(value) for value in values["major_plan"]["trade_dates"])
    technical_dates = tuple(values["technical_plan"].trade_dates)
    stock_start, stock_end = _stock_dates(values["stock_plan"])
    registered = {
        cn_a_index_mins_trade_days.name: tuple(
            instance.get_dynamic_partitions(cn_a_index_mins_trade_days.name)
        ),
        cn_major_index_mins_trade_days.name: tuple(
            instance.get_dynamic_partitions(cn_major_index_mins_trade_days.name)
        ),
        cn_a_stock_mins_silver_trade_days.name: tuple(
            instance.get_dynamic_partitions(cn_a_stock_mins_silver_trade_days.name)
        ),
    }
    stock_dates = tuple(
        date
        for date in sorted(set(registered[cn_a_stock_mins_silver_trade_days.name]))
        if stock_start <= date <= stock_end
    )
    if len(stock_dates) != 3066:
        raise MinuteGoldP9EventError(
            "P9 stock date scope differs from frozen P7/P8 scope"
        )
    if _stock_dates_hash(stock_dates) != values["stock_plan"].get(
        "selected_partition_keys_hash"
    ):
        raise MinuteGoldP9EventError("P9 stock dates do not match the frozen P7 hash")
    recent = {
        cn_a_index_mins_trade_days.name: index_dates[-P9_CHECK_WINDOW:],
        cn_major_index_mins_trade_days.name: major_dates[-P9_CHECK_WINDOW:],
        cn_a_stock_mins_silver_trade_days.name: stock_dates[-P9_CHECK_WINDOW:],
    }
    missing = {
        cn_a_index_mins_trade_days.name: tuple(
            sorted(set(index_dates) - set(registered[cn_a_index_mins_trade_days.name]))
        ),
        cn_major_index_mins_trade_days.name: tuple(
            sorted(
                set(major_dates) - set(registered[cn_major_index_mins_trade_days.name])
            )
        ),
        cn_a_stock_mins_silver_trade_days.name: tuple(
            sorted(
                set(stock_dates)
                - set(registered[cn_a_stock_mins_silver_trade_days.name])
            )
        ),
    }

    assets: list[P9AssetSpec] = []
    if "index_gold" in selected_families:
        index_counts = _single_file_counts(
            index_dates,
            CN_A_GOLD_MINUTE_FREQS,
            lambda freq, date: gold_index_mins_path(lake_root, freq, date),
        )
        for freq, asset_key, check_name in zip(
            CN_A_GOLD_MINUTE_FREQS,
            INDEX_MINS_GOLD_ASSET_NAMES,
            INDEX_MINS_GOLD_CHECKS,
            strict=True,
        ):
            assets.append(
                _asset_spec(
                    family="index_gold",
                    asset_key=asset_key,
                    freq=freq,
                    partition_set=cn_a_index_mins_trade_days.name,
                    dates=index_dates,
                    check_names=(check_name,),
                    columns=GOLD_INDEX_MINS_SCHEMA,
                    uri_builder=lambda date, current=freq: gold_index_mins_path(
                        lake_root, current, date
                    ),
                    counts=index_counts,
                    source_method="cn_a_minute_gold_p6_canonical_rebuild",
                )
            )

    if "major_index_gold" in selected_families:
        major_counts = _single_file_counts(
            major_dates,
            CN_A_GOLD_MINUTE_FREQS,
            lambda freq, date: gold_major_index_mins_path(lake_root, freq, date),
        )
        for freq, asset_key, check_name in zip(
            CN_A_GOLD_MINUTE_FREQS,
            MAJOR_INDEX_MINS_GOLD_ASSET_KEYS,
            MAJOR_INDEX_MINS_GOLD_CHECKS,
            strict=True,
        ):
            assets.append(
                _asset_spec(
                    family="major_index_gold",
                    asset_key=asset_key,
                    freq=freq,
                    partition_set=cn_major_index_mins_trade_days.name,
                    dates=major_dates,
                    check_names=(check_name,),
                    columns=GOLD_MAJOR_INDEX_MINS_SCHEMA,
                    uri_builder=lambda date, current=freq: gold_major_index_mins_path(
                        lake_root, current, date
                    ),
                    counts=major_counts,
                    source_method="cn_a_minute_gold_p6_canonical_rebuild",
                )
            )

    if "major_index_technical_state" in selected_families:
        technical_counts = _single_file_counts(
            technical_dates,
            P9_FREQUENCIES,
            lambda freq, date: gold_major_index_mins_technical_path(
                lake_root, freq, date
            ),
        )
        technical_state_counts = _single_file_counts(
            technical_dates,
            P9_FREQUENCIES,
            lambda freq, date: gold_major_index_mins_technical_state_path(
                lake_root, freq, date
            ),
        )
        for freq in P9_FREQUENCIES:
            assets.extend(
                (
                    _asset_spec(
                        family="major_index_technical_state",
                        asset_key=major_index_mins_technical_asset_key(freq),
                        freq=freq,
                        partition_set=cn_major_index_mins_trade_days.name,
                        dates=technical_dates,
                        check_names=major_index_mins_technical_checks(freq),
                        columns=GOLD_MAJOR_INDEX_MINS_TECHNICAL_SCHEMA,
                        uri_builder=lambda date, current=freq: (
                            gold_major_index_mins_technical_path(
                                lake_root, current, date
                            )
                        ),
                        counts=technical_counts,
                        source_method="cn_a_minute_gold_p6_technical_rebuild",
                    ),
                    _asset_spec(
                        family="major_index_technical_state",
                        asset_key=major_index_mins_technical_state_asset_key(freq),
                        freq=freq,
                        partition_set=cn_major_index_mins_trade_days.name,
                        dates=technical_dates,
                        check_names=major_index_mins_technical_state_checks(freq),
                        columns=GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_SCHEMA,
                        uri_builder=lambda date, current=freq: (
                            gold_major_index_mins_technical_state_path(
                                lake_root, current, date
                            )
                        ),
                        counts=technical_state_counts,
                        source_method="cn_a_minute_gold_p6_technical_state_rebuild",
                    ),
                )
            )

    selected_stock_families = {
        "stock_qfq",
        "stock_indicator_state",
    }.intersection(selected_families)
    stock_counts: dict[tuple[int, str], int] = {}
    for freq in P9_FREQUENCIES:
        qfq_root = gold_stk_mins_qfq_path(
            lake_root, freq, "{ts_code}", "{year}"
        ).parents[2]
        indicator_root = gold_stk_mins_qfq_macd_kdj_path(
            lake_root, freq, "{ts_code}", "{year}"
        ).parents[2]
        if "stock_qfq" in selected_families:
            assets.append(
                _asset_spec(
                    family="stock_qfq",
                    asset_key=f"gold_stk_mins_qfq_{freq}m",
                    freq=freq,
                    partition_set=cn_a_stock_mins_silver_trade_days.name,
                    dates=stock_dates,
                    check_names=(
                        "gold_stk_mins_qfq_contract_check",
                        "gold_stk_mins_qfq_key_integrity_check",
                        "gold_stk_mins_qfq_value_domain_check",
                        "gold_stk_mins_qfq_source_coverage_check",
                    ),
                    columns=GOLD_STK_MINS_QFQ_SCHEMA,
                    uri_builder=lambda _date, root=qfq_root: root,
                    counts=stock_counts,
                    source_method="cn_a_minute_gold_p7_canonical_rebuild",
                )
            )
        if "stock_indicator_state" in selected_families:
            assets.extend(
                (
                    _asset_spec(
                        family="stock_indicator_state",
                        asset_key=f"gold_stk_mins_qfq_macd_kdj_{freq}m",
                        freq=freq,
                        partition_set=cn_a_stock_mins_silver_trade_days.name,
                        dates=stock_dates,
                        check_names=(
                            "gold_stk_mins_qfq_macd_kdj_contract_check",
                            "gold_stk_mins_qfq_macd_kdj_source_coverage_check",
                        ),
                        columns=GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
                        uri_builder=lambda _date, root=indicator_root: root,
                        counts=stock_counts,
                        source_method="cn_a_minute_gold_p8_indicator_rebuild",
                    ),
                    _asset_spec(
                        family="stock_indicator_state",
                        asset_key=f"gold_stk_mins_qfq_macd_kdj_state_{freq}m",
                        freq=freq,
                        partition_set=cn_a_stock_mins_silver_trade_days.name,
                        dates=stock_dates,
                        check_names=(
                            "gold_stk_mins_qfq_macd_kdj_state_file_exists_and_schema_check",
                            "gold_stk_mins_qfq_macd_kdj_state_latest_coverage_check",
                        ),
                        columns=GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
                        uri_builder=lambda date, current=freq: (
                            gold_stk_mins_qfq_macd_kdj_state_path(
                                lake_root, current, date
                            )
                        ),
                        counts=stock_counts,
                        source_method="cn_a_minute_gold_p8_state_rebuild",
                    ),
                )
            )

    check_audits: dict[str, tuple[dg.AssetCheckResult, ...]] = {}
    duckdb_resource = DuckDBResource()
    for spec in assets:
        for date in recent[spec.partition_set]:
            if spec.family == "index_gold":
                source_freq = CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[spec.freq]
                with duckdb_resource.connect() as connection:
                    results = (
                        evaluate_canonical_gold_minute_core_check(
                            connection=connection,
                            target_path=gold_index_mins_path(
                                lake_root, spec.freq, date
                            ),
                            source_path=silver_index_mins_path(
                                lake_root, f"{source_freq}min", date
                            ),
                            target_freq=spec.freq,
                            partition_key=date,
                        ),
                    )
            elif spec.family == "major_index_gold":
                source_freq = CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[spec.freq]
                with duckdb_resource.connect() as connection:
                    results = (
                        evaluate_canonical_gold_minute_core_check(
                            connection=connection,
                            target_path=gold_major_index_mins_path(
                                lake_root, spec.freq, date
                            ),
                            source_path=silver_major_index_mins_path(
                                lake_root, f"{source_freq}min", date
                            ),
                            target_freq=spec.freq,
                            partition_key=date,
                            expected_codes=effective_silver_codes_for_date(date),
                        ),
                    )
            elif spec.family == "major_index_technical_state":
                if "_state_" in spec.asset_key:
                    results = tuple(
                        evaluate_major_index_mins_technical_state_check(
                            lake_root_path=lake_root,
                            duckdb_resource=duckdb_resource,
                            partition_key=date,
                            freq=spec.freq,
                            check_kind=kind,
                            expected_trade_dates=technical_dates,
                        )
                        for kind in _STATE_CHECK_KINDS
                    )
                else:
                    results = tuple(
                        evaluate_major_index_mins_technical_check(
                            lake_root_path=lake_root,
                            duckdb_resource=duckdb_resource,
                            partition_key=date,
                            freq=spec.freq,
                            check_kind=kind,
                        )
                        for kind in _TECHNICAL_CHECK_KINDS
                    )
            elif spec.family == "stock_indicator_state":
                continue
            else:
                continue
            check_audits[f"{spec.asset_key}|{date}"] = results

    if "stock_indicator_state" in selected_stock_families:
        recent_stock = recent[cn_a_stock_mins_silver_trade_days.name]
        for freq in P9_FREQUENCIES:
            check_audits.update(
                audit_stock_indicator_state_partitions(
                    lake_root=lake_root,
                    freq=freq,
                    dates=recent_stock,
                )
            )

    if "stock_qfq" in selected_families:
        stock_plan = values["stock_plan"]
        factor_manifest = stock_plan.get("as_of_adj_factor_snapshot_manifest")
        if not isinstance(factor_manifest, Mapping):
            raise MinuteGoldP9EventError("P7 factor snapshot manifest is missing")
        factor_path = Path(str(factor_manifest.get("path") or ""))
        if _sha256(factor_path) != factor_manifest.get("sha256"):
            raise MinuteGoldP9EventError("P7 factor snapshot changed after P7")
        recent_stock = recent[cn_a_stock_mins_silver_trade_days.name]
        for freq in P9_FREQUENCIES:
            for year in sorted({date[:4] for date in recent_stock}):
                year_dates = tuple(
                    date for date in recent_stock if date.startswith(year)
                )
                audit_rows = audit_stk_mins_qfq_bootstrap_batch(
                    lake_root=lake_root,
                    duckdb=duckdb_resource,
                    batch=StkMinsQfqHistoryBatch(
                        freq=freq,
                        year=year,
                        partition_keys=year_dates,
                    ),
                    as_of_trade_date=stock_end,
                    as_of_adj_factor_path=factor_path,
                )
                for audit in audit_rows:
                    key = f"{audit.asset_key.to_user_string()}|{audit.partition_key}"
                    check_audits[key] = tuple(
                        dg.AssetCheckResult(
                            passed=check.passed, metadata=check.metadata
                        )
                        for check in audit.checks
                    )

    global_asset_identity = [
        *(
            {
                "family": "index_gold",
                "asset_key": asset_key,
                "freq": freq,
                "partition_set": cn_a_index_mins_trade_days.name,
                "start": index_dates[0],
                "end": index_dates[-1],
                "count": len(index_dates),
                "checks": (check_name,),
            }
            for freq, asset_key, check_name in zip(
                CN_A_GOLD_MINUTE_FREQS,
                INDEX_MINS_GOLD_ASSET_NAMES,
                INDEX_MINS_GOLD_CHECKS,
                strict=True,
            )
        ),
        *(
            {
                "family": "major_index_gold",
                "asset_key": asset_key,
                "freq": freq,
                "partition_set": cn_major_index_mins_trade_days.name,
                "start": major_dates[0],
                "end": major_dates[-1],
                "count": len(major_dates),
                "checks": (check_name,),
            }
            for freq, asset_key, check_name in zip(
                CN_A_GOLD_MINUTE_FREQS,
                MAJOR_INDEX_MINS_GOLD_ASSET_KEYS,
                MAJOR_INDEX_MINS_GOLD_CHECKS,
                strict=True,
            )
        ),
    ]
    for freq in P9_FREQUENCIES:
        global_asset_identity.extend(
            (
                {
                    "family": "major_index_technical_state",
                    "asset_key": major_index_mins_technical_asset_key(freq),
                    "freq": freq,
                    "partition_set": cn_major_index_mins_trade_days.name,
                    "start": technical_dates[0],
                    "end": technical_dates[-1],
                    "count": len(technical_dates),
                    "checks": major_index_mins_technical_checks(freq),
                },
                {
                    "family": "major_index_technical_state",
                    "asset_key": major_index_mins_technical_state_asset_key(freq),
                    "freq": freq,
                    "partition_set": cn_major_index_mins_trade_days.name,
                    "start": technical_dates[0],
                    "end": technical_dates[-1],
                    "count": len(technical_dates),
                    "checks": major_index_mins_technical_state_checks(freq),
                },
                {
                    "family": "stock_qfq",
                    "asset_key": f"gold_stk_mins_qfq_{freq}m",
                    "freq": freq,
                    "partition_set": cn_a_stock_mins_silver_trade_days.name,
                    "start": stock_dates[0],
                    "end": stock_dates[-1],
                    "count": len(stock_dates),
                    "checks": (
                        "gold_stk_mins_qfq_contract_check",
                        "gold_stk_mins_qfq_key_integrity_check",
                        "gold_stk_mins_qfq_value_domain_check",
                        "gold_stk_mins_qfq_source_coverage_check",
                    ),
                },
                {
                    "family": "stock_indicator_state",
                    "asset_key": f"gold_stk_mins_qfq_macd_kdj_{freq}m",
                    "freq": freq,
                    "partition_set": cn_a_stock_mins_silver_trade_days.name,
                    "start": stock_dates[0],
                    "end": stock_dates[-1],
                    "count": len(stock_dates),
                    "checks": (
                        "gold_stk_mins_qfq_macd_kdj_contract_check",
                        "gold_stk_mins_qfq_macd_kdj_source_coverage_check",
                    ),
                },
                {
                    "family": "stock_indicator_state",
                    "asset_key": f"gold_stk_mins_qfq_macd_kdj_state_{freq}m",
                    "freq": freq,
                    "partition_set": cn_a_stock_mins_silver_trade_days.name,
                    "start": stock_dates[0],
                    "end": stock_dates[-1],
                    "count": len(stock_dates),
                    "checks": (
                        "gold_stk_mins_qfq_macd_kdj_state_file_exists_and_schema_check",
                        "gold_stk_mins_qfq_macd_kdj_state_latest_coverage_check",
                    ),
                },
            )
        )

    plan_identity = {
        "revision": P9_REVISION,
        "evidence_hashes": evidence_hashes,
        "assets": global_asset_identity,
        "recent": recent,
    }
    return P9Plan(
        plan_hash=_hash_payload(plan_identity),
        evidence_hashes=evidence_hashes,
        assets=tuple(assets),
        recent_dates_by_partition_set=recent,
        missing_registered=missing,
        active_run_count=_active_run_count(instance),
        check_audits=check_audits,
        elapsed_ms=(perf_counter() - started) * 1_000,
    )


def apply_p9_family(
    *,
    instance: Any,
    plan: P9Plan,
    family: str,
    checkpoint_path: Path,
    expected_plan_hash: str,
) -> P9EventReport:
    if family not in P9_FAMILIES:
        raise MinuteGoldP9EventError(f"unsupported P9 family: {family}")
    if plan.plan_hash != expected_plan_hash:
        raise MinuteGoldP9EventError(
            "P9 explicit plan hash does not match current evidence"
        )
    if plan.should_stop:
        raise MinuteGoldP9EventError(
            "P9 apply is blocked by preflight or check failures"
        )
    started = perf_counter()
    completed = _checkpoint(checkpoint_path, plan_hash=plan.plan_hash)
    reported_materializations = 0
    reported_checks = 0
    refreshed_indexes = 0
    skipped = 0
    for spec in (asset for asset in plan.assets if asset.family == family):
        recent = set(plan.recent_dates_by_partition_set[spec.partition_set])
        for date in spec.trade_dates:
            identity = f"{spec.asset_key}|{date}"
            if identity in completed:
                skipped += 1
                continue
            existing_p9_materialization = _latest_materialization_for_p9(
                instance,
                asset_key=spec.asset_key,
                partition=date,
                plan_hash=plan.plan_hash,
            )
            if existing_p9_materialization is None:
                _report_materialization(instance, plan=plan, spec=spec, date=date)
                reported_materializations += 1
            if date in recent:
                reported, refreshed = _report_checks(
                    instance,
                    plan=plan,
                    spec=spec,
                    date=date,
                )
                reported_checks += reported
                refreshed_indexes += refreshed
            completed.add(identity)
            if len(completed) % 250 == 0:
                _write_checkpoint(
                    checkpoint_path, plan_hash=plan.plan_hash, completed=completed
                )
        _write_checkpoint(
            checkpoint_path, plan_hash=plan.plan_hash, completed=completed
        )
    return P9EventReport(
        mode="apply",
        family=family,
        plan=plan,
        reported_materializations=reported_materializations,
        reported_checks=reported_checks,
        refreshed_runless_check_indexes=refreshed_indexes,
        skipped_checkpoint_items=skipped,
        elapsed_ms=(perf_counter() - started) * 1_000,
    )


def post_audit_p9_family(
    *,
    instance: Any,
    plan: P9Plan,
    family: str,
    checkpoint_path: Path,
    expected_plan_hash: str,
) -> P9EventReport:
    if plan.plan_hash != expected_plan_hash:
        raise MinuteGoldP9EventError("P9 post-audit plan hash mismatch")
    expected = {
        f"{spec.asset_key}|{date}"
        for spec in plan.assets
        if spec.family == family
        for date in spec.trade_dates
    }
    completed = _checkpoint(checkpoint_path, plan_hash=plan.plan_hash)
    if not expected.issubset(completed):
        raise MinuteGoldP9EventError(
            f"P9 post-audit checkpoint is incomplete: missing={len(expected - completed)}"
        )
    for spec in (asset for asset in plan.assets if asset.family == family):
        materialized = instance.get_materialized_partitions(dg.AssetKey(spec.asset_key))
        missing = set(spec.trade_dates) - set(materialized)
        if missing:
            raise MinuteGoldP9EventError(
                f"P9 post-audit materializations are incomplete: {spec.asset_key}:{sorted(missing)[:10]}"
            )
        for date in plan.recent_dates_by_partition_set[spec.partition_set]:
            _latest_materialization(instance, spec.asset_key, date)
        _assert_latest_bound_checks(
            instance,
            spec=spec,
            partitions=plan.recent_dates_by_partition_set[spec.partition_set],
        )
    return P9EventReport(mode="post-audit", family=family, plan=plan)


def write_p9_report(report: P9Plan | P9EventReport, path: Path) -> None:
    _atomic_json(path, report.to_dict())


__all__ = [
    "P9_FAMILIES",
    "P9EventReport",
    "P9Evidence",
    "P9Plan",
    "apply_p9_family",
    "build_p9_plan",
    "post_audit_p9_family",
    "write_p9_report",
]
