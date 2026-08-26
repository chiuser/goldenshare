from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from orchestrator.defs.bootstrap.stk_mins_bse_history_recovery import (
    BseMinuteRecoveryMode,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
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
    GOLD_WEALTH_MARKET_TURNOVER_COLUMNS,
    WEALTH_MARKET_TURNOVER_BUILD_VERSION,
    WealthMarketTurnoverIntegrityAudit,
    WealthMarketTurnoverMinuteSourcePath,
    WealthMarketTurnoverSourcePaths,
    WealthMarketTurnoverWriteAudit,
    audit_gold_wealth_market_turnover_file_contract,
    audit_gold_wealth_market_turnover_recomputed_from_sources,
    summarize_gold_wealth_market_turnover_file,
    validate_wealth_market_turnover_source_paths,
    wealth_market_turnover_canonical_hash,
    wealth_market_turnover_canonical_rows,
    wealth_market_turnover_select_sql,
    wealth_market_turnover_source_paths,
)

WEALTH_MARKET_TURNOVER_WMT7_HISTORY_START_DATE = "2021-11-15"
WEALTH_MARKET_TURNOVER_HISTORY_BATCH_SIZE_LIMIT = 20
WEALTH_MARKET_TURNOVER_HISTORY_AUDIT_SECONDS_LIMIT = 300
WEALTH_MARKET_TURNOVER_CORRECTION_METHOD = "bse_close_auction_daily_residual"
# Existing runless maintenance remains a separate, unchanged recent-window tool.
WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE = 20
WEALTH_MARKET_TURNOVER_MIXED_RECOVERY_KIND = "wmt7r_mixed_history_recovery"


class WealthMarketTurnoverFrequencyAction(str, Enum):
    REBUILD_V2 = "rebuild_v2"
    PRESERVE_EXISTING = "preserve_existing"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverFrequencyPlan:
    freq: int
    action: str
    recovery_mode: str | None
    reason_code: str
    preserved_row_hash: str | None


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
    target_canonical_hash: str | None
    frequency_plans: tuple[WealthMarketTurnoverFrequencyPlan, ...]


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverHistoryPlan:
    selected_partition_keys: tuple[str, ...]
    partition_plans: tuple[WealthMarketTurnoverPartitionPlan, ...]
    plan_hash: str
    staging_root: str
    batch_size: int
    build_version: str
    correction_method: str
    built_at: str
    source_bundle_path: str
    source_bundle_hash: str
    changed_silver_manifest_path: str
    changed_silver_manifest_hash: str
    eligible_source_partition_count: int
    already_ready_partition_count: int
    all_preserve_partition_count: int
    blocked_partition_count: int
    planned_write_count: int
    planned_event_count: int
    should_stop: bool
    stop_reason_codes: tuple[str, ...]
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
            target_canonical_hash=(
                str(partition_payload["target_canonical_hash"])
                if partition_payload.get("target_canonical_hash") is not None
                else None
            ),
            frequency_plans=tuple(
                WealthMarketTurnoverFrequencyPlan(
                    freq=int(frequency_payload["freq"]),
                    action=str(frequency_payload["action"]),
                    recovery_mode=(
                        str(frequency_payload["recovery_mode"])
                        if frequency_payload.get("recovery_mode") is not None
                        else None
                    ),
                    reason_code=str(frequency_payload["reason_code"]),
                    preserved_row_hash=(
                        str(frequency_payload["preserved_row_hash"])
                        if frequency_payload.get("preserved_row_hash") is not None
                        else None
                    ),
                )
                for frequency_payload in partition_payload["frequency_plans"]
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
        built_at=str(payload["built_at"]),
        source_bundle_path=str(payload["source_bundle_path"]),
        source_bundle_hash=str(payload["source_bundle_hash"]),
        changed_silver_manifest_path=str(payload["changed_silver_manifest_path"]),
        changed_silver_manifest_hash=str(payload["changed_silver_manifest_hash"]),
        eligible_source_partition_count=int(
            payload["eligible_source_partition_count"]
        ),
        already_ready_partition_count=int(payload["already_ready_partition_count"]),
        all_preserve_partition_count=int(payload["all_preserve_partition_count"]),
        blocked_partition_count=int(payload["blocked_partition_count"]),
        planned_write_count=int(payload["planned_write_count"]),
        planned_event_count=int(payload["planned_event_count"]),
        should_stop=bool(payload["should_stop"]),
        stop_reason_codes=tuple(payload["stop_reason_codes"]),
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
    preserved_rows_match: bool
    frequency_actions: Mapping[str, str]
    old_canonical_hash: str | None
    new_canonical_hash: str | None
    changed: bool
    file_hash: str | None
    hash_matches: bool

    @property
    def reason_code(self) -> str | None:
        if not self.hash_matches:
            return "candidate_hash_mismatch"
        if self.file_contract.reason_code is not None:
            return self.file_contract.reason_code
        if self.recomputed_from_sources is not None:
            return self.recomputed_from_sources.reason_code
        if not self.preserved_rows_match:
            return "preserved_frequency_changed"
        return None

    @property
    def checked_row_count(self) -> int:
        return self.file_contract.checked_row_count

    def to_dict(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "target_path": str(self.target_path),
            "passed": self.passed,
            "reason_code": self.reason_code,
            "file_hash": self.file_hash,
            "hash_matches": self.hash_matches,
            "preserved_rows_match": self.preserved_rows_match,
            "frequency_actions": dict(self.frequency_actions),
            "old_canonical_hash": self.old_canonical_hash,
            "new_canonical_hash": self.new_canonical_hash,
            "changed": self.changed,
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

    @property
    def changed_partition_keys(self) -> tuple[str, ...]:
        return tuple(
            audit.partition_key
            for audit in self.partition_audits
            if audit.passed and audit.changed
        )

    @property
    def no_op_partition_keys(self) -> tuple[str, ...]:
        return tuple(
            audit.partition_key
            for audit in self.partition_audits
            if audit.passed and not audit.changed
        )

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
            "changed_partition_keys": list(self.changed_partition_keys),
            "no_op_partition_keys": list(self.no_op_partition_keys),
            "partition_audits": [audit.to_dict() for audit in self.partition_audits],
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverPromoteReport:
    plan_hash: str
    promoted_partition_keys: tuple[str, ...]
    already_promoted_partition_keys: tuple[str, ...]
    no_op_partition_keys: tuple[str, ...]
    changed_manifest_path: str
    changed_manifest_hash: str
    complete: bool
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


def _load_recovery_inputs(
    *,
    source_bundle_path: Path,
    changed_silver_manifest_path: Path,
) -> tuple[dict[str, object], dict[str, object], dict[tuple[str, int], dict[str, object]]]:
    bundle = _load_json_file(source_bundle_path, label="BSE source bundle")
    frozen_bundle = bundle.get("frozen_bundle")
    if (
        bundle.get("stage") != "r0b_source_bundle"
        or bundle.get("should_stop") is not False
        or not isinstance(frozen_bundle, dict)
        or bundle.get("bundle_hash") != _hash_payload(frozen_bundle)
    ):
        raise RuntimeError("BSE source bundle is not a complete frozen contract")

    mode_by_key: dict[tuple[str, int], dict[str, object]] = {}
    allowed_modes = {mode.value for mode in BseMinuteRecoveryMode}
    for raw_row in frozen_bundle.get("mode_rows") or ():
        row = dict(raw_row)
        key = (str(row.get("trade_date") or ""), int(row.get("freq") or 0))
        mode = str(row.get("mode") or "")
        if (
            not key[0]
            or key[1] not in STK_MINS_FREQS
            or mode not in allowed_modes
            or key in mode_by_key
        ):
            raise RuntimeError("BSE source bundle contains invalid recovery mode rows")
        mode_by_key[key] = row

    changed_manifest = _load_json_file(
        changed_silver_manifest_path,
        label="actual changed Silver manifest",
    )
    frozen_changed_manifest = {
        key: changed_manifest[key]
        for key in (
            "schema_version",
            "recovery_kind",
            "stage",
            "plan_hash",
            "bundle_hash",
            "raw_promote_hash",
            "audit_hash",
            "changed_silver_count",
            "changed_silver_rows",
        )
    }
    if (
        changed_manifest.get("stage") != "r2_actual_changed_silver_manifest"
        or changed_manifest.get("should_stop") is not False
        or changed_manifest.get("plan_hash") != bundle.get("plan_hash")
        or changed_manifest.get("bundle_hash") != bundle.get("bundle_hash")
        or changed_manifest.get("manifest_hash")
        != _hash_payload(frozen_changed_manifest)
    ):
        raise RuntimeError("actual changed Silver manifest identity is invalid")

    changed_keys: set[tuple[str, int]] = set()
    for raw_row in changed_manifest.get("changed_silver_rows") or ():
        key = (str(raw_row.get("trade_date") or ""), int(raw_row.get("freq") or 0))
        if key in changed_keys or key not in mode_by_key:
            raise RuntimeError("actual changed Silver scope escaped the source bundle")
        changed_keys.add(key)
    changed_count = changed_manifest.get("changed_silver_count")
    if changed_count is None or len(changed_keys) != int(changed_count):
        raise RuntimeError("actual changed Silver count does not match its rows")
    required_changed_keys = {
        key
        for key, row in mode_by_key.items()
        if row["mode"]
        in {
            BseMinuteRecoveryMode.SOURCE_RECOVERABLE.value,
            BseMinuteRecoveryMode.SILVER_FALLBACK_RECOVERABLE.value,
        }
    }
    if not required_changed_keys.issubset(changed_keys):
        raise RuntimeError("recoverable source scope is absent from changed Silver")
    return bundle, changed_manifest, mode_by_key


def _frequency_plan(
    *,
    freq: int,
    mode_row: Mapping[str, object] | None,
    target_row: Mapping[str, object] | None,
) -> WealthMarketTurnoverFrequencyPlan:
    recovery_mode = str(mode_row["mode"]) if mode_row is not None else None
    if recovery_mode == BseMinuteRecoveryMode.PARTIAL_BLOCKED.value:
        action = WealthMarketTurnoverFrequencyAction.BLOCK
        reason_code = str(mode_row.get("reason_code") or "partial_source_scope")
    elif recovery_mode in {
        BseMinuteRecoveryMode.SOURCE_EMPTY_SKIP.value,
        BseMinuteRecoveryMode.SOURCE_UNUSABLE_SKIP.value,
    }:
        action = WealthMarketTurnoverFrequencyAction.PRESERVE_EXISTING
        reason_code = str(mode_row.get("reason_code") or "source_empty")
    else:
        action = WealthMarketTurnoverFrequencyAction.REBUILD_V2
        reason_code = (
            str(mode_row.get("reason_code") or "recovered_source")
            if mode_row is not None
            else "complete_existing_source"
        )
    preserved_row_hash = (
        _hash_payload(dict(target_row))
        if action is WealthMarketTurnoverFrequencyAction.PRESERVE_EXISTING
        and target_row is not None
        else None
    )
    return WealthMarketTurnoverFrequencyPlan(
        freq=freq,
        action=action.value,
        recovery_mode=recovery_mode,
        reason_code=reason_code,
        preserved_row_hash=preserved_row_hash,
    )


def _frequency_plan_with_source_gate(
    *,
    freq: int,
    mode_row: Mapping[str, object] | None,
    target_row: Mapping[str, object] | None,
    source_issue: str | None,
) -> WealthMarketTurnoverFrequencyPlan:
    planned = _frequency_plan(
        freq=freq,
        mode_row=mode_row,
        target_row=target_row,
    )
    if (
        source_issue is None
        or planned.action != WealthMarketTurnoverFrequencyAction.REBUILD_V2.value
    ):
        return planned
    return WealthMarketTurnoverFrequencyPlan(
        freq=freq,
        action=WealthMarketTurnoverFrequencyAction.BLOCK.value,
        recovery_mode=planned.recovery_mode,
        reason_code=source_issue,
        preserved_row_hash=None,
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


def _discover_partial_bse_source_frequency_keys(
    *,
    connection,
    lake_root: Path,
    partition_keys: Sequence[str],
) -> dict[tuple[str, int], str]:
    """Find partial BSE minute inputs before any WMT candidate is built."""

    if not partition_keys:
        return {}
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE wmt_history_requested_dates "
        "(trade_date DATE PRIMARY KEY)"
    )
    connection.executemany(
        "INSERT INTO wmt_history_requested_dates VALUES (?)",
        [(partition_key,) for partition_key in partition_keys],
    )
    minute_glob = (
        Path(lake_root)
        / "silver"
        / "quote"
        / "stk_mins"
        / "freq=*"
        / "trade_date=*"
        / "part-000.parquet"
    )
    daily_glob = (
        Path(lake_root)
        / "silver"
        / "quote"
        / "stock_daily"
        / "trade_date=*"
        / "part-000.parquet"
    )
    rows = connection.execute(
        f"""
        WITH requested_freqs(freq) AS (
          VALUES {", ".join(f"({freq})" for freq in STK_MINS_FREQS)}
        ),
        daily_bse AS (
          SELECT DISTINCT
            CAST(daily.trade_date AS DATE) AS trade_date,
            upper(trim(CAST(daily.ts_code AS VARCHAR))) AS ts_code
          FROM {read_parquet(daily_glob, hive_partitioning=True)} daily
          JOIN wmt_history_requested_dates requested
            ON requested.trade_date = CAST(daily.trade_date AS DATE)
          WHERE ends_with(upper(trim(CAST(daily.ts_code AS VARCHAR))), '.BJ')
        ),
        minute_bse AS (
          SELECT
            CAST(minute.trade_date AS DATE) AS trade_date,
            CAST(minute.freq AS INTEGER) AS freq,
            upper(trim(CAST(minute.ts_code AS VARCHAR))) AS ts_code,
            count(*) FILTER (
              WHERE CAST(minute.trade_time AS TIME) = TIME '15:00:00'
            ) AS close_row_count
          FROM {read_parquet(minute_glob, hive_partitioning=True)} minute
          JOIN wmt_history_requested_dates requested
            ON requested.trade_date = CAST(minute.trade_date AS DATE)
          JOIN requested_freqs
            ON requested_freqs.freq = CAST(minute.freq AS INTEGER)
          WHERE ends_with(upper(trim(CAST(minute.ts_code AS VARCHAR))), '.BJ')
          GROUP BY 1, 2, 3
        ),
        expected AS (
          SELECT daily.trade_date, requested_freqs.freq, daily.ts_code
          FROM daily_bse daily
          CROSS JOIN requested_freqs
        ),
        code_set_issues AS (
          SELECT
            coalesce(expected.trade_date, minute.trade_date) AS trade_date,
            coalesce(expected.freq, minute.freq) AS freq,
            count(*) AS issue_count
          FROM expected
          FULL OUTER JOIN minute_bse minute
            USING (trade_date, freq, ts_code)
          WHERE expected.ts_code IS NULL OR minute.ts_code IS NULL
          GROUP BY 1, 2
        ),
        close_issues AS (
          SELECT expected.trade_date, expected.freq, count(*) AS issue_count
          FROM expected
          JOIN minute_bse minute USING (trade_date, freq, ts_code)
          WHERE minute.close_row_count != 1
          GROUP BY 1, 2
        )
        SELECT
          coalesce(code_set.trade_date, close_points.trade_date)::VARCHAR,
          coalesce(code_set.freq, close_points.freq),
          CASE
            WHEN code_set.issue_count IS NOT NULL THEN 'bse_code_set_mismatch'
            ELSE 'bse_close_point_missing'
          END AS reason_code
        FROM code_set_issues code_set
        FULL OUTER JOIN close_issues close_points USING (trade_date, freq)
        ORDER BY 1, 2
        """
    ).fetchall()
    return {
        (str(trade_date), int(freq)): str(reason_code)
        for trade_date, freq, reason_code in rows
    }


def plan_wealth_market_turnover_history(
    *,
    duckdb_resource: DuckDBResource,
    recovery_source_bundle_path: Path,
    changed_silver_manifest_path: Path,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
    partition_keys: Sequence[str] | None = None,
    start_date: str = WEALTH_MARKET_TURNOVER_WMT7_HISTORY_START_DATE,
    end_date: str | None = None,
    batch_size: int = WEALTH_MARKET_TURNOVER_HISTORY_BATCH_SIZE_LIMIT,
) -> WealthMarketTurnoverHistoryPlan:
    _validate_batch_size(batch_size)
    bundle, changed_silver_manifest, mode_by_key = _load_recovery_inputs(
        source_bundle_path=recovery_source_bundle_path,
        changed_silver_manifest_path=changed_silver_manifest_path,
    )
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
    all_preserve_count = 0
    blocked_count = 0
    stop_reasons: set[str] = set()
    with duckdb_resource.connect() as connection:
        source_issue_by_key = _discover_partial_bse_source_frequency_keys(
            connection=connection,
            lake_root=lake_root,
            partition_keys=requested_keys,
        )
        for partition_key in requested_keys:
            source_paths = wealth_market_turnover_source_paths(lake_root, partition_key)
            if not _stock_daily_contains_bse(connection, source_paths.stock_daily_path):
                continue
            target_path = gold_wealth_market_turnover_path(lake_root, partition_key)
            target_rows = (
                wealth_market_turnover_canonical_rows(
                    connection=connection,
                    path=target_path,
                )
                if target_path.is_file()
                else {}
            )
            target_canonical_hash = (
                wealth_market_turnover_canonical_hash(
                    connection=connection,
                    path=target_path,
                )
                if target_path.is_file()
                else None
            )
            frequency_plans = tuple(
                _frequency_plan_with_source_gate(
                    freq=freq,
                    mode_row=mode_by_key.get((partition_key, freq)),
                    target_row=target_rows.get(freq),
                    source_issue=source_issue_by_key.get((partition_key, freq)),
                )
                for freq in STK_MINS_FREQS
            )
            if any(
                item.action == WealthMarketTurnoverFrequencyAction.BLOCK.value
                for item in frequency_plans
            ):
                blocked_count += 1
                stop_reasons.update(
                    item.reason_code
                    for item in frequency_plans
                    if item.action == WealthMarketTurnoverFrequencyAction.BLOCK.value
                )
                continue
            preserve_freqs = tuple(
                item.freq
                for item in frequency_plans
                if item.action
                == WealthMarketTurnoverFrequencyAction.PRESERVE_EXISTING.value
            )
            if preserve_freqs and (
                not target_path.is_file()
                or any(
                    item.preserved_row_hash is None
                    for item in frequency_plans
                    if item.action
                    == WealthMarketTurnoverFrequencyAction.PRESERVE_EXISTING.value
                )
            ):
                blocked_count += 1
                stop_reasons.add("missing_preserved_gold_partition")
                continue
            if len(preserve_freqs) == len(STK_MINS_FREQS):
                all_preserve_count += 1
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
                    target_canonical_hash=target_canonical_hash,
                    frequency_plans=frequency_plans,
                )
            )
    selected_keys = tuple(plan.partition_key for plan in selected_plans)
    resolved_staging_root = str(Path(staging_root).resolve())
    built_at = datetime.now(timezone.utc).isoformat()
    plan_hash = _calculate_plan_hash(
        selected_partition_keys=selected_keys,
        partition_plans=selected_plans,
        staging_root=resolved_staging_root,
        batch_size=batch_size,
        build_version=WEALTH_MARKET_TURNOVER_BUILD_VERSION,
        correction_method=WEALTH_MARKET_TURNOVER_CORRECTION_METHOD,
        built_at=built_at,
        source_bundle_path=str(recovery_source_bundle_path.resolve()),
        source_bundle_hash=str(bundle["bundle_hash"]),
        changed_silver_manifest_path=str(changed_silver_manifest_path.resolve()),
        changed_silver_manifest_hash=str(changed_silver_manifest["manifest_hash"]),
    )
    return WealthMarketTurnoverHistoryPlan(
        selected_partition_keys=selected_keys,
        partition_plans=tuple(selected_plans),
        plan_hash=plan_hash,
        staging_root=resolved_staging_root,
        batch_size=batch_size,
        build_version=WEALTH_MARKET_TURNOVER_BUILD_VERSION,
        correction_method=WEALTH_MARKET_TURNOVER_CORRECTION_METHOD,
        built_at=built_at,
        source_bundle_path=str(recovery_source_bundle_path.resolve()),
        source_bundle_hash=str(bundle["bundle_hash"]),
        changed_silver_manifest_path=str(changed_silver_manifest_path.resolve()),
        changed_silver_manifest_hash=str(changed_silver_manifest["manifest_hash"]),
        eligible_source_partition_count=len(requested_keys),
        already_ready_partition_count=0,
        all_preserve_partition_count=all_preserve_count,
        blocked_partition_count=blocked_count,
        planned_write_count=len(selected_keys),
        planned_event_count=0,
        should_stop=bool(blocked_count),
        stop_reason_codes=tuple(sorted(stop_reasons)),
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
    _assert_plan_ready(plan)
    _assert_recovery_inputs_unchanged(plan)
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
        result = _build_mixed_candidate(
            plan=plan,
            partition_plan=partition_plan,
            candidate_path=candidate_path,
            duckdb_resource=duckdb_resource,
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
    _assert_plan_ready(plan)
    _assert_recovery_inputs_unchanged(plan)
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
    candidate_audits: Mapping[str, Mapping[str, object]],
    checkpoint_path: Path,
    changed_manifest_path: Path,
) -> WealthMarketTurnoverPromoteReport:
    _assert_plan_hash(plan)
    _assert_plan_ready(plan)
    _assert_recovery_inputs_unchanged(plan)
    selected_keys = _selected_plan_batch(plan, partition_keys)
    _assert_maintenance_output_path(plan, checkpoint_path)
    _assert_maintenance_output_path(plan, changed_manifest_path)
    started_at = perf_counter()
    checkpoint = _load_promote_checkpoint(
        plan=plan,
        checkpoint_path=checkpoint_path,
    )
    promoted_rows = list(checkpoint.get("promoted") or ())
    no_op_rows = list(checkpoint.get("no_op") or ())
    completed = {
        str(row["partition_key"])
        for row in (*promoted_rows, *no_op_rows)
    }
    promoted: list[str] = []
    already_promoted: list[str] = []
    no_op: list[str] = []
    _reconcile_interrupted_promotion(
        plan=plan,
        checkpoint=checkpoint,
        checkpoint_path=checkpoint_path,
        candidate_hashes=candidate_hashes,
        candidate_audits=candidate_audits,
        promoted_rows=promoted_rows,
        no_op_rows=no_op_rows,
        completed=completed,
    )
    for partition_key in selected_keys:
        if partition_key in completed:
            already_promoted.append(partition_key)
            continue
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
        candidate_audit = candidate_audits.get(partition_key)
        if not candidate_audit or candidate_audit.get("passed") is not True:
            raise ValueError(
                f"Missing green candidate audit for partition {partition_key}."
            )
        if candidate_audit.get("file_hash") != expected_candidate_hash:
            raise RuntimeError(
                f"Candidate audit hash mismatch for partition {partition_key}."
            )
        if not candidate_path.exists():
            raise FileNotFoundError(
                f"Missing candidate file for partition {partition_key}: {candidate_path}"
            )
        if _sha256_file(candidate_path) != expected_candidate_hash:
            raise RuntimeError(f"Candidate hash changed for partition {partition_key}.")
        _assert_target_unchanged(partition_plan, target_path)
        if candidate_audit.get("changed") is not True:
            _write_promote_checkpoint(
                plan=plan,
                checkpoint_path=checkpoint_path,
                promoted_rows=promoted_rows,
                no_op_rows=no_op_rows,
                in_progress={
                    "partition_key": partition_key,
                    "candidate_hash": expected_candidate_hash,
                    "new_canonical_hash": candidate_audit.get("new_canonical_hash"),
                    "changed": False,
                },
            )
            candidate_path.unlink()
            no_op_rows.append(
                {
                    "partition_key": partition_key,
                    "target_path": str(target_path),
                    "canonical_hash": candidate_audit.get("new_canonical_hash"),
                }
            )
            no_op.append(partition_key)
            completed.add(partition_key)
            _write_promote_checkpoint(
                plan=plan,
                checkpoint_path=checkpoint_path,
                promoted_rows=promoted_rows,
                no_op_rows=no_op_rows,
                in_progress=None,
            )
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if os.stat(candidate_path.parent).st_dev != os.stat(target_path.parent).st_dev:
            raise RuntimeError("candidate and formal target are not on the same filesystem")
        _write_promote_checkpoint(
            plan=plan,
            checkpoint_path=checkpoint_path,
            promoted_rows=promoted_rows,
            no_op_rows=no_op_rows,
            in_progress={
                "partition_key": partition_key,
                "candidate_hash": expected_candidate_hash,
                "new_canonical_hash": candidate_audit.get("new_canonical_hash"),
                "changed": True,
            },
        )
        os.replace(candidate_path, target_path)
        if _sha256_file(target_path) != expected_candidate_hash:
            raise RuntimeError(
                f"Formal target hash mismatch after promote for {partition_key}."
            )
        promoted.append(partition_key)
        promoted_rows.append(
            {
                "partition_key": partition_key,
                "target_path": str(target_path),
                "file_hash": expected_candidate_hash,
                "old_canonical_hash": candidate_audit.get("old_canonical_hash"),
                "new_canonical_hash": candidate_audit.get("new_canonical_hash"),
                "frequency_actions": candidate_audit.get("frequency_actions"),
            }
        )
        completed.add(partition_key)
        _write_promote_checkpoint(
            plan=plan,
            checkpoint_path=checkpoint_path,
            promoted_rows=promoted_rows,
            no_op_rows=no_op_rows,
            in_progress=None,
        )
    changed_manifest = _write_changed_manifest(
        plan=plan,
        changed_manifest_path=changed_manifest_path,
        promoted_rows=promoted_rows,
        no_op_rows=no_op_rows,
    )
    return WealthMarketTurnoverPromoteReport(
        plan_hash=plan.plan_hash,
        promoted_partition_keys=tuple(promoted),
        already_promoted_partition_keys=tuple(already_promoted),
        no_op_partition_keys=tuple(no_op),
        changed_manifest_path=str(changed_manifest_path),
        changed_manifest_hash=str(changed_manifest["manifest_hash"]),
        complete=bool(changed_manifest["complete"]),
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
    _assert_plan_ready(plan)
    _assert_recovery_inputs_unchanged(plan)
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
    changed_manifest: Mapping[str, object],
) -> WealthMarketTurnoverProdPublishReport:
    _assert_plan_hash(plan)
    _assert_plan_ready(plan)
    _assert_recovery_inputs_unchanged(plan)
    changed_keys = _validate_changed_manifest(
        plan=plan,
        changed_manifest=changed_manifest,
        require_complete=True,
    )
    selected_keys = _selected_plan_batch(plan, partition_keys)
    unexpected = tuple(key for key in selected_keys if key not in changed_keys)
    if unexpected:
        raise ValueError(
            "Prod publish may only consume actual changed WMT partitions: "
            f"{unexpected}"
        )
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
        rows = _load_mixed_rows_for_prod_sync(
            duckdb_resource=duckdb_resource,
            source_path=source_path,
            partition_key=partition_key,
            preserve_freqs=_frequency_values_for_action(
                partition_plan,
                WealthMarketTurnoverFrequencyAction.PRESERVE_EXISTING,
            ),
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


def _build_mixed_candidate(
    *,
    plan: WealthMarketTurnoverHistoryPlan,
    partition_plan: WealthMarketTurnoverPartitionPlan,
    candidate_path: Path,
    duckdb_resource: DuckDBResource,
) -> WealthMarketTurnoverWriteAudit:
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.unlink(missing_ok=True)
    rebuild_freqs = _frequency_values_for_action(
        partition_plan,
        WealthMarketTurnoverFrequencyAction.REBUILD_V2,
    )
    preserve_freqs = _frequency_values_for_action(
        partition_plan,
        WealthMarketTurnoverFrequencyAction.PRESERVE_EXISTING,
    )
    source_paths = _source_bundle_for_freqs(partition_plan, rebuild_freqs)
    target_path = Path(partition_plan.target_path)
    try:
        with duckdb_resource.connect() as connection:
            correction_stats = validate_wealth_market_turnover_source_paths(
                connection=connection,
                source_paths=source_paths,
                partition_key=partition_plan.partition_key,
                expected_freqs=rebuild_freqs,
            )
            rebuild_sql = wealth_market_turnover_select_sql(
                source_paths=source_paths,
                partition_key=partition_plan.partition_key,
                built_at_sql=duckdb_string(plan.built_at),
            )
            source_queries = [f"SELECT * FROM ({rebuild_sql}) rebuilt_rows"]
            if preserve_freqs:
                preserve_values = ", ".join(str(freq) for freq in preserve_freqs)
                source_queries.append(
                    f"""
                    SELECT
                      type,
                      market,
                      trade_date,
                      freq,
                      build_status,
                      latest_trade_time,
                      total_amount,
                      total_vol,
                      security_count,
                      source_row_count,
                      points_json,
                      build_version,
                      built_at,
                      build_note
                    FROM {read_parquet(target_path, hive_partitioning=False)}
                    WHERE freq IN ({preserve_values})
                    """
                )
            mixed_sql = (
                "SELECT * FROM ("
                + " UNION ALL ".join(f"({query})" for query in source_queries)
                + ") mixed_rows ORDER BY freq"
            )
            connection.execute(copy_query_to_parquet(mixed_sql, candidate_path))
            audit = _audit_mixed_target(
                connection=connection,
                partition_plan=partition_plan,
                target_path=candidate_path,
                expected_hash=None,
                source_files_validated=True,
            )
            if not audit.passed:
                raise RuntimeError(
                    "wealth market turnover mixed candidate audit failed: "
                    f"partition={partition_plan.partition_key}, "
                    f"reason_code={audit.reason_code}."
                )
            return summarize_gold_wealth_market_turnover_file(
                connection=connection,
                target_path=candidate_path,
                correction_stats=correction_stats,
            )
    except Exception:
        candidate_path.unlink(missing_ok=True)
        raise


def _audit_mixed_target(
    *,
    connection,
    partition_plan: WealthMarketTurnoverPartitionPlan,
    target_path: Path,
    expected_hash: str | None,
    source_files_validated: bool = False,
) -> WealthMarketTurnoverHistoryPartitionAudit:
    preserve_freqs = _frequency_values_for_action(
        partition_plan,
        WealthMarketTurnoverFrequencyAction.PRESERVE_EXISTING,
    )
    rebuild_freqs = _frequency_values_for_action(
        partition_plan,
        WealthMarketTurnoverFrequencyAction.REBUILD_V2,
    )
    file_audit = audit_gold_wealth_market_turnover_file_contract(
        connection=connection,
        target_path=target_path,
        partition_key=partition_plan.partition_key,
        preserve_freqs=preserve_freqs,
    )
    recompute_audit = None
    if file_audit.passed:
        recompute_audit = audit_gold_wealth_market_turnover_recomputed_from_sources(
            connection=connection,
            target_path=target_path,
            source_paths=_source_bundle_for_freqs(partition_plan, rebuild_freqs),
            partition_key=partition_plan.partition_key,
            source_files_validated=source_files_validated,
            expected_freqs=rebuild_freqs,
        )
    target_rows = (
        wealth_market_turnover_canonical_rows(
            connection=connection,
            path=target_path,
        )
        if target_path.is_file()
        else {}
    )
    preserved_rows_match = all(
        item.preserved_row_hash is not None
        and item.freq in target_rows
        and _hash_payload(target_rows[item.freq]) == item.preserved_row_hash
        for item in partition_plan.frequency_plans
        if item.action
        == WealthMarketTurnoverFrequencyAction.PRESERVE_EXISTING.value
    )
    file_hash = _sha256_file(target_path) if target_path.is_file() else None
    new_canonical_hash = (
        wealth_market_turnover_canonical_hash(
            connection=connection,
            path=target_path,
        )
        if target_path.is_file()
        else None
    )
    hash_matches = expected_hash is None or file_hash == expected_hash
    return WealthMarketTurnoverHistoryPartitionAudit(
        partition_key=partition_plan.partition_key,
        target_path=target_path,
        passed=(
            file_audit.passed
            and recompute_audit is not None
            and recompute_audit.passed
            and preserved_rows_match
            and hash_matches
        ),
        file_contract=file_audit,
        recomputed_from_sources=recompute_audit,
        preserved_rows_match=preserved_rows_match,
        frequency_actions={
            str(item.freq): item.action for item in partition_plan.frequency_plans
        },
        old_canonical_hash=partition_plan.target_canonical_hash,
        new_canonical_hash=new_canonical_hash,
        changed=(partition_plan.target_canonical_hash != new_canonical_hash),
        file_hash=file_hash,
        hash_matches=hash_matches,
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
            audits.append(
                _audit_mixed_target(
                    connection=connection,
                    partition_plan=partition_plan,
                    target_path=target_path,
                    expected_hash=(expected_hashes or {}).get(partition_key),
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


def _source_bundle_for_freqs(
    partition_plan: WealthMarketTurnoverPartitionPlan,
    freqs: Sequence[int],
) -> WealthMarketTurnoverSourcePaths:
    requested = tuple(int(freq) for freq in freqs)
    if not requested:
        raise ValueError("At least one WMT rebuild frequency is required.")
    full_source = _source_bundle_from_partition_plan(partition_plan)
    by_freq = {item.freq: item for item in full_source.minute_paths}
    if any(freq not in by_freq for freq in requested):
        raise RuntimeError("WMT rebuild frequency is absent from the frozen source plan.")
    return WealthMarketTurnoverSourcePaths(
        minute_paths=tuple(by_freq[freq] for freq in requested),
        stock_daily_path=full_source.stock_daily_path,
    )


def _frequency_values_for_action(
    partition_plan: WealthMarketTurnoverPartitionPlan,
    action: WealthMarketTurnoverFrequencyAction,
) -> tuple[int, ...]:
    return tuple(
        item.freq
        for item in partition_plan.frequency_plans
        if item.action == action.value
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
    built_at: str,
    source_bundle_path: str,
    source_bundle_hash: str,
    changed_silver_manifest_path: str,
    changed_silver_manifest_hash: str,
) -> str:
    payload = {
        "selected_partition_keys": list(selected_partition_keys),
        "partition_plans": [asdict(plan) for plan in partition_plans],
        "staging_root": staging_root,
        "batch_size": batch_size,
        "build_version": build_version,
        "correction_method": correction_method,
        "built_at": built_at,
        "source_bundle_path": source_bundle_path,
        "source_bundle_hash": source_bundle_hash,
        "changed_silver_manifest_path": changed_silver_manifest_path,
        "changed_silver_manifest_hash": changed_silver_manifest_hash,
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
        built_at=plan.built_at,
        source_bundle_path=plan.source_bundle_path,
        source_bundle_hash=plan.source_bundle_hash,
        changed_silver_manifest_path=plan.changed_silver_manifest_path,
        changed_silver_manifest_hash=plan.changed_silver_manifest_hash,
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
            target_canonical_hash=None,
            frequency_plans=tuple(
                WealthMarketTurnoverFrequencyPlan(
                    freq=freq,
                    action=WealthMarketTurnoverFrequencyAction.REBUILD_V2.value,
                    recovery_mode=None,
                    reason_code="direct_audit",
                    preserved_row_hash=None,
                )
                for freq in STK_MINS_FREQS
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
        built_at="2000-01-01T00:00:00+00:00",
        source_bundle_path="",
        source_bundle_hash="",
        changed_silver_manifest_path="",
        changed_silver_manifest_hash="",
    )
    return WealthMarketTurnoverHistoryPlan(
        selected_partition_keys=selected_keys,
        partition_plans=partition_plans,
        plan_hash=plan_hash,
        staging_root=staging_root,
        batch_size=WEALTH_MARKET_TURNOVER_RUNLESS_WINDOW_SIZE,
        build_version=WEALTH_MARKET_TURNOVER_BUILD_VERSION,
        correction_method=WEALTH_MARKET_TURNOVER_CORRECTION_METHOD,
        built_at="2000-01-01T00:00:00+00:00",
        source_bundle_path="",
        source_bundle_hash="",
        changed_silver_manifest_path="",
        changed_silver_manifest_hash="",
        eligible_source_partition_count=len(selected_keys),
        already_ready_partition_count=0,
        all_preserve_partition_count=0,
        blocked_partition_count=0,
        planned_write_count=0,
        planned_event_count=0,
        should_stop=False,
        stop_reason_codes=(),
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


def _load_json_file(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{label} is unreadable: {path}") from error
    if not isinstance(payload, dict):
        raise TypeError(f"{label} must be a JSON object: {path}")
    return payload


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _assert_plan_ready(plan: WealthMarketTurnoverHistoryPlan) -> None:
    if plan.should_stop or plan.blocked_partition_count:
        raise RuntimeError(
            "wealth market turnover history plan is blocked: "
            f"reason_codes={list(plan.stop_reason_codes)}"
        )
    if plan.planned_event_count != 0:
        raise RuntimeError("R5 history maintenance must not plan Dagster events")


def _assert_recovery_inputs_unchanged(
    plan: WealthMarketTurnoverHistoryPlan,
) -> None:
    if not plan.source_bundle_path and not plan.changed_silver_manifest_path:
        return
    bundle, changed_manifest, _ = _load_recovery_inputs(
        source_bundle_path=Path(plan.source_bundle_path),
        changed_silver_manifest_path=Path(plan.changed_silver_manifest_path),
    )
    if (
        bundle.get("bundle_hash") != plan.source_bundle_hash
        or changed_manifest.get("manifest_hash")
        != plan.changed_silver_manifest_hash
    ):
        raise RuntimeError("R5 recovery input identity changed after plan")


def _assert_maintenance_output_path(
    plan: WealthMarketTurnoverHistoryPlan,
    path: Path,
) -> None:
    resolved = path.resolve()
    staging_root = Path(plan.staging_root).resolve()
    if not resolved.is_relative_to(staging_root):
        raise RuntimeError("R5 checkpoint and manifest must stay under staging root")
    formal_root = Path(DEFAULT_LAKE_ROOT).resolve()
    if resolved.is_relative_to(formal_root):
        raise RuntimeError("R5 maintenance metadata must not be written into formal lake")


def _load_promote_checkpoint(
    *,
    plan: WealthMarketTurnoverHistoryPlan,
    checkpoint_path: Path,
) -> dict[str, object]:
    if not checkpoint_path.exists():
        return {
            "schema_version": 1,
            "recovery_kind": WEALTH_MARKET_TURNOVER_MIXED_RECOVERY_KIND,
            "stage": "r5_wmt_promote_checkpoint",
            "plan_hash": plan.plan_hash,
            "promoted": [],
            "no_op": [],
            "in_progress": None,
        }
    payload = _load_json_file(checkpoint_path, label="R5 promote checkpoint")
    if (
        payload.get("schema_version") != 1
        or payload.get("recovery_kind")
        != WEALTH_MARKET_TURNOVER_MIXED_RECOVERY_KIND
        or payload.get("stage") != "r5_wmt_promote_checkpoint"
        or payload.get("plan_hash") != plan.plan_hash
    ):
        raise RuntimeError("R5 promote checkpoint identity mismatch")
    return payload


def _write_promote_checkpoint(
    *,
    plan: WealthMarketTurnoverHistoryPlan,
    checkpoint_path: Path,
    promoted_rows: Sequence[Mapping[str, object]],
    no_op_rows: Sequence[Mapping[str, object]],
    in_progress: Mapping[str, object] | None,
) -> None:
    payload = {
        "schema_version": 1,
        "recovery_kind": WEALTH_MARKET_TURNOVER_MIXED_RECOVERY_KIND,
        "stage": "r5_wmt_promote_checkpoint",
        "plan_hash": plan.plan_hash,
        "promoted": sorted(
            (dict(row) for row in promoted_rows),
            key=lambda row: str(row["partition_key"]),
        ),
        "no_op": sorted(
            (dict(row) for row in no_op_rows),
            key=lambda row: str(row["partition_key"]),
        ),
        "in_progress": dict(in_progress) if in_progress is not None else None,
    }
    _atomic_write_json(checkpoint_path, payload)


def _reconcile_interrupted_promotion(
    *,
    plan: WealthMarketTurnoverHistoryPlan,
    checkpoint: Mapping[str, object],
    checkpoint_path: Path,
    candidate_hashes: Mapping[str, str],
    candidate_audits: Mapping[str, Mapping[str, object]],
    promoted_rows: list[Mapping[str, object]],
    no_op_rows: list[Mapping[str, object]],
    completed: set[str],
) -> None:
    raw_in_progress = checkpoint.get("in_progress")
    if not isinstance(raw_in_progress, dict):
        return
    partition_key = str(raw_in_progress.get("partition_key") or "")
    if not partition_key or partition_key in completed:
        raise RuntimeError("R5 promote checkpoint has invalid in-progress state")
    candidate_audit = candidate_audits.get(partition_key)
    expected_hash = candidate_hashes.get(partition_key)
    if (
        not candidate_audit
        or candidate_audit.get("passed") is not True
        or not expected_hash
        or raw_in_progress.get("candidate_hash") != expected_hash
    ):
        raise RuntimeError("R5 interrupted promote cannot be reconciled safely")
    candidate_path = _candidate_path(plan, partition_key)
    target_path = Path(_partition_plan(plan, partition_key).target_path)
    changed = raw_in_progress.get("changed") is True
    if candidate_path.exists():
        if _sha256_file(candidate_path) != expected_hash:
            raise RuntimeError("R5 candidate changed during interrupted promote")
    elif changed and target_path.is_file() and _sha256_file(target_path) == expected_hash:
        promoted_rows.append(
            {
                "partition_key": partition_key,
                "target_path": str(target_path),
                "file_hash": expected_hash,
                "old_canonical_hash": candidate_audit.get("old_canonical_hash"),
                "new_canonical_hash": candidate_audit.get("new_canonical_hash"),
                "frequency_actions": candidate_audit.get("frequency_actions"),
            }
        )
        completed.add(partition_key)
    elif not changed and not candidate_path.exists():
        with DuckDBResource().connect() as connection:
            current_hash = wealth_market_turnover_canonical_hash(
                connection=connection,
                path=target_path,
            )
        if current_hash != candidate_audit.get("new_canonical_hash"):
            raise RuntimeError("R5 no-op target changed during interrupted promote")
        no_op_rows.append(
            {
                "partition_key": partition_key,
                "target_path": str(target_path),
                "canonical_hash": current_hash,
            }
        )
        completed.add(partition_key)
    else:
        raise RuntimeError("R5 interrupted promote state is ambiguous")
    _write_promote_checkpoint(
        plan=plan,
        checkpoint_path=checkpoint_path,
        promoted_rows=promoted_rows,
        no_op_rows=no_op_rows,
        in_progress=None,
    )


def _write_changed_manifest(
    *,
    plan: WealthMarketTurnoverHistoryPlan,
    changed_manifest_path: Path,
    promoted_rows: Sequence[Mapping[str, object]],
    no_op_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    changed_rows = sorted(
        (dict(row) for row in promoted_rows),
        key=lambda row: str(row["partition_key"]),
    )
    unchanged_rows = sorted(
        (dict(row) for row in no_op_rows),
        key=lambda row: str(row["partition_key"]),
    )
    completed_keys = {
        str(row["partition_key"])
        for row in (*changed_rows, *unchanged_rows)
    }
    frozen = {
        "schema_version": 1,
        "recovery_kind": WEALTH_MARKET_TURNOVER_MIXED_RECOVERY_KIND,
        "stage": "r5_actual_changed_wmt_manifest",
        "plan_hash": plan.plan_hash,
        "source_bundle_hash": plan.source_bundle_hash,
        "changed_silver_manifest_hash": plan.changed_silver_manifest_hash,
        "planned_partition_count": len(plan.selected_partition_keys),
        "changed_partition_count": len(changed_rows),
        "no_op_partition_count": len(unchanged_rows),
        "changed_rows": changed_rows,
        "no_op_rows": unchanged_rows,
        "complete": completed_keys == set(plan.selected_partition_keys),
    }
    payload = {**frozen, "manifest_hash": _hash_payload(frozen)}
    _atomic_write_json(changed_manifest_path, payload)
    return payload


def _validate_changed_manifest(
    *,
    plan: WealthMarketTurnoverHistoryPlan,
    changed_manifest: Mapping[str, object],
    require_complete: bool,
) -> set[str]:
    frozen = {
        key: changed_manifest.get(key)
        for key in (
            "schema_version",
            "recovery_kind",
            "stage",
            "plan_hash",
            "source_bundle_hash",
            "changed_silver_manifest_hash",
            "planned_partition_count",
            "changed_partition_count",
            "no_op_partition_count",
            "changed_rows",
            "no_op_rows",
            "complete",
        )
    }
    if (
        changed_manifest.get("schema_version") != 1
        or changed_manifest.get("recovery_kind")
        != WEALTH_MARKET_TURNOVER_MIXED_RECOVERY_KIND
        or changed_manifest.get("stage") != "r5_actual_changed_wmt_manifest"
        or changed_manifest.get("plan_hash") != plan.plan_hash
        or changed_manifest.get("source_bundle_hash") != plan.source_bundle_hash
        or changed_manifest.get("changed_silver_manifest_hash")
        != plan.changed_silver_manifest_hash
        or changed_manifest.get("manifest_hash") != _hash_payload(frozen)
        or (require_complete and changed_manifest.get("complete") is not True)
    ):
        raise RuntimeError("R5 actual changed WMT manifest is not consumable")
    changed_rows = changed_manifest.get("changed_rows")
    no_op_rows = changed_manifest.get("no_op_rows")
    if not isinstance(changed_rows, list) or not isinstance(no_op_rows, list):
        raise TypeError("R5 actual changed WMT manifest rows are invalid")
    changed_keys = {str(row["partition_key"]) for row in changed_rows}
    no_op_keys = {str(row["partition_key"]) for row in no_op_rows}
    if (
        len(changed_keys) != len(changed_rows)
        or len(no_op_keys) != len(no_op_rows)
        or changed_keys & no_op_keys
        or changed_keys | no_op_keys != set(plan.selected_partition_keys)
        or len(changed_keys)
        != int(changed_manifest.get("changed_partition_count") or 0)
        or len(no_op_keys) != int(changed_manifest.get("no_op_partition_count") or 0)
    ):
        raise RuntimeError("R5 actual changed WMT manifest scope mismatch")
    return changed_keys


def _load_mixed_rows_for_prod_sync(
    *,
    duckdb_resource: DuckDBResource,
    source_path: Path,
    partition_key: str,
    preserve_freqs: Sequence[int],
) -> tuple[dict[str, object], ...]:
    with duckdb_resource.connect() as connection:
        file_audit = audit_gold_wealth_market_turnover_file_contract(
            connection=connection,
            target_path=source_path,
            partition_key=partition_key,
            preserve_freqs=preserve_freqs,
        )
        if not file_audit.passed:
            raise RuntimeError(
                "mixed Gold WMT file contract failed before Prod publish: "
                f"partition={partition_key}, reason_code={file_audit.reason_code}."
            )
        rows = connection.execute(
            f"""
            SELECT {', '.join(GOLD_WEALTH_MARKET_TURNOVER_COLUMNS)}
            FROM {read_parquet(source_path, hive_partitioning=False)}
            ORDER BY freq
            """
        ).fetchall()
    return tuple(
        dict(zip(GOLD_WEALTH_MARKET_TURNOVER_COLUMNS, row, strict=True))
        for row in rows
    )


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
