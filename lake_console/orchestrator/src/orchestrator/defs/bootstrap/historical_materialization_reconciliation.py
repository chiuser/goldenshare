"""Offline recovery of historical Dagster materialization state.

This module never writes Lake files or runs Dagster jobs.  Its only permitted
write is a runless ``AssetMaterialization`` for a physically verified, already
registered Lake partition that has neither a materialization nor a check event.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import subprocess
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import dagster as dg

from orchestrator.defs.catalog.lake_assets import (
    PartitionModelFamily,
    get_partition_model_definition,
    list_lake_asset_catalog_entries,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata


SCHEMA_VERSION = 1
HOT_WINDOW_SIZE = 20
FOOTER_BATCH_SIZE = 250
WRITE_CHUNK_SIZE = 500
RECONCILIATION_METHOD = "historical_lake_partition_materialization_v1"
CONTRACT_ONLY_CATALOG_ASSET_KEYS = frozenset(
    {
        "raw_tushare_dc_index",
        "raw_tushare_dc_member",
        "raw_tushare_dc_daily",
        "silver_dc_index",
        "silver_dc_member",
        "silver_dc_daily",
        "gold_dc_daily_technical",
    }
)

FAMILY_ASSET_KEYS: dict[str, tuple[str, ...]] = {
    "A": (
        "gold_market_major_indices_daily",
        "gold_market_breadth_daily",
        "gold_stock_return_distribution",
        "gold_wealth_market_turnover",
    ),
    "B": ("raw_index_daily",),
    "C": tuple(f"raw_stk_mins_{freq}m" for freq in (1, 5, 15, 30, 60)),
    "D": tuple(f"silver_stk_mins_{freq}m" for freq in (1, 5, 15, 30, 60)),
    "E": tuple(
        f"gold_stk_mins_qfq_macd_kdj_state_{freq}m"
        for freq in (1, 5, 15, 30, 60, 90, 120)
    ),
}
EXPECTED_ASSET_KEYS = frozenset(
    asset_key for asset_keys in FAMILY_ASSET_KEYS.values() for asset_key in asset_keys
)

SIMPLE_PATTERNS: dict[str, str] = {
    "raw_tushare_suspend_d": "raw/tushare/suspend_d/trade_date=*/part-000.parquet",
    "silver_stock_suspend_daily": "silver/quote/stock_suspend_daily/trade_date=*/part-000.parquet",
    "raw_tushare_stock_daily": "raw/tushare/stock_daily/trade_date=*/part-000.parquet",
    "raw_tushare_stk_nineturn": "raw/tushare/stk_nineturn/trade_date=*/part-000.parquet",
    "silver_stock_nineturn_daily": "silver/quote/stock_nineturn_daily/trade_date=*/part-000.parquet",
    "silver_stock_daily": "silver/quote/stock_daily/trade_date=*/part-000.parquet",
    "raw_tushare_adj_factor": "raw/tushare/adj_factor/trade_date=*/part-000.parquet",
    "silver_adj_factor": "silver/quote/adj_factor/trade_date=*/part-000.parquet",
    "gold_stock_daily_qfq": "gold/quote/stock_daily_qfq/trade_date=*/part-000.parquet",
    "raw_index_daily": "raw/index_daily/trade_date=*/part-000.parquet",
    "silver_index_daily": "silver/index_daily/trade_date=*/part-000.parquet",
    "gold_market_major_indices_daily": "gold/market/major_indices_daily/trade_date=*/part-000.parquet",
    "gold_market_breadth_daily": "gold/breadth/market_breadth_daily/trade_date=*/part-000.parquet",
    "gold_stock_return_distribution": "gold/breadth/stock_return_distribution/trade_date=*/part-000.parquet",
    "gold_wealth_market_turnover": "gold/wealth/market_turnover/trade_date=*/part-000.parquet",
}
for _freq in (1, 5, 15, 30, 60):
    SIMPLE_PATTERNS[f"raw_stk_mins_{_freq}m"] = (
        f"raw/tushare/stk_mins/freq={_freq}/trade_date=*/part-000.parquet"
    )
    SIMPLE_PATTERNS[f"silver_stk_mins_{_freq}m"] = (
        f"silver/quote/stk_mins/freq={_freq}/trade_date=*/part-000.parquet"
    )
for _freq in (1, 5, 15, 30, 60, 90, 120):
    SIMPLE_PATTERNS[f"gold_stk_mins_qfq_macd_kdj_state_{_freq}m"] = (
        "gold/indicator/stk_mins_qfq_macd_kdj_state/"
        f"freq={_freq}/trade_date=*/part-000.parquet"
    )

STOCK_YEAR_PATTERNS: dict[str, str] = {}
for _freq in (1, 5, 15, 30, 60, 90, 120):
    STOCK_YEAR_PATTERNS[f"gold_stk_mins_qfq_{_freq}m"] = (
        f"gold/quote/stk_mins_qfq/freq={_freq}/ts_code=*/year=*/part-000.parquet"
    )
    STOCK_YEAR_PATTERNS[f"gold_stk_mins_qfq_macd_kdj_{_freq}m"] = (
        "gold/indicator/stk_mins_qfq_macd_kdj/"
        f"freq={_freq}/ts_code=*/year=*/part-000.parquet"
    )

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ACTIVE_RUN_STATUSES = ("QUEUED", "STARTING", "STARTED", "CANCELING")


class HistoricalMaterializationReconciliationError(RuntimeError):
    """Raised when a materialization recovery plan cannot continue safely."""


@dataclass(frozen=True, slots=True)
class PhysicalPartition:
    partition_key: str
    required_paths: tuple[Path, ...]
    canonical_uri: str
    file_count: int
    files: tuple[dict[str, object], ...]

    def fingerprint_payload(self, lake_root: Path) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "required_paths": [str(path.relative_to(lake_root)) for path in self.required_paths],
            "canonical_uri": self.canonical_uri,
            "file_count": self.file_count,
            "files": list(self.files),
        }


@dataclass(frozen=True, slots=True)
class ReconciliationCandidate:
    asset_key: str
    partition_key: str
    physical_fingerprint: str
    canonical_uri: str
    file_count: int
    required_paths: tuple[str, ...]
    files: tuple[dict[str, object], ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ReconciliationCandidate":
        if payload.get("classification") != "safe_candidate":
            raise HistoricalMaterializationReconciliationError(
                "Only safe_candidate manifest entries can be applied."
            )
        asset_key = str(payload["asset_key"])
        partition_key = str(payload["partition_key"])
        if asset_key not in EXPECTED_ASSET_KEYS:
            raise HistoricalMaterializationReconciliationError(
                f"Candidate asset is outside approved A-E scope: {asset_key}."
            )
        if not ISO_DATE_RE.fullmatch(partition_key):
            raise HistoricalMaterializationReconciliationError(
                f"Candidate partition key is not ISO date: {partition_key}."
            )
        return cls(
            asset_key=asset_key,
            partition_key=partition_key,
            physical_fingerprint=str(payload["physical_fingerprint"]),
            canonical_uri=str(payload["canonical_uri"]),
            file_count=int(payload["file_count"]),
            required_paths=tuple(str(value) for value in payload["required_paths"]),
            files=tuple(dict(value) for value in payload["files"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_key": self.asset_key,
            "partition_key": self.partition_key,
            "physical_fingerprint": self.physical_fingerprint,
            "canonical_uri": self.canonical_uri,
            "file_count": self.file_count,
            "required_paths": list(self.required_paths),
            "files": list(self.files),
        }


@dataclass(frozen=True, slots=True)
class ReconciliationPlan:
    report_path: Path
    manifest_path: Path
    plan_fingerprint: str
    candidates: tuple[ReconciliationCandidate, ...]
    report: Mapping[str, object]

    def candidates_for_families(self, families: Sequence[str]) -> tuple[ReconciliationCandidate, ...]:
        normalized = _normalize_families(families)
        allowed = {
            asset_key
            for family in normalized
            for asset_key in FAMILY_ASSET_KEYS[family]
        }
        by_asset = {candidate.asset_key for candidate in self.candidates}
        unexpected = by_asset - EXPECTED_ASSET_KEYS
        if unexpected:
            raise HistoricalMaterializationReconciliationError(
                f"Plan contains assets outside approved A-E scope: {sorted(unexpected)}."
            )
        ordered: list[ReconciliationCandidate] = []
        for family in normalized:
            for asset_key in FAMILY_ASSET_KEYS[family]:
                ordered.extend(
                    sorted(
                        (
                            candidate
                            for candidate in self.candidates
                            if candidate.asset_key == asset_key and candidate.asset_key in allowed
                        ),
                        key=lambda candidate: candidate.partition_key,
                    )
                )
        return tuple(ordered)


@dataclass(frozen=True, slots=True)
class ReconciliationApplyReport:
    plan_fingerprint: str
    batch_id: str
    requested_families: tuple[str, ...]
    dry_run: bool
    planned_event_count: int
    reported_event_count: int
    skipped_existing_materialization_count: int
    family_reports: tuple[dict[str, object], ...]
    control_counts_before: Mapping[str, int]
    control_counts_after: Mapping[str, int]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_fingerprint": self.plan_fingerprint,
            "batch_id": self.batch_id,
            "requested_families": list(self.requested_families),
            "dry_run": self.dry_run,
            "planned_event_count": self.planned_event_count,
            "reported_event_count": self.reported_event_count,
            "skipped_existing_materialization_count": self.skipped_existing_materialization_count,
            "family_reports": list(self.family_reports),
            "control_counts_before": dict(self.control_counts_before),
            "control_counts_after": dict(self.control_counts_after),
            "elapsed_ms": self.elapsed_ms,
        }


def build_historical_materialization_reconciliation_plan(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    output_dir: Path,
) -> ReconciliationPlan:
    """Create a zero-write inventory and immutable candidate manifest."""

    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    lake_root = lake_root.resolve()
    resolved = _resolved_defs()
    active_specs = {
        spec.key.to_user_string(): spec for spec in resolved.resolve_all_asset_specs()
    }
    catalog = {entry.asset_key: entry for entry in list_lake_asset_catalog_entries()}
    active_catalog_keys = set(active_specs).intersection(catalog)
    active_partitioned = {
        key
        for key in active_catalog_keys
        if get_partition_model_definition(catalog[key].partition_model).family
        == PartitionModelFamily.TRADE_DATE_PARTITION
    }
    permanent_excluded = CONTRACT_ONLY_CATALOG_ASSET_KEYS.intersection(active_partitioned)
    supported_keys = set(SIMPLE_PATTERNS).intersection(active_partitioned)
    stock_year_keys = set(STOCK_YEAR_PATTERNS).intersection(active_partitioned)
    unclassified_active = (
        active_partitioned - supported_keys - stock_year_keys - permanent_excluded
    )

    registered_by_asset: dict[str, set[str]] = {}
    materialized_by_asset: dict[str, set[str]] = {}
    for asset_key in sorted(supported_keys | stock_year_keys):
        partitions_def = active_specs[asset_key].partitions_def
        registered_by_asset[asset_key] = (
            set(partitions_def.get_partition_keys(dynamic_partitions_store=instance))
            if partitions_def is not None
            else set()
        )
        materialized_by_asset[asset_key] = set(
            instance.get_materialized_partitions(dg.AssetKey(asset_key))
        )

    check_partitions = _check_partitions_by_asset(supported_keys | stock_year_keys)
    reports: list[dict[str, object]] = []
    manifest_entries: list[dict[str, object]] = []
    for asset_key in sorted(supported_keys):
        report, entries = _asset_report(
            asset_key=asset_key,
            pattern=SIMPLE_PATTERNS[asset_key],
            lake_root=lake_root,
            registered_partition_keys=registered_by_asset[asset_key],
            materialized_partition_keys=materialized_by_asset[asset_key],
            check_partition_keys=check_partitions.get(asset_key, set()),
            catalog_entry=catalog[asset_key],
        )
        reports.append(report)
        manifest_entries.extend(entries)
    for asset_key in sorted(stock_year_keys):
        reports.append(
            _unsupported_stock_year_report(
                asset_key=asset_key,
                pattern=STOCK_YEAR_PATTERNS[asset_key],
                lake_root=lake_root,
                catalog_entry=catalog[asset_key],
            )
        )
    for asset_key in sorted(permanent_excluded):
        definition = get_partition_model_definition(catalog[asset_key].partition_model)
        reports.append(
            {
                "asset_key": asset_key,
                "asset_family": definition.asset_family,
                "physical_layout": definition.physical_layout.value,
                "status": "permanently_excluded_contract_only",
                "classification_counts": {"unsupported_or_ambiguous": 0},
            }
        )

    candidates = tuple(
        ReconciliationCandidate.from_dict(entry)
        for entry in sorted(
            manifest_entries,
            key=lambda entry: (str(entry["asset_key"]), str(entry["partition_key"])),
        )
    )
    plan_fingerprint = _hash_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "safe_candidates": [candidate.to_dict() for candidate in candidates],
            "active_partitioned": sorted(active_partitioned),
        }
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = output_dir / (
        f"dagster_historical_materialization_reconciliation_candidates_{timestamp}.jsonl"
    )
    with manifest_path.open("w", encoding="utf-8") as handle:
        for candidate in candidates:
            payload = {"classification": "safe_candidate", **candidate.to_dict()}
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    classification_totals: Counter[str] = Counter()
    for report in reports:
        classification_totals.update(report.get("classification_counts", {}))
    structural_stop_reasons = []
    if unclassified_active:
        structural_stop_reasons.append(
            "active_partitioned_assets_without_explicit_spec:"
            + ",".join(sorted(unclassified_active))
        )
    catalog_missing_active = sorted(set(active_specs) - set(catalog))
    if catalog_missing_active:
        structural_stop_reasons.append(
            "active_assets_missing_catalog:" + ",".join(catalog_missing_active)
        )
    metadata_sizes = [_metadata_size(candidate, plan_fingerprint) for candidate in candidates]
    report_payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "phase": "P0_read_only_inventory",
        "evaluated_at": datetime.now().astimezone().isoformat(),
        "read_only": True,
        "dagster_home": os.environ.get("DAGSTER_HOME"),
        "lake_root": str(lake_root),
        "active_asset_spec_count": len(active_specs),
        "catalog_entry_count": len(catalog),
        "active_catalog_asset_count": len(active_catalog_keys),
        "active_partitioned_asset_count": len(active_partitioned),
        "supported_partition_file_asset_count": len(supported_keys),
        "unsupported_stock_year_asset_count": len(stock_year_keys),
        "contract_only_excluded_asset_keys": sorted(permanent_excluded),
        "unclassified_active_partitioned_asset_keys": sorted(unclassified_active),
        "active_assets_missing_catalog": catalog_missing_active,
        "run_status_counts": _run_status_counts(),
        "classification_totals": dict(sorted(classification_totals.items())),
        "planned_materialization_event_count": len(candidates),
        "planned_check_event_count": 0,
        "metadata_payload_bytes": {
            "p50": int(statistics.median(metadata_sizes)) if metadata_sizes else 0,
            "p95": _percentile(metadata_sizes, 95),
            "max": max(metadata_sizes, default=0),
            "total": sum(metadata_sizes),
            "note": "Metadata payload only; excludes Dagster event envelope and indexes.",
        },
        "plan_fingerprint": plan_fingerprint,
        "candidate_manifest_path": str(manifest_path),
        "candidate_manifest_sha256": _sha256_path(manifest_path),
        "asset_reports": reports,
        "should_stop": bool(structural_stop_reasons),
        "structural_stop_reasons": structural_stop_reasons,
        "performance": {
            "footer_batch_size": FOOTER_BATCH_SIZE,
            "business_row_scans": 0,
            "hot_window_size": HOT_WINDOW_SIZE,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }
    report_path = output_dir / (
        f"dagster_historical_materialization_reconciliation_plan_{timestamp}.json"
    )
    _write_json(report_path, report_payload)
    return ReconciliationPlan(
        report_path=report_path,
        manifest_path=manifest_path,
        plan_fingerprint=plan_fingerprint,
        candidates=candidates,
        report=report_payload,
    )


def load_historical_materialization_reconciliation_plan(
    plan_report_path: Path,
) -> ReconciliationPlan:
    payload = json.loads(plan_report_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise HistoricalMaterializationReconciliationError("Unsupported plan schema version.")
    if payload.get("phase") != "P0_read_only_inventory" or payload.get("read_only") is not True:
        raise HistoricalMaterializationReconciliationError("Apply requires a read-only P0 plan report.")
    if payload.get("should_stop"):
        raise HistoricalMaterializationReconciliationError(
            f"Plan has stop reasons: {payload.get('structural_stop_reasons', [])}."
        )
    manifest_path = Path(str(payload["candidate_manifest_path"]))
    if not manifest_path.is_file():
        raise HistoricalMaterializationReconciliationError(
            f"Candidate manifest is missing: {manifest_path}."
        )
    expected_sha256 = str(payload["candidate_manifest_sha256"])
    if _sha256_path(manifest_path) != expected_sha256:
        raise HistoricalMaterializationReconciliationError("Candidate manifest SHA-256 mismatch.")
    candidates = tuple(
        ReconciliationCandidate.from_dict(json.loads(line))
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    expected_fingerprint = str(payload["plan_fingerprint"])
    observed_fingerprint = _hash_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "safe_candidates": [candidate.to_dict() for candidate in candidates],
            "active_partitioned": _active_partitioned_asset_keys(),
        }
    )
    if observed_fingerprint != expected_fingerprint:
        raise HistoricalMaterializationReconciliationError(
            "Plan fingerprint does not match current active partitioned asset definitions."
        )
    return ReconciliationPlan(
        report_path=plan_report_path,
        manifest_path=manifest_path,
        plan_fingerprint=expected_fingerprint,
        candidates=candidates,
        report=payload,
    )


def apply_historical_materialization_reconciliation(
    *,
    instance: dg.DagsterInstance,
    plan: ReconciliationPlan,
    lake_root: Path,
    families: Sequence[str],
    dry_run: bool,
    output_dir: Path,
) -> ReconciliationApplyReport:
    """Report only verified historical materializations in the approved A-E order."""

    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_families = _normalize_families(families)
    selected = plan.candidates_for_families(normalized_families)
    control_counts_before = _control_counts()
    partitioned_specs = _partitioned_specs_by_asset()
    batch_id = str(uuid.uuid4())
    reported_count = 0
    skipped_count = 0
    family_reports: list[dict[str, object]] = []

    for family in normalized_families:
        family_started = time.perf_counter()
        family_candidates = tuple(
            candidate
            for candidate in selected
            if candidate.asset_key in FAMILY_ASSET_KEYS[family]
        )
        family_report, reported, skipped = _apply_family(
            instance=instance,
            lake_root=lake_root,
            candidates=family_candidates,
            family=family,
            plan_fingerprint=plan.plan_fingerprint,
            batch_id=batch_id,
            dry_run=dry_run,
            output_dir=output_dir,
            partitioned_specs=partitioned_specs,
        )
        family_reports.append(
            {
                **family_report,
                "elapsed_ms": round((time.perf_counter() - family_started) * 1000, 2),
            }
        )
        reported_count += reported
        skipped_count += skipped

    control_counts_after = _control_counts()
    if not dry_run:
        _assert_control_counts_unchanged(
            before=control_counts_before,
            after=control_counts_after,
        )
    return ReconciliationApplyReport(
        plan_fingerprint=plan.plan_fingerprint,
        batch_id=batch_id,
        requested_families=normalized_families,
        dry_run=dry_run,
        planned_event_count=len(selected),
        reported_event_count=reported_count,
        skipped_existing_materialization_count=skipped_count,
        family_reports=tuple(family_reports),
        control_counts_before=control_counts_before,
        control_counts_after=control_counts_after,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def audit_historical_materialization_reconciliation(
    *,
    instance: dg.DagsterInstance,
    plan: ReconciliationPlan,
    families: Sequence[str],
) -> dict[str, object]:
    normalized_families = _normalize_families(families)
    selected = plan.candidates_for_families(normalized_families)
    missing_by_asset: dict[str, list[str]] = {}
    for asset_key in sorted({candidate.asset_key for candidate in selected}):
        expected = {
            candidate.partition_key for candidate in selected if candidate.asset_key == asset_key
        }
        actual = set(instance.get_materialized_partitions(dg.AssetKey(asset_key)))
        missing = sorted(expected - actual)
        if missing:
            missing_by_asset[asset_key] = missing[:20]
    return {
        "plan_fingerprint": plan.plan_fingerprint,
        "requested_families": list(normalized_families),
        "candidate_count": len(selected),
        "missing_materialization_sample_by_asset": missing_by_asset,
        "all_selected_candidates_materialized": not missing_by_asset,
        "control_counts": _control_counts(),
    }


def write_reconciliation_report(output_dir: Path, stage: str, payload: Mapping[str, object]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / (
        f"dagster_historical_materialization_reconciliation_{stage}_{timestamp}.json"
    )
    _write_json(output_path, dict(payload))
    return output_path


def _apply_family(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    candidates: Sequence[ReconciliationCandidate],
    family: str,
    plan_fingerprint: str,
    batch_id: str,
    dry_run: bool,
    output_dir: Path,
    partitioned_specs: Mapping[str, dg.AssetSpec],
) -> tuple[dict[str, object], int, int]:
    reported_count = 0
    skipped_count = 0
    chunk_reports: list[dict[str, object]] = []
    for chunk_index, chunk in enumerate(_chunks(tuple(candidates), WRITE_CHUNK_SIZE), start=1):
        _assert_no_active_runs()
        current_materialized = {
            asset_key: set(instance.get_materialized_partitions(dg.AssetKey(asset_key)))
            for asset_key in {candidate.asset_key for candidate in chunk}
        }
        existing_checks = _check_partitions_by_asset(
            {candidate.asset_key for candidate in chunk}
        )
        registered = _registered_partitions_by_asset(
            instance,
            {candidate.asset_key for candidate in chunk},
            partitioned_specs=partitioned_specs,
        )
        hot_keys = _hot_partition_keys_by_asset(lake_root, {candidate.asset_key for candidate in chunk})
        chunk_reported = 0
        chunk_skipped = 0
        for candidate in chunk:
            if candidate.partition_key in current_materialized[candidate.asset_key]:
                chunk_skipped += 1
                continue
            _assert_candidate_current(
                candidate=candidate,
                lake_root=lake_root,
                registered_partition_keys=registered[candidate.asset_key],
                check_partition_keys=existing_checks.get(candidate.asset_key, set()),
                hot_partition_keys=hot_keys[candidate.asset_key],
            )
            if not dry_run:
                instance.report_runless_asset_event(
                    dg.AssetMaterialization(
                        asset_key=dg.AssetKey(candidate.asset_key),
                        partition=candidate.partition_key,
                        metadata=build_materialization_metadata(
                            uri=candidate.canonical_uri,
                            extra_metadata={
                                "reconciliation_method": RECONCILIATION_METHOD,
                                "reconciliation_batch_id": batch_id,
                                "reconciliation_file_count": candidate.file_count,
                                "reconciliation_plan_fingerprint": plan_fingerprint,
                                "check_events_reported": False,
                            },
                        ),
                    )
                )
            current_materialized[candidate.asset_key].add(candidate.partition_key)
            chunk_reported += 1
        reported_count += chunk_reported
        skipped_count += chunk_skipped
        chunk_payload = {
            "family": family,
            "chunk_index": chunk_index,
            "candidate_count": len(chunk),
            "reported_count": chunk_reported,
            "skipped_existing_materialization_count": chunk_skipped,
            "first_candidate": chunk[0].to_dict() if chunk else None,
            "last_candidate": chunk[-1].to_dict() if chunk else None,
        }
        chunk_reports.append(chunk_payload)
        write_reconciliation_report(
            output_dir,
            f"progress_family_{family}_chunk_{chunk_index:03d}",
            chunk_payload,
        )
    return (
        {
            "family": family,
            "candidate_count": len(candidates),
            "reported_count": reported_count,
            "skipped_existing_materialization_count": skipped_count,
            "chunk_count": len(chunk_reports),
            "chunks": chunk_reports,
        },
        reported_count,
        skipped_count,
    )


def _assert_candidate_current(
    *,
    candidate: ReconciliationCandidate,
    lake_root: Path,
    registered_partition_keys: set[str],
    check_partition_keys: set[str],
    hot_partition_keys: set[str],
) -> None:
    if candidate.partition_key not in registered_partition_keys:
        raise HistoricalMaterializationReconciliationError(
            f"Candidate partition is no longer registered: {candidate.asset_key}[{candidate.partition_key}]."
        )
    if candidate.partition_key in check_partition_keys:
        raise HistoricalMaterializationReconciliationError(
            f"Candidate now has check state without a materialization: {candidate.asset_key}[{candidate.partition_key}]."
        )
    if candidate.partition_key in hot_partition_keys:
        raise HistoricalMaterializationReconciliationError(
            f"Candidate entered the current hot window: {candidate.asset_key}[{candidate.partition_key}]."
        )
    files = []
    for file_payload in candidate.files:
        relative_path = str(file_payload["relative_path"])
        path = lake_root / relative_path
        if not path.is_file() or path.stat().st_size == 0:
            raise HistoricalMaterializationReconciliationError(
                f"Candidate physical file is missing or empty: {path}."
            )
        stat = path.stat()
        if stat.st_size != int(file_payload["size_bytes"]) or stat.st_mtime_ns != int(file_payload["mtime_ns"]):
            raise HistoricalMaterializationReconciliationError(
                f"Candidate physical fingerprint changed: {path}."
            )
        files.append(path)
    invalid = _validate_parquet_footers(files)
    if invalid:
        raise HistoricalMaterializationReconciliationError(
            f"Candidate Parquet footer validation failed: {invalid}."
        )
    observed = _physical_candidate_fingerprint(
        partition_key=candidate.partition_key,
        canonical_uri=candidate.canonical_uri,
        files=files,
        lake_root=lake_root,
    )
    if observed != candidate.physical_fingerprint:
        raise HistoricalMaterializationReconciliationError(
            f"Candidate physical fingerprint no longer matches plan: {candidate.asset_key}[{candidate.partition_key}]."
        )


def _asset_report(
    *,
    asset_key: str,
    pattern: str,
    lake_root: Path,
    registered_partition_keys: set[str],
    materialized_partition_keys: set[str],
    check_partition_keys: set[str],
    catalog_entry: Any,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    started = time.perf_counter()
    partitions, invalid_samples = _discover_physical_partitions(lake_root, pattern)
    hot_partition_keys = set(sorted(partitions)[-HOT_WINDOW_SIZE:])
    classification_counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, object]]] = {}
    safe_entries: list[dict[str, object]] = []
    all_fingerprints: list[dict[str, object]] = []
    for partition_key, partition in sorted(partitions.items()):
        fingerprint_payload = partition.fingerprint_payload(lake_root)
        fingerprint = _hash_payload(fingerprint_payload)
        all_fingerprints.append(
            {"partition_key": partition_key, "physical_fingerprint": fingerprint}
        )
        if partition_key not in registered_partition_keys:
            classification = "unregistered_physical_partition"
        elif partition_key in hot_partition_keys:
            classification = "hot_window_excluded"
        elif partition_key in materialized_partition_keys:
            classification = "already_materialized"
        elif partition_key in check_partition_keys:
            classification = "check_without_materialization"
        else:
            classification = "safe_candidate"
            safe_entries.append(
                {
                    "asset_key": asset_key,
                    "classification": classification,
                    "physical_fingerprint": fingerprint,
                    **fingerprint_payload,
                }
            )
        classification_counts[classification] += 1
        samples.setdefault(classification, []).append(
            {"partition_key": partition_key, "canonical_uri": partition.canonical_uri}
        )
    if invalid_samples:
        classification_counts["missing_or_invalid_physical_file"] += len(invalid_samples)
        samples["missing_or_invalid_physical_file"] = invalid_samples
    definition = get_partition_model_definition(catalog_entry.partition_model)
    return (
        {
            "asset_key": asset_key,
            "asset_family": definition.asset_family,
            "physical_layout": definition.physical_layout.value,
            "pattern": pattern,
            "status": "supported_partition_file",
            "discovered_path_count": len(partitions) + len(invalid_samples),
            "valid_physical_partition_count": len(partitions),
            "valid_partition_start": min(partitions) if partitions else None,
            "valid_partition_end": max(partitions) if partitions else None,
            "registered_partition_count": len(registered_partition_keys),
            "existing_materialized_partition_count": len(materialized_partition_keys),
            "existing_check_partition_count": len(check_partition_keys),
            "hot_window_size": HOT_WINDOW_SIZE,
            "classification_counts": dict(sorted(classification_counts.items())),
            "samples": {name: values[:20] for name, values in sorted(samples.items())},
            "physical_partition_fingerprint": _hash_payload(all_fingerprints),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        },
        safe_entries,
    )


def _unsupported_stock_year_report(
    *, asset_key: str, pattern: str, lake_root: Path, catalog_entry: Any
) -> dict[str, object]:
    definition = get_partition_model_definition(catalog_entry.partition_model)
    return {
        "asset_key": asset_key,
        "asset_family": definition.asset_family,
        "physical_layout": definition.physical_layout.value,
        "pattern": pattern,
        "status": "unsupported_or_ambiguous",
        "reason": (
            "A stock-year Parquet can contain many trade-date partitions; this tool "
            "does not scan business rows to infer date-level materialization facts."
        ),
        "discovered_stock_year_file_count": sum(1 for _ in lake_root.glob(pattern)),
        "classification_counts": {"unsupported_or_ambiguous": 0},
    }


def _discover_physical_partitions(
    lake_root: Path, pattern: str
) -> tuple[dict[str, PhysicalPartition], list[dict[str, object]]]:
    paths = sorted(lake_root.glob(pattern))
    invalid_footer_paths = _validate_parquet_footers(paths)
    partitions: dict[str, PhysicalPartition] = {}
    invalid: list[dict[str, object]] = []
    duplicate_keys: set[str] = set()
    for path in paths:
        partition_key = _parse_partition_key(path)
        if partition_key is None:
            invalid.append({"path": str(path), "reason": "invalid_partition_directory"})
            continue
        if path in invalid_footer_paths:
            invalid.append({"path": str(path), "reason": invalid_footer_paths[path]})
            continue
        if partition_key in partitions:
            duplicate_keys.add(partition_key)
            continue
        stat = path.stat()
        relative_path = str(path.relative_to(lake_root))
        partitions[partition_key] = PhysicalPartition(
            partition_key=partition_key,
            required_paths=(path,),
            canonical_uri=str(path),
            file_count=1,
            files=(
                {
                    "relative_path": relative_path,
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                },
            ),
        )
    for partition_key in sorted(duplicate_keys):
        partitions.pop(partition_key, None)
        invalid.append({"partition_key": partition_key, "reason": "duplicate_physical_partition"})
    return partitions, invalid


def _validate_parquet_footers(paths: Sequence[Path]) -> dict[Path, str]:
    invalid: dict[Path, str] = {}
    readable_paths = []
    for path in paths:
        if not path.is_file():
            invalid[path] = "not_regular_file"
        elif path.stat().st_size == 0:
            invalid[path] = "empty_file"
        else:
            readable_paths.append(path)
    if not readable_paths:
        return invalid
    with connect_configured_duckdb() as connection:
        for batch in _chunks(tuple(readable_paths), FOOTER_BATCH_SIZE):
            values = [str(path) for path in batch]
            try:
                rows = connection.execute(
                    "SELECT DISTINCT file_name FROM parquet_metadata(?)", [values]
                ).fetchall()
                observed = {Path(str(row[0])).resolve() for row in rows}
                for path in batch:
                    if path.resolve() not in observed:
                        invalid[path] = "parquet_footer_not_reported"
            except Exception:
                for path in batch:
                    try:
                        connection.execute(
                            "SELECT 1 FROM parquet_metadata(?) LIMIT 1", [[str(path)]]
                        ).fetchone()
                    except Exception as error:
                        invalid[path] = f"parquet_footer_unreadable:{type(error).__name__}"
    return invalid


def _physical_candidate_fingerprint(
    *, partition_key: str, canonical_uri: str, files: Sequence[Path], lake_root: Path
) -> str:
    payload_files = []
    for path in files:
        stat = path.stat()
        payload_files.append(
            {
                "relative_path": str(path.relative_to(lake_root)),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return _hash_payload(
        {
            "partition_key": partition_key,
            "required_paths": [str(path.relative_to(lake_root)) for path in files],
            "canonical_uri": canonical_uri,
            "file_count": len(files),
            "files": payload_files,
        }
    )


def _partitioned_specs_by_asset() -> dict[str, dg.AssetSpec]:
    resolved = _resolved_defs()
    return {
        spec.key.to_user_string(): spec
        for spec in resolved.resolve_all_asset_specs()
        if spec.partitions_def is not None
    }


def _registered_partitions_by_asset(
    instance: dg.DagsterInstance,
    asset_keys: set[str],
    *,
    partitioned_specs: Mapping[str, dg.AssetSpec] | None = None,
) -> dict[str, set[str]]:
    specs = partitioned_specs or _partitioned_specs_by_asset()
    result: dict[str, set[str]] = {}
    for asset_key in asset_keys:
        spec = specs.get(asset_key)
        if spec is None or spec.partitions_def is None:
            raise HistoricalMaterializationReconciliationError(
                f"Candidate asset no longer has a partition definition: {asset_key}."
            )
        result[asset_key] = set(
            spec.partitions_def.get_partition_keys(dynamic_partitions_store=instance)
        )
    return result


def _hot_partition_keys_by_asset(lake_root: Path, asset_keys: set[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for asset_key in asset_keys:
        pattern = SIMPLE_PATTERNS.get(asset_key)
        if pattern is None:
            raise HistoricalMaterializationReconciliationError(
                f"Candidate asset has no approved physical spec: {asset_key}."
            )
        keys = sorted(
            partition_key
            for path in lake_root.glob(pattern)
            if (partition_key := _parse_partition_key(path)) is not None
        )
        result[asset_key] = set(keys[-HOT_WINDOW_SIZE:])
    return result


def _active_partitioned_asset_keys() -> list[str]:
    resolved = _resolved_defs()
    catalog = {entry.asset_key: entry for entry in list_lake_asset_catalog_entries()}
    return sorted(
        spec.key.to_user_string()
        for spec in resolved.resolve_all_asset_specs()
        if spec.key.to_user_string() in catalog
        and get_partition_model_definition(catalog[spec.key.to_user_string()].partition_model).family
        == PartitionModelFamily.TRADE_DATE_PARTITION
    )


def _check_partitions_by_asset(asset_keys: set[str]) -> dict[str, set[str]]:
    if not asset_keys:
        return {}
    encoded_keys = ", ".join(
        "'" + json.dumps([asset_key]).replace("'", "''") + "'"
        for asset_key in sorted(asset_keys)
    )
    rows = _psql_rows(
        """
        SELECT asset_key, partition
        FROM asset_check_executions
        WHERE partition IS NOT NULL
          AND asset_key IN ("""
        + encoded_keys
        + ")\n        GROUP BY asset_key, partition\n        ORDER BY asset_key, partition"
    )
    result: dict[str, set[str]] = {}
    for encoded_asset_key, partition in rows:
        try:
            decoded = json.loads(encoded_asset_key)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, list) and len(decoded) == 1:
            result.setdefault(str(decoded[0]), set()).add(str(partition))
    return result


def _run_status_counts() -> dict[str, int]:
    return {status: int(count) for status, count in _psql_rows(
        "SELECT status, count(*) FROM runs GROUP BY status ORDER BY status"
    )}


def _assert_no_active_runs() -> None:
    rows = _psql_rows(
        "SELECT status, count(*) FROM runs WHERE status IN ("
        + ", ".join("'" + status + "'" for status in ACTIVE_RUN_STATUSES)
        + ") GROUP BY status ORDER BY status"
    )
    if rows:
        raise HistoricalMaterializationReconciliationError(
            f"Active Dagster runs block reconciliation apply: {dict(rows)}."
        )


def _control_counts() -> dict[str, int]:
    result: dict[str, int] = {}
    for name, query in {
        "asset_check_executions": "SELECT count(*) FROM asset_check_executions",
        "asset_check_event_logs": (
            "SELECT count(*) FROM event_logs "
            "WHERE dagster_event_type IN "
            "('ASSET_CHECK_EVALUATION', 'ASSET_CHECK_EVALUATION_PLANNED')"
        ),
        "runs": "SELECT count(*) FROM runs",
        "run_tags": "SELECT count(*) FROM run_tags",
        "asset_event_tags": "SELECT count(*) FROM asset_event_tags",
        "dynamic_partitions": "SELECT count(*) FROM dynamic_partitions",
    }.items():
        rows = _psql_rows(query)
        result[name] = int(rows[0][0]) if rows else 0
    return result


def _assert_control_counts_unchanged(
    *, before: Mapping[str, int], after: Mapping[str, int]
) -> None:
    changed = {
        key: {"before": before[key], "after": after[key]}
        for key in before
        if before[key] != after.get(key)
    }
    if changed:
        raise HistoricalMaterializationReconciliationError(
            f"Unexpected non-materialization Dagster state change: {changed}."
        )


def _metadata_size(candidate: ReconciliationCandidate, plan_fingerprint: str) -> int:
    payload = build_materialization_metadata(
        uri=candidate.canonical_uri,
        extra_metadata={
            "reconciliation_method": RECONCILIATION_METHOD,
            "reconciliation_batch_id": "00000000-0000-0000-0000-000000000000",
            "reconciliation_file_count": candidate.file_count,
            "reconciliation_plan_fingerprint": plan_fingerprint,
            "check_events_reported": False,
        },
    )
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def _psql_rows(sql: str) -> list[tuple[str, ...]]:
    completed = subprocess.run(
        [
            "psql",
            "-d",
            "goldenshare_dagster",
            "-v",
            "ON_ERROR_STOP=1",
            "-qAt",
            "-F",
            "\t",
            "-c",
            f"BEGIN READ ONLY; {sql}; COMMIT;",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [tuple(line.split("\t")) for line in completed.stdout.splitlines() if line]


def _chunks(values: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _parse_partition_key(path: Path) -> str | None:
    parent = path.parent.name
    if not parent.startswith("trade_date="):
        return None
    value = parent.removeprefix("trade_date=")
    if not ISO_DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _normalize_families(families: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(value.upper() for value in families)
    if not normalized:
        raise HistoricalMaterializationReconciliationError("At least one A-E family is required.")
    if len(set(normalized)) != len(normalized):
        raise HistoricalMaterializationReconciliationError("Families must not repeat.")
    invalid = [value for value in normalized if value not in FAMILY_ASSET_KEYS]
    if invalid:
        raise HistoricalMaterializationReconciliationError(
            f"Unsupported reconciliation families: {invalid}."
        )
    expected_order = tuple(sorted(normalized, key=lambda value: "ABCDE".index(value)))
    if normalized != expected_order:
        raise HistoricalMaterializationReconciliationError("Families must be ordered A through E.")
    return normalized


def _hash_payload(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percentile(values: Sequence[int], percent: int) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    return int(statistics.quantiles(values, n=100, method="inclusive")[percent - 1])


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _resolved_defs():
    # bootstrap modules are imported while Dagster builds the component tree.
    # Importing definitions at module load time would recursively rebuild it.
    from orchestrator.definitions import defs

    return defs()
