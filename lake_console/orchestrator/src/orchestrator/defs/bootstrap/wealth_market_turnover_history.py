from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_wealth_market_turnover_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    STK_MINS_SILVER_HISTORY_START_DATE,
)
from orchestrator.defs.wealth_market_turnover_contract import (
    WealthMarketTurnoverIntegrityAudit,
    WealthMarketTurnoverWriteAudit,
    audit_gold_wealth_market_turnover_file_contract,
    audit_gold_wealth_market_turnover_recomputed_from_silver,
    wealth_market_turnover_input_paths,
    write_gold_wealth_market_turnover_partition,
)


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverHistoryPlan:
    selected_partition_keys: tuple[str, ...]
    silver_partition_counts: Mapping[int, int]
    complete_silver_partition_count: int
    existing_target_file_count: int
    planned_write_count: int
    planned_event_count: int
    missing_input_count: int
    missing_input_samples: tuple[str, ...]
    sample_partition_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["silver_partition_counts"] = {
            str(freq): count for freq, count in self.silver_partition_counts.items()
        }
        return payload


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverHistoryWriteReport:
    selected_partition_keys: tuple[str, ...]
    written_partition_keys: tuple[str, ...]
    skipped_existing_partition_keys: tuple[str, ...]
    write_results: tuple[WealthMarketTurnoverWriteAudit, ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "selected_partition_keys": list(self.selected_partition_keys),
            "written_partition_keys": list(self.written_partition_keys),
            "skipped_existing_partition_keys": list(
                self.skipped_existing_partition_keys
            ),
            "write_results": [
                {
                    "file_path": str(result.file_path),
                    "row_count": result.row_count,
                    "observed_columns": list(result.observed_columns),
                    "source_row_count": result.source_row_count,
                    "total_amount": result.total_amount,
                    "total_vol": result.total_vol,
                    "security_count_by_freq": result.security_count_by_freq,
                    "latest_trade_time_by_freq": result.latest_trade_time_by_freq,
                }
                for result in self.write_results
            ],
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverHistoryPartitionAudit:
    partition_key: str
    target_path: Path
    passed: bool
    file_contract: WealthMarketTurnoverIntegrityAudit
    recomputed_from_silver: WealthMarketTurnoverIntegrityAudit | None

    @property
    def reason_code(self) -> str | None:
        if self.file_contract.reason_code is not None:
            return self.file_contract.reason_code
        if self.recomputed_from_silver is not None:
            return self.recomputed_from_silver.reason_code
        return None

    @property
    def checked_row_count(self) -> int:
        if self.recomputed_from_silver is not None:
            return self.recomputed_from_silver.checked_row_count
        return self.file_contract.checked_row_count

    def to_dict(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "target_path": str(self.target_path),
            "passed": self.passed,
            "reason_code": self.reason_code,
            "file_contract": _integrity_audit_payload(self.file_contract),
            "recomputed_from_silver": (
                _integrity_audit_payload(self.recomputed_from_silver)
                if self.recomputed_from_silver is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverHistoryAuditReport:
    selected_partition_keys: tuple[str, ...]
    target_file_count: int
    target_row_count: int
    target_date_min: str | None
    target_date_max: str | None
    failed_partition_count: int
    reason_counts: Mapping[str, int]
    partition_audits: tuple[WealthMarketTurnoverHistoryPartitionAudit, ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "selected_partition_keys": list(self.selected_partition_keys),
            "selected_trade_date_count": len(self.selected_partition_keys),
            "target_file_count": self.target_file_count,
            "target_row_count": self.target_row_count,
            "target_date_min": self.target_date_min,
            "target_date_max": self.target_date_max,
            "failed_partition_count": self.failed_partition_count,
            "reason_counts": dict(self.reason_counts),
            "sample_partition_audits": [
                audit.to_dict() for audit in self.partition_audits[:20]
            ],
            "elapsed_ms": self.elapsed_ms,
        }


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


def discover_silver_stk_mins_partitions_for_turnover(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> dict[int, tuple[str, ...]]:
    partitions_by_freq: dict[int, tuple[str, ...]] = {}
    for freq in STK_MINS_FREQS:
        silver_root = (
            Path(lake_root)
            / "silver"
            / "quote"
            / "stk_mins"
            / f"freq={freq}"
        )
        partitions_by_freq[freq] = tuple(
            sorted(
                path.parent.name.removeprefix("trade_date=")
                for path in silver_root.glob("trade_date=*/part-000.parquet")
                if path.is_file()
            )
        )
    return partitions_by_freq


def complete_silver_stk_mins_partition_keys_for_turnover(
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    *,
    start_date: str = STK_MINS_SILVER_HISTORY_START_DATE,
    end_date: str | None = None,
) -> tuple[str, ...]:
    silver_by_freq = discover_silver_stk_mins_partitions_for_turnover(lake_root)
    if not silver_by_freq:
        return ()
    common = set(silver_by_freq[STK_MINS_FREQS[0]])
    for freq in STK_MINS_FREQS[1:]:
        common &= set(silver_by_freq[freq])
    return _filter_partition_keys(
        sorted(common),
        start_date=start_date,
        end_date=end_date,
    )


def plan_wealth_market_turnover_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_SILVER_HISTORY_START_DATE,
    end_date: str | None = None,
) -> WealthMarketTurnoverHistoryPlan:
    silver_by_freq = discover_silver_stk_mins_partitions_for_turnover(lake_root)
    complete_keys = complete_silver_stk_mins_partition_keys_for_turnover(
        lake_root,
        start_date=start_date,
        end_date=end_date,
    )
    selected_keys = _select_partition_keys(
        complete_keys,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
    )
    existing_targets = set(discover_wealth_market_turnover_target_partitions(lake_root))
    missing_inputs = _missing_silver_input_samples(lake_root, selected_keys)
    return WealthMarketTurnoverHistoryPlan(
        selected_partition_keys=selected_keys,
        silver_partition_counts={
            freq: len(partitions) for freq, partitions in silver_by_freq.items()
        },
        complete_silver_partition_count=len(complete_keys),
        existing_target_file_count=sum(
            1 for partition_key in selected_keys if partition_key in existing_targets
        ),
        planned_write_count=sum(
            1 for partition_key in selected_keys if partition_key not in existing_targets
        ),
        planned_event_count=len(selected_keys) * 2,
        missing_input_count=len(missing_inputs),
        missing_input_samples=tuple(missing_inputs[:20]),
        sample_partition_keys=_sample_partition_keys(selected_keys),
    )


def generate_wealth_market_turnover_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    partition_keys: Sequence[str],
    skip_existing: bool = True,
    overwrite: bool = False,
) -> WealthMarketTurnoverHistoryWriteReport:
    selected_keys = tuple(sorted(set(partition_keys)))
    if not selected_keys:
        raise ValueError("At least one wealth market turnover partition key is required.")
    missing_inputs = _missing_silver_input_samples(lake_root, selected_keys)
    if missing_inputs:
        raise FileNotFoundError(
            "wealth market turnover history inputs are missing: "
            f"{tuple(missing_inputs[:20])}"
        )

    started_at = perf_counter()
    written: list[str] = []
    skipped: list[str] = []
    write_results: list[WealthMarketTurnoverWriteAudit] = []
    with duckdb_resource.connect() as connection:
        for partition_key in selected_keys:
            target_path = gold_wealth_market_turnover_path(lake_root, partition_key)
            if target_path.exists() and skip_existing and not overwrite:
                skipped.append(partition_key)
                continue
            result = write_gold_wealth_market_turnover_partition(
                connection=connection,
                input_paths=wealth_market_turnover_input_paths(lake_root, partition_key),
                partition_key=partition_key,
                target_path=target_path,
            )
            written.append(partition_key)
            write_results.append(result)
    return WealthMarketTurnoverHistoryWriteReport(
        selected_partition_keys=selected_keys,
        written_partition_keys=tuple(written),
        skipped_existing_partition_keys=tuple(skipped),
        write_results=tuple(write_results),
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def audit_wealth_market_turnover_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource,
    partition_keys: Sequence[str] | None = None,
    start_date: str = STK_MINS_SILVER_HISTORY_START_DATE,
    end_date: str | None = None,
) -> WealthMarketTurnoverHistoryAuditReport:
    selected_keys = (
        tuple(sorted(set(partition_keys)))
        if partition_keys is not None
        else _filter_partition_keys(
            discover_wealth_market_turnover_target_partitions(lake_root),
            start_date=start_date,
            end_date=end_date,
        )
    )
    started_at = perf_counter()
    audits: list[WealthMarketTurnoverHistoryPartitionAudit] = []
    with duckdb_resource.connect() as connection:
        for partition_key in selected_keys:
            target_path = gold_wealth_market_turnover_path(lake_root, partition_key)
            file_audit = audit_gold_wealth_market_turnover_file_contract(
                connection=connection,
                target_path=target_path,
                partition_key=partition_key,
            )
            recompute_audit = None
            if file_audit.passed:
                recompute_audit = audit_gold_wealth_market_turnover_recomputed_from_silver(
                    connection=connection,
                    target_path=target_path,
                    input_paths=wealth_market_turnover_input_paths(
                        lake_root,
                        partition_key,
                    ),
                    partition_key=partition_key,
                )
            audits.append(
                WealthMarketTurnoverHistoryPartitionAudit(
                    partition_key=partition_key,
                    target_path=target_path,
                    passed=file_audit.passed
                    and recompute_audit is not None
                    and recompute_audit.passed,
                    file_contract=file_audit,
                    recomputed_from_silver=recompute_audit,
                )
            )

    reason_counts: dict[str, int] = {}
    target_row_count = 0
    passed_keys: list[str] = []
    for audit in audits:
        if audit.passed:
            target_row_count += audit.checked_row_count
            passed_keys.append(audit.partition_key)
            continue
        reason = audit.reason_code or "unknown_failure"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return WealthMarketTurnoverHistoryAuditReport(
        selected_partition_keys=selected_keys,
        target_file_count=sum(1 for audit in audits if audit.target_path.exists()),
        target_row_count=target_row_count,
        target_date_min=passed_keys[0] if passed_keys else None,
        target_date_max=passed_keys[-1] if passed_keys else None,
        failed_partition_count=sum(1 for audit in audits if not audit.passed),
        reason_counts=reason_counts,
        partition_audits=tuple(audits),
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


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
                f"silver inputs: {missing}"
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


def _missing_silver_input_samples(
    lake_root: Path,
    partition_keys: Sequence[str],
) -> list[str]:
    missing: list[str] = []
    for partition_key in partition_keys:
        for input_path in wealth_market_turnover_input_paths(lake_root, partition_key):
            if not input_path.path.exists():
                missing.append(f"{partition_key}:freq={input_path.freq}:{input_path.path}")
    return missing


def _sample_partition_keys(partition_keys: Sequence[str]) -> tuple[str, ...]:
    if not partition_keys:
        return ()
    ordered = tuple(partition_keys)
    return tuple(dict.fromkeys((ordered[0], ordered[len(ordered) // 2], ordered[-1])))


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
