from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.assets.wealth_market_turnover_prod_core import (
    load_gold_wealth_market_turnover_rows_for_prod_sync,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_wealth_market_turnover_path,
    gold_wealth_market_turnover_staging_path,
)
from orchestrator.defs.prod_db.wealth_market_turnover import (
    replace_prod_core_wealth_market_turnover_partition,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS
from orchestrator.defs.wealth_market_turnover_contract import (
    WEALTH_MARKET_TURNOVER_BUILD_VERSION,
    WealthMarketTurnoverIntegrityAudit,
    WealthMarketTurnoverMinuteSourcePath,
    WealthMarketTurnoverSourcePaths,
    WealthMarketTurnoverWriteAudit,
    audit_gold_wealth_market_turnover_file_contract,
    audit_gold_wealth_market_turnover_recomputed_from_sources,
    build_gold_wealth_market_turnover_candidate,
    wealth_market_turnover_source_paths,
)

WEALTH_MARKET_TURNOVER_WMT7_HISTORY_START_DATE = "2021-11-15"
WEALTH_MARKET_TURNOVER_HISTORY_BATCH_SIZE_LIMIT = 20
WEALTH_MARKET_TURNOVER_HISTORY_AUDIT_SECONDS_LIMIT = 300
WEALTH_MARKET_TURNOVER_CORRECTION_METHOD = "bse_close_auction_daily_residual"
# Existing runless maintenance remains a separate, unchanged recent-window tool.
WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE = 20


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverFileFingerprint:
    path: str
    size: int
    mtime_ns: int
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverPartitionPlan:
    partition_key: str
    source_files: tuple[WealthMarketTurnoverFileFingerprint, ...]
    target_path: str
    target_file: WealthMarketTurnoverFileFingerprint | None


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverHistoryPlan:
    selected_partition_keys: tuple[str, ...]
    partition_plans: tuple[WealthMarketTurnoverPartitionPlan, ...]
    plan_hash: str
    staging_root: str
    batch_size: int
    build_version: str
    correction_method: str
    eligible_source_partition_count: int
    already_ready_partition_count: int
    planned_write_count: int
    planned_event_count: int
    sample_partition_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def wealth_market_turnover_history_plan_from_dict(
    payload: Mapping[str, object],
) -> WealthMarketTurnoverHistoryPlan:
    partition_plans = tuple(
        WealthMarketTurnoverPartitionPlan(
            partition_key=str(partition_payload["partition_key"]),
            source_files=tuple(
                WealthMarketTurnoverFileFingerprint(**source_payload)
                for source_payload in partition_payload["source_files"]
            ),
            target_path=str(partition_payload["target_path"]),
            target_file=(
                WealthMarketTurnoverFileFingerprint(
                    **partition_payload["target_file"]
                )
                if partition_payload.get("target_file") is not None
                else None
            ),
        )
        for partition_payload in payload["partition_plans"]
    )
    plan = WealthMarketTurnoverHistoryPlan(
        selected_partition_keys=tuple(payload["selected_partition_keys"]),
        partition_plans=partition_plans,
        plan_hash=str(payload["plan_hash"]),
        staging_root=str(payload["staging_root"]),
        batch_size=int(payload["batch_size"]),
        build_version=str(payload["build_version"]),
        correction_method=str(payload["correction_method"]),
        eligible_source_partition_count=int(
            payload["eligible_source_partition_count"]
        ),
        already_ready_partition_count=int(payload["already_ready_partition_count"]),
        planned_write_count=int(payload["planned_write_count"]),
        planned_event_count=int(payload["planned_event_count"]),
        sample_partition_keys=tuple(payload["sample_partition_keys"]),
    )
    _assert_plan_hash(plan)
    return plan


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverHistoryWriteReport:
    plan_hash: str
    selected_partition_keys: tuple[str, ...]
    written_partition_keys: tuple[str, ...]
    write_results: tuple[WealthMarketTurnoverWriteAudit, ...]
    candidate_hashes: Mapping[str, str]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_hash": self.plan_hash,
            "selected_partition_keys": list(self.selected_partition_keys),
            "written_partition_keys": list(self.written_partition_keys),
            "write_results": [_write_audit_payload(result) for result in self.write_results],
            "candidate_hashes": dict(self.candidate_hashes),
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverHistoryPartitionAudit:
    partition_key: str
    target_path: Path
    passed: bool
    file_contract: WealthMarketTurnoverIntegrityAudit
    recomputed_from_sources: WealthMarketTurnoverIntegrityAudit | None
    file_hash: str | None

    @property
    def reason_code(self) -> str | None:
        if self.file_contract.reason_code is not None:
            return self.file_contract.reason_code
        if self.recomputed_from_sources is not None:
            return self.recomputed_from_sources.reason_code
        return None

    @property
    def checked_row_count(self) -> int:
        if self.recomputed_from_sources is not None:
            return self.recomputed_from_sources.checked_row_count
        return self.file_contract.checked_row_count

    def to_dict(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "target_path": str(self.target_path),
            "passed": self.passed,
            "reason_code": self.reason_code,
            "file_hash": self.file_hash,
            "file_contract": _integrity_audit_payload(self.file_contract),
            "recomputed_from_sources": (
                _integrity_audit_payload(self.recomputed_from_sources)
                if self.recomputed_from_sources is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverHistoryAuditReport:
    plan_hash: str
    selected_partition_keys: tuple[str, ...]
    target_file_count: int
    target_row_count: int
    target_date_min: str | None
    target_date_max: str | None
    failed_partition_count: int
    reason_counts: Mapping[str, int]
    partition_audits: tuple[WealthMarketTurnoverHistoryPartitionAudit, ...]
    elapsed_ms: float

    @property
    def passed(self) -> bool:
        return self.failed_partition_count == 0

    @property
    def file_hashes(self) -> dict[str, str]:
        return {
            audit.partition_key: audit.file_hash
            for audit in self.partition_audits
            if audit.passed and audit.file_hash is not None
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_hash": self.plan_hash,
            "selected_partition_keys": list(self.selected_partition_keys),
            "selected_trade_date_count": len(self.selected_partition_keys),
            "target_file_count": self.target_file_count,
            "target_row_count": self.target_row_count,
            "target_date_min": self.target_date_min,
            "target_date_max": self.target_date_max,
            "failed_partition_count": self.failed_partition_count,
            "reason_counts": dict(self.reason_counts),
            "partition_audits": [audit.to_dict() for audit in self.partition_audits],
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverPromoteReport:
    plan_hash: str
    promoted_partition_keys: tuple[str, ...]
    already_promoted_partition_keys: tuple[str, ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverProdPublishReport:
    plan_hash: str
    published_partition_keys: tuple[str, ...]
    last_successful_partition_key: str | None
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def discover_wealth_market_turnover_target_partitions(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> tuple[str, ...]:
    target_root = Path(lake_root) / "gold" / "wealth" / "market_turnover"
    return tuple(
        sorted(
            path.parent.name.removeprefix("trade_date=")
            for path in target_root.glob("trade_date=*/part-000.parquet")
            if path.is_file()
        )
    )


def discover_complete_source_partitions_for_turnover(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    *,
    start_date: str = WEALTH_MARKET_TURNOVER_WMT7_HISTORY_START_DATE,
    end_date: str | None = None,
) -> tuple[str, ...]:
    partition_sets: list[set[str]] = []
    for freq in STK_MINS_FREQS:
        root = Path(lake_root) / "silver" / "quote" / "stk_mins" / f"freq={freq}"
        partition_sets.append(
            {
                path.parent.name.removeprefix("trade_date=")
                for path in root.glob("trade_date=*/part-000.parquet")
                if path.is_file()
            }
        )
    daily_root = Path(lake_root) / "silver" / "quote" / "stock_daily"
    partition_sets.append(
        {
            path.parent.name.removeprefix("trade_date=")
            for path in daily_root.glob("trade_date=*/part-000.parquet")
            if path.is_file()
        }
    )
    if not partition_sets:
        return ()
    complete = set.intersection(*partition_sets)
    return _filter_partition_keys(complete, start_date=start_date, end_date=end_date)


def plan_wealth_market_turnover_history(
    *,
    duckdb_resource: DuckDBResource,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
    partition_keys: Sequence[str] | None = None,
    start_date: str = WEALTH_MARKET_TURNOVER_WMT7_HISTORY_START_DATE,
    end_date: str | None = None,
    batch_size: int = WEALTH_MARKET_TURNOVER_HISTORY_BATCH_SIZE_LIMIT,
) -> WealthMarketTurnoverHistoryPlan:
    _validate_batch_size(batch_size)
    effective_start = max(start_date, WEALTH_MARKET_TURNOVER_WMT7_HISTORY_START_DATE)
    complete_keys = discover_complete_source_partitions_for_turnover(
        lake_root,
        start_date=effective_start,
        end_date=end_date,
    )
    requested_keys = _select_partition_keys(
        complete_keys,
        partition_keys=partition_keys,
        start_date=effective_start,
        end_date=end_date,
    )
    selected_plans: list[WealthMarketTurnoverPartitionPlan] = []
    ready_count = 0
    with duckdb_resource.connect() as connection:
        for partition_key in requested_keys:
            source_paths = wealth_market_turnover_source_paths(lake_root, partition_key)
            if not _stock_daily_contains_bse(connection, source_paths.stock_daily_path):
                continue
            target_path = gold_wealth_market_turnover_path(lake_root, partition_key)
            if _target_is_current_v2(
                connection=connection,
                target_path=target_path,
                source_paths=source_paths,
                partition_key=partition_key,
            ):
                ready_count += 1
                continue
            selected_plans.append(
                WealthMarketTurnoverPartitionPlan(
                    partition_key=partition_key,
                    source_files=tuple(
                        _fingerprint_file(path, include_hash=False)
                        for path in _source_paths_for_partition(lake_root, partition_key)
                    ),
                    target_path=str(target_path.resolve()),
                    target_file=(
                        _fingerprint_file(target_path, include_hash=True)
                        if target_path.exists()
                        else None
                    ),
                )
            )
    selected_keys = tuple(plan.partition_key for plan in selected_plans)
    resolved_staging_root = str(Path(staging_root).resolve())
    plan_hash = _calculate_plan_hash(
        selected_partition_keys=selected_keys,
        partition_plans=selected_plans,
        staging_root=resolved_staging_root,
        batch_size=batch_size,
        build_version=WEALTH_MARKET_TURNOVER_BUILD_VERSION,
        correction_method=WEALTH_MARKET_TURNOVER_CORRECTION_METHOD,
    )
    return WealthMarketTurnoverHistoryPlan(
        selected_partition_keys=selected_keys,
        partition_plans=tuple(selected_plans),
        plan_hash=plan_hash,
        staging_root=resolved_staging_root,
        batch_size=batch_size,
        build_version=WEALTH_MARKET_TURNOVER_BUILD_VERSION,
        correction_method=WEALTH_MARKET_TURNOVER_CORRECTION_METHOD,
        eligible_source_partition_count=len(requested_keys),
        already_ready_partition_count=ready_count,
        planned_write_count=len(selected_keys),
        planned_event_count=0,
        sample_partition_keys=_sample_partition_keys(selected_keys),
    )


def build_wealth_market_turnover_history_candidates(
    *,
    plan: WealthMarketTurnoverHistoryPlan,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    partition_keys: Sequence[str],
) -> WealthMarketTurnoverHistoryWriteReport:
    _assert_plan_hash(plan)
    selected_keys = _selected_plan_batch(plan, partition_keys)
    started_at = perf_counter()
    written: list[str] = []
    results: list[WealthMarketTurnoverWriteAudit] = []
    candidate_hashes: dict[str, str] = {}
    for partition_key in selected_keys:
        partition_plan = _partition_plan(plan, partition_key)
        _assert_source_fingerprints_unchanged(partition_plan)
        _assert_partition_paths_match_lake_root(
            partition_plan=partition_plan,
            lake_root=lake_root,
        )
        candidate_path = _candidate_path(plan, partition_key)
        result = build_gold_wealth_market_turnover_candidate(
            duckdb_resource=duckdb_resource,
            source_paths=_source_bundle_from_partition_plan(partition_plan),
            partition_key=partition_key,
            candidate_path=candidate_path,
        )
        written.append(partition_key)
        results.append(result)
        candidate_hashes[partition_key] = _sha256_file(candidate_path)
    return WealthMarketTurnoverHistoryWriteReport(
        plan_hash=plan.plan_hash,
        selected_partition_keys=selected_keys,
        written_partition_keys=tuple(written),
        write_results=tuple(results),
        candidate_hashes=candidate_hashes,
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def audit_wealth_market_turnover_history_candidates(
    *,
    plan: WealthMarketTurnoverHistoryPlan,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    partition_keys: Sequence[str],
    expected_candidate_hashes: Mapping[str, str] | None = None,
) -> WealthMarketTurnoverHistoryAuditReport:
    _assert_plan_hash(plan)
    selected_keys = _selected_plan_batch(plan, partition_keys)
    return _audit_paths(
        plan=plan,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        partition_keys=selected_keys,
        target_paths={key: _candidate_path(plan, key) for key in selected_keys},
        expected_hashes=expected_candidate_hashes,
    )


def promote_wealth_market_turnover_history_candidates(
    *,
    plan: WealthMarketTurnoverHistoryPlan,
    lake_root: Path,
    partition_keys: Sequence[str],
    candidate_hashes: Mapping[str, str],
) -> WealthMarketTurnoverPromoteReport:
    _assert_plan_hash(plan)
    selected_keys = _selected_plan_batch(plan, partition_keys)
    started_at = perf_counter()
    promoted: list[str] = []
    already_promoted: list[str] = []
    for partition_key in selected_keys:
        expected_candidate_hash = candidate_hashes.get(partition_key)
        if not expected_candidate_hash:
            raise ValueError(f"Missing candidate hash for partition {partition_key}.")
        partition_plan = _partition_plan(plan, partition_key)
        _assert_source_fingerprints_unchanged(partition_plan)
        _assert_partition_paths_match_lake_root(
            partition_plan=partition_plan,
            lake_root=lake_root,
        )
        candidate_path = _candidate_path(plan, partition_key)
        target_path = Path(partition_plan.target_path)
        if not candidate_path.exists():
            if target_path.exists() and _sha256_file(target_path) == expected_candidate_hash:
                already_promoted.append(partition_key)
                continue
            raise FileNotFoundError(
                f"Missing candidate file for partition {partition_key}: {candidate_path}"
            )
        if _sha256_file(candidate_path) != expected_candidate_hash:
            raise RuntimeError(f"Candidate hash changed for partition {partition_key}.")
        _assert_target_unchanged(partition_plan, target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if os.stat(candidate_path.parent).st_dev != os.stat(target_path.parent).st_dev:
            raise RuntimeError("candidate and formal target are not on the same filesystem")
        os.replace(candidate_path, target_path)
        if _sha256_file(target_path) != expected_candidate_hash:
            raise RuntimeError(
                f"Formal target hash mismatch after promote for {partition_key}."
            )
        promoted.append(partition_key)
    return WealthMarketTurnoverPromoteReport(
        plan_hash=plan.plan_hash,
        promoted_partition_keys=tuple(promoted),
        already_promoted_partition_keys=tuple(already_promoted),
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def audit_wealth_market_turnover_history(
    *,
    plan: WealthMarketTurnoverHistoryPlan | None = None,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    partition_keys: Sequence[str],
    expected_hashes: Mapping[str, str] | None = None,
) -> WealthMarketTurnoverHistoryAuditReport:
    if plan is None:
        plan = _build_direct_audit_plan(
            lake_root=lake_root,
            partition_keys=partition_keys,
        )
    _assert_plan_hash(plan)
    selected_keys = _selected_plan_batch(plan, partition_keys)
    return _audit_paths(
        plan=plan,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        partition_keys=selected_keys,
        target_paths={
            key: Path(_partition_plan(plan, key).target_path)
            for key in selected_keys
        },
        expected_hashes=expected_hashes,
    )


def publish_wealth_market_turnover_history_to_prod(
    *,
    plan: WealthMarketTurnoverHistoryPlan,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    prod_postgres_write,
    partition_keys: Sequence[str],
    formal_audit_hashes: Mapping[str, str],
) -> WealthMarketTurnoverProdPublishReport:
    _assert_plan_hash(plan)
    selected_keys = _selected_plan_batch(plan, partition_keys)
    started_at = perf_counter()
    published: list[str] = []
    for partition_key in selected_keys:
        partition_plan = _partition_plan(plan, partition_key)
        _assert_source_fingerprints_unchanged(partition_plan)
        _assert_partition_paths_match_lake_root(
            partition_plan=partition_plan,
            lake_root=lake_root,
        )
        source_path = Path(partition_plan.target_path)
        expected_hash = formal_audit_hashes.get(partition_key)
        if expected_hash is None:
            raise ValueError(
                f"Missing formal audit hash for partition {partition_key}."
            )
        if not source_path.exists() or _sha256_file(source_path) != expected_hash:
            raise RuntimeError(
                f"Formal Gold changed after audit for partition {partition_key}."
            )
        rows = load_gold_wealth_market_turnover_rows_for_prod_sync(
            duckdb_resource=duckdb_resource,
            source_path=source_path,
            partition_key=partition_key,
        )
        with prod_postgres_write.connect() as connection:
            replace_prod_core_wealth_market_turnover_partition(
                connection=connection,
                rows=rows,
                partition_key=partition_key,
            )
        published.append(partition_key)
    return WealthMarketTurnoverProdPublishReport(
        plan_hash=plan.plan_hash,
        published_partition_keys=tuple(published),
        last_successful_partition_key=published[-1] if published else None,
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def _audit_paths(
    *,
    plan: WealthMarketTurnoverHistoryPlan,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    partition_keys: tuple[str, ...],
    target_paths: Mapping[str, Path],
    expected_hashes: Mapping[str, str] | None,
) -> WealthMarketTurnoverHistoryAuditReport:
    started_at = perf_counter()
    audits: list[WealthMarketTurnoverHistoryPartitionAudit] = []
    with duckdb_resource.connect() as connection:
        for partition_key in partition_keys:
            partition_plan = _partition_plan(plan, partition_key)
            _assert_source_fingerprints_unchanged(partition_plan)
            _assert_partition_paths_match_lake_root(
                partition_plan=partition_plan,
                lake_root=lake_root,
            )
            target_path = target_paths[partition_key]
            file_audit = audit_gold_wealth_market_turnover_file_contract(
                connection=connection,
                target_path=target_path,
                partition_key=partition_key,
            )
            recompute_audit = None
            if file_audit.passed:
                recompute_audit = audit_gold_wealth_market_turnover_recomputed_from_sources(
                    connection=connection,
                    target_path=target_path,
                    source_paths=_source_bundle_from_partition_plan(partition_plan),
                    partition_key=partition_key,
                )
            file_hash = _sha256_file(target_path) if target_path.exists() else None
            expected_hash = (expected_hashes or {}).get(partition_key)
            hash_matches = expected_hash is None or file_hash == expected_hash
            audits.append(
                WealthMarketTurnoverHistoryPartitionAudit(
                    partition_key=partition_key,
                    target_path=target_path,
                    passed=(
                        file_audit.passed
                        and recompute_audit is not None
                        and recompute_audit.passed
                        and hash_matches
                    ),
                    file_contract=file_audit,
                    recomputed_from_sources=recompute_audit,
                    file_hash=file_hash,
                )
            )
            if (
                perf_counter() - started_at
                > WEALTH_MARKET_TURNOVER_HISTORY_AUDIT_SECONDS_LIMIT
            ):
                raise RuntimeError(
                    "wealth_market_turnover_history_audit_exceeded_300_seconds"
                )
    reason_counts: dict[str, int] = {}
    passed_keys: list[str] = []
    target_row_count = 0
    for audit in audits:
        if audit.passed:
            passed_keys.append(audit.partition_key)
            target_row_count += audit.checked_row_count
        else:
            reason = audit.reason_code or "candidate_hash_mismatch"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return WealthMarketTurnoverHistoryAuditReport(
        plan_hash=plan.plan_hash,
        selected_partition_keys=partition_keys,
        target_file_count=sum(1 for path in target_paths.values() if path.exists()),
        target_row_count=target_row_count,
        target_date_min=passed_keys[0] if passed_keys else None,
        target_date_max=passed_keys[-1] if passed_keys else None,
        failed_partition_count=sum(1 for audit in audits if not audit.passed),
        reason_counts=reason_counts,
        partition_audits=tuple(audits),
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def _target_is_current_v2(
    *,
    connection,
    target_path: Path,
    source_paths,
    partition_key: str,
) -> bool:
    if not target_path.exists():
        return False
    file_audit = audit_gold_wealth_market_turnover_file_contract(
        connection=connection,
        target_path=target_path,
        partition_key=partition_key,
    )
    if not file_audit.passed:
        return False
    recompute = audit_gold_wealth_market_turnover_recomputed_from_sources(
        connection=connection,
        target_path=target_path,
        source_paths=source_paths,
        partition_key=partition_key,
    )
    return recompute.passed


def _stock_daily_contains_bse(connection, path: Path) -> bool:
    return bool(
        connection.execute(
            f"""
            SELECT count(*) > 0
            FROM read_parquet('{path.as_posix()}', hive_partitioning=false)
            WHERE upper(trim(CAST(ts_code AS VARCHAR))) LIKE '%.BJ'
            """
        ).fetchone()[0]
    )


def _source_paths_for_partition(lake_root: Path, partition_key: str) -> tuple[Path, ...]:
    source_paths = wealth_market_turnover_source_paths(lake_root, partition_key)
    return tuple(path.path for path in source_paths.minute_paths) + (
        source_paths.stock_daily_path,
    )


def _source_bundle_from_partition_plan(
    partition_plan: WealthMarketTurnoverPartitionPlan,
) -> WealthMarketTurnoverSourcePaths:
    expected_count = len(STK_MINS_FREQS) + 1
    if len(partition_plan.source_files) != expected_count:
        raise RuntimeError(
            "wealth market turnover plan source file count mismatch: "
            f"partition={partition_plan.partition_key}, "
            f"observed={len(partition_plan.source_files)}, expected={expected_count}."
        )
    return WealthMarketTurnoverSourcePaths(
        minute_paths=tuple(
            WealthMarketTurnoverMinuteSourcePath(freq=freq, path=Path(source.path))
            for freq, source in zip(
                STK_MINS_FREQS,
                partition_plan.source_files[:-1],
                strict=True,
            )
        ),
        stock_daily_path=Path(partition_plan.source_files[-1].path),
    )


def _assert_partition_paths_match_lake_root(
    *,
    partition_plan: WealthMarketTurnoverPartitionPlan,
    lake_root: Path,
) -> None:
    expected_sources = tuple(
        str(path.resolve())
        for path in _source_paths_for_partition(
            lake_root,
            partition_plan.partition_key,
        )
    )
    observed_sources = tuple(source.path for source in partition_plan.source_files)
    expected_target = str(
        gold_wealth_market_turnover_path(
            lake_root,
            partition_plan.partition_key,
        ).resolve()
    )
    if observed_sources != expected_sources or partition_plan.target_path != expected_target:
        raise RuntimeError(
            "wealth market turnover plan does not match the requested lake root: "
            f"partition={partition_plan.partition_key}."
        )


def _calculate_plan_hash(
    *,
    selected_partition_keys: Sequence[str],
    partition_plans: Sequence[WealthMarketTurnoverPartitionPlan],
    staging_root: str,
    batch_size: int,
    build_version: str,
    correction_method: str,
) -> str:
    payload = {
        "selected_partition_keys": list(selected_partition_keys),
        "partition_plans": [asdict(plan) for plan in partition_plans],
        "staging_root": staging_root,
        "batch_size": batch_size,
        "build_version": build_version,
        "correction_method": correction_method,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _assert_plan_hash(plan: WealthMarketTurnoverHistoryPlan) -> None:
    observed_hash = _calculate_plan_hash(
        selected_partition_keys=plan.selected_partition_keys,
        partition_plans=plan.partition_plans,
        staging_root=plan.staging_root,
        batch_size=plan.batch_size,
        build_version=plan.build_version,
        correction_method=plan.correction_method,
    )
    if observed_hash != plan.plan_hash:
        raise RuntimeError(
            "wealth market turnover history plan hash mismatch: "
            f"expected={plan.plan_hash}, observed={observed_hash}."
        )


def _build_direct_audit_plan(
    *,
    lake_root: Path,
    partition_keys: Sequence[str],
) -> WealthMarketTurnoverHistoryPlan:
    selected_keys = tuple(sorted(set(partition_keys)))
    _validate_batch_size(len(selected_keys))
    partition_plans = tuple(
        WealthMarketTurnoverPartitionPlan(
            partition_key=partition_key,
            source_files=tuple(
                _fingerprint_file(path, include_hash=False)
                for path in _source_paths_for_partition(lake_root, partition_key)
            ),
            target_path=str(
                gold_wealth_market_turnover_path(lake_root, partition_key).resolve()
            ),
            target_file=(
                _fingerprint_file(
                    gold_wealth_market_turnover_path(lake_root, partition_key),
                    include_hash=True,
                )
                if gold_wealth_market_turnover_path(
                    lake_root,
                    partition_key,
                ).exists()
                else None
            ),
        )
        for partition_key in selected_keys
    )
    staging_root = str(Path(DEFAULT_LAKE_STAGING_ROOT).resolve())
    plan_hash = _calculate_plan_hash(
        selected_partition_keys=selected_keys,
        partition_plans=partition_plans,
        staging_root=staging_root,
        batch_size=WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE,
        build_version=WEALTH_MARKET_TURNOVER_BUILD_VERSION,
        correction_method=WEALTH_MARKET_TURNOVER_CORRECTION_METHOD,
    )
    return WealthMarketTurnoverHistoryPlan(
        selected_partition_keys=selected_keys,
        partition_plans=partition_plans,
        plan_hash=plan_hash,
        staging_root=staging_root,
        batch_size=WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE,
        build_version=WEALTH_MARKET_TURNOVER_BUILD_VERSION,
        correction_method=WEALTH_MARKET_TURNOVER_CORRECTION_METHOD,
        eligible_source_partition_count=len(selected_keys),
        already_ready_partition_count=0,
        planned_write_count=0,
        planned_event_count=0,
        sample_partition_keys=_sample_partition_keys(selected_keys),
    )


def _fingerprint_file(
    path: Path,
    *,
    include_hash: bool,
) -> WealthMarketTurnoverFileFingerprint:
    stat = path.stat()
    return WealthMarketTurnoverFileFingerprint(
        path=str(path.resolve()),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=_sha256_file(path) if include_hash else None,
    )


def _assert_source_fingerprints_unchanged(
    partition_plan: WealthMarketTurnoverPartitionPlan,
) -> None:
    for expected in partition_plan.source_files:
        path = Path(expected.path)
        if not path.exists():
            raise RuntimeError(
                f"Source file disappeared for {partition_plan.partition_key}: {path}"
            )
        current = _fingerprint_file(path, include_hash=False)
        if current.size != expected.size or current.mtime_ns != expected.mtime_ns:
            raise RuntimeError(
                f"Source fingerprint changed for {partition_plan.partition_key}: {path}"
            )


def _assert_target_unchanged(
    partition_plan: WealthMarketTurnoverPartitionPlan,
    target_path: Path,
) -> None:
    expected = partition_plan.target_file
    if expected is None:
        if target_path.exists():
            raise RuntimeError(
                f"Formal target appeared after plan for {partition_plan.partition_key}."
            )
        return
    if not target_path.exists():
        raise RuntimeError(
            f"Formal target disappeared after plan for {partition_plan.partition_key}."
        )
    current = _fingerprint_file(target_path, include_hash=True)
    if (
        current.size != expected.size
        or current.mtime_ns != expected.mtime_ns
        or current.sha256 != expected.sha256
    ):
        raise RuntimeError(
            f"Formal target changed after plan for {partition_plan.partition_key}."
        )


def _candidate_path(plan: WealthMarketTurnoverHistoryPlan, partition_key: str) -> Path:
    return gold_wealth_market_turnover_staging_path(
        Path(plan.staging_root),
        operation_id=plan.plan_hash,
        partition_key=partition_key,
    )


def _partition_plan(
    plan: WealthMarketTurnoverHistoryPlan,
    partition_key: str,
) -> WealthMarketTurnoverPartitionPlan:
    for partition_plan in plan.partition_plans:
        if partition_plan.partition_key == partition_key:
            return partition_plan
    raise ValueError(f"Partition {partition_key} is not in plan {plan.plan_hash}.")


def _selected_plan_batch(
    plan: WealthMarketTurnoverHistoryPlan,
    partition_keys: Sequence[str],
) -> tuple[str, ...]:
    selected = tuple(sorted(set(partition_keys)))
    if not selected:
        raise ValueError("At least one wealth market turnover partition is required.")
    if (
        len(selected) > plan.batch_size
        or len(selected) > WEALTH_MARKET_TURNOVER_HISTORY_BATCH_SIZE_LIMIT
    ):
        raise ValueError("wealth market turnover history batch exceeds 20 partitions")
    unknown = tuple(key for key in selected if key not in plan.selected_partition_keys)
    if unknown:
        raise ValueError(f"Partitions are not in the frozen plan: {unknown}")
    return selected


def _select_partition_keys(
    complete_keys: Sequence[str],
    *,
    partition_keys: Sequence[str] | None,
    start_date: str,
    end_date: str | None,
) -> tuple[str, ...]:
    complete = tuple(complete_keys)
    if partition_keys is not None:
        requested = tuple(sorted(set(partition_keys)))
        missing = tuple(key for key in requested if key not in set(complete))
        if missing:
            raise ValueError(
                "Requested wealth market turnover partitions are missing complete "
                f"minute and stock daily inputs: {missing}"
            )
        return requested
    return _filter_partition_keys(complete, start_date=start_date, end_date=end_date)


def _filter_partition_keys(
    partition_keys: Sequence[str],
    *,
    start_date: str,
    end_date: str | None,
) -> tuple[str, ...]:
    return tuple(
        key
        for key in sorted(set(partition_keys))
        if key >= start_date and (end_date is None or key <= end_date)
    )


def _validate_batch_size(batch_size: int) -> None:
    if not 1 <= int(batch_size) <= WEALTH_MARKET_TURNOVER_HISTORY_BATCH_SIZE_LIMIT:
        raise ValueError("wealth market turnover history batch_size must be 1..20")


def _sample_partition_keys(partition_keys: Sequence[str]) -> tuple[str, ...]:
    if not partition_keys:
        return ()
    ordered = tuple(partition_keys)
    return tuple(dict.fromkeys((ordered[0], ordered[len(ordered) // 2], ordered[-1])))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_audit_payload(result: WealthMarketTurnoverWriteAudit) -> dict[str, object]:
    return {
        "file_path": str(result.file_path),
        "row_count": result.row_count,
        "observed_columns": list(result.observed_columns),
        "source_row_count": result.source_row_count,
        "total_amount": result.total_amount,
        "total_vol": result.total_vol,
        "security_count_by_freq": result.security_count_by_freq,
        "latest_trade_time_by_freq": result.latest_trade_time_by_freq,
        "bse_security_count": result.bse_security_count,
        "bse_residual_vol_by_freq": result.bse_residual_vol_by_freq,
        "bse_residual_amount_by_freq": result.bse_residual_amount_by_freq,
        "bse_rounding_residual_code_count_by_freq": (
            result.bse_rounding_residual_code_count_by_freq
        ),
    }


def _integrity_audit_payload(
    audit: WealthMarketTurnoverIntegrityAudit,
) -> dict[str, object]:
    return {
        "passed": audit.passed,
        "failure_stage": audit.failure_stage,
        "reason_code": audit.reason_code,
        "checked_row_count": audit.checked_row_count,
        "failed_row_count": audit.failed_row_count,
        "missing_file_paths": list(audit.missing_file_paths),
        "sample_rows": list(audit.sample_rows),
        "metadata": audit.metadata,
    }
