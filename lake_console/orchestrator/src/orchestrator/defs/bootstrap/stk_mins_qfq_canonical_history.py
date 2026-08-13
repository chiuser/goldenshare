from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from orchestrator.defs.bootstrap.stk_mins_qfq_derived_history import (
    GOLD_STK_MINS_QFQ_DERIVED_AMOUNT_ABS_TOLERANCE,
    GOLD_STK_MINS_QFQ_DERIVED_AUDIT_MAX_SECONDS,
    GOLD_STK_MINS_QFQ_DERIVED_OHLC_ABS_TOLERANCE,
    GOLD_STK_MINS_QFQ_DERIVED_OHLC_DECIMAL_PLACES,
    audit_stk_mins_qfq_derived_canonical_equivalence,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    STK_MINS_QFQ_HISTORY_START_DATE,
    StkMinsQfqHistoryBatch,
    _generate_qfq_history_batch,
    _history_batch_key,
    plan_stk_mins_qfq_history,
)
from orchestrator.defs.duckdb_connection import DuckDBConnectionSettings
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
)
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_COLUMNS,
    build_as_of_adj_factor_by_code_sql,
    write_gold_stk_mins_qfq_rows_to_year_files,
)

CANONICAL_REBUILD_FREQS = (1, 5, 15, 30, 60)
FULL_REBUILD_FREQS = (5, 15, 30, 60)
DERIVED_EQUIVALENCE_FREQS = (90, 120)
DERIVED_EQUIVALENCE_SAMPLE_YEARS = (2014, 2021, 2026)
EXPECTED_FIRST_TIME_BY_FREQ = {
    1: "09:30:00",
    5: "09:35:00",
    15: "09:45:00",
    30: "10:00:00",
    60: "10:30:00",
    90: "11:00:00",
    120: "11:30:00",
}
PLAN_SCHEMA_VERSION = 1
DEFAULT_REBUILD_STAGING_ROOT = (
    Path(DEFAULT_LAKE_STAGING_ROOT) / "cn_a_minute_gold_p7"
)
DEFAULT_REPORT_ROOT = Path("/private/tmp/cn_a_minute_gold_p7")
MAX_BATCH_SECONDS = 300.0
MAX_TOTAL_SECONDS = 8 * 60 * 60.0
MIN_FREE_SPACE_HEADROOM_BYTES = 20 * 1024**3
P7_DUCKDB_MEMORY_LIMIT = "4GB"
P7_DUCKDB_MAX_TEMP_DIRECTORY_SIZE = "512GB"
P7_DUCKDB_THREADS = 4
P7_STOCK_CHUNK_SIZE = 256


class StkMinsQfqCanonicalHistoryError(RuntimeError):
    pass


def plan_stk_mins_qfq_canonical_history(
    *,
    registered_partition_keys: Sequence[str],
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    staging_root: Path = DEFAULT_REBUILD_STAGING_ROOT,
    report_root: Path = DEFAULT_REPORT_ROOT,
    start_date: str = STK_MINS_QFQ_HISTORY_START_DATE,
    end_date: str,
    duckdb_resource: DuckDBResource,
) -> dict[str, Any]:
    """Freeze the P7 source, target and exact 1m affected scope."""

    started_at = perf_counter()
    lake_root = lake_root.resolve()
    staging_root = staging_root.resolve()
    _assert_formal_roots(lake_root=lake_root, staging_root=staging_root)
    history_plan = plan_stk_mins_qfq_history(
        lake_root=lake_root,
        registered_partition_keys=registered_partition_keys,
        start_date=start_date,
        end_date=end_date,
        freqs=FULL_REBUILD_FREQS,
        duckdb_resource=duckdb_resource,
    )
    if history_plan.missing_input_count:
        raise StkMinsQfqCanonicalHistoryError(
            "Canonical QFQ inputs are missing: "
            f"{history_plan.missing_input_samples}."
        )
    selected_dates = history_plan.selected_partition_keys
    if selected_dates[-1] != end_date:
        raise StkMinsQfqCanonicalHistoryError(
            "The frozen QFQ frontier is not the requested end date."
        )
    planning_root = staging_root / ".planning"
    planning_root.mkdir(parents=True, exist_ok=True)
    planning_scope_path = planning_root / f"affected_scope_{os.getpid()}.parquet"
    planning_scope_path.unlink(missing_ok=True)
    affected_scope_manifest = _discover_one_minute_affected_scope(
        lake_root=lake_root,
        selected_partition_keys=selected_dates,
        duckdb_resource=duckdb_resource,
        output_path=planning_scope_path,
    )
    planning_as_of_path = planning_root / f"as_of_adj_factor_{os.getpid()}.parquet"
    planning_as_of_path.unlink(missing_ok=True)
    as_of_snapshot_manifest = _build_as_of_adj_factor_snapshot(
        lake_root=lake_root,
        selected_partition_keys=selected_dates,
        output_path=planning_as_of_path,
        duckdb_resource=duckdb_resource,
    )

    source_paths = _source_paths_for_plan(
        lake_root=lake_root,
        selected_partition_keys=selected_dates,
    )
    source_manifest = tuple(_file_stat(path, root=lake_root) for path in source_paths)
    code_manifest = tuple(
        _file_content_entry(path, root=_repository_root())
        for path in _code_contract_paths()
    )
    one_minute_target_paths = _one_minute_target_paths(
        planning_scope_path,
        duckdb_resource=duckdb_resource,
        lake_root=lake_root,
    )
    one_minute_sources = tuple(
        _file_content_entry(path, root=lake_root)
        for path in one_minute_target_paths
    )
    batches = tuple(
        {
            "freq": batch.freq,
            "year": batch.year,
            "batch_key": _history_batch_key(batch),
            "partition_keys": list(batch.partition_keys),
            "planned_target_file_count": history_plan.target_file_counts_by_batch[
                (batch.freq, batch.year)
            ],
        }
        for batch in history_plan.batches
    )
    hash_payload: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "contract": "stk_mins_qfq_canonical_history_v1",
        "lake_root": str(lake_root),
        "staging_root": str(staging_root),
        "report_root": str(report_root.resolve()),
        "start_date": selected_dates[0],
        "end_date": selected_dates[-1],
        "selected_partition_keys": list(selected_dates),
        "selected_partition_keys_hash": _hash_json(list(selected_dates)),
        "as_of_adj_factor_trade_date": selected_dates[-1],
        "batches": list(batches),
        "source_manifest": list(source_manifest),
        "one_minute_source_manifest": list(one_minute_sources),
        "affected_scope_manifest": {
            key: value
            for key, value in affected_scope_manifest.items()
            if key != "path"
        },
        "as_of_adj_factor_snapshot_manifest": {
            key: value
            for key, value in as_of_snapshot_manifest.items()
            if key != "path"
        },
        "code_manifest": list(code_manifest),
    }
    plan_hash = _hash_json(hash_payload)
    phase_root = staging_root / plan_hash
    candidate_lake_root = phase_root / "candidate_lake"
    phase_root.mkdir(parents=True, exist_ok=True)
    affected_scope_path = phase_root / "affected-scope.parquet"
    if affected_scope_path.exists():
        if _file_sha256(affected_scope_path) != affected_scope_manifest["sha256"]:
            raise StkMinsQfqCanonicalHistoryError(
                "The frozen affected scope path already contains another manifest."
            )
        planning_scope_path.unlink(missing_ok=True)
    else:
        os.replace(planning_scope_path, affected_scope_path)
    as_of_snapshot_path = phase_root / "as-of-adj-factor.parquet"
    if as_of_snapshot_path.exists():
        if _file_sha256(as_of_snapshot_path) != as_of_snapshot_manifest["sha256"]:
            raise StkMinsQfqCanonicalHistoryError(
                "The frozen as-of factor path already contains another snapshot."
            )
        planning_as_of_path.unlink(missing_ok=True)
    else:
        os.replace(planning_as_of_path, as_of_snapshot_path)
    free_bytes = shutil.disk_usage(staging_root).free
    estimated_candidate_bytes = _estimated_candidate_bytes(
        lake_root=lake_root,
        one_minute_target_paths=one_minute_target_paths,
        freqs=FULL_REBUILD_FREQS,
    )
    required_free_bytes = 2 * estimated_candidate_bytes + MIN_FREE_SPACE_HEADROOM_BYTES
    report: dict[str, Any] = {
        **hash_payload,
        "affected_scope_manifest": {
            **hash_payload["affected_scope_manifest"],
            "path": str(affected_scope_path),
        },
        "as_of_adj_factor_snapshot_manifest": {
            **hash_payload["as_of_adj_factor_snapshot_manifest"],
            "path": str(as_of_snapshot_path),
        },
        "report_type": "stk_mins_qfq_canonical_history_plan",
        "planned_at": _utc_now(),
        "plan_hash": plan_hash,
        "phase_root": str(phase_root),
        "candidate_lake_root": str(candidate_lake_root),
        "planned_target_file_count": history_plan.planned_target_file_count,
        "existing_target_file_count": history_plan.existing_target_file_count,
        "missing_target_file_count": (
            history_plan.planned_target_file_count
            - history_plan.existing_target_file_count
        ),
        "one_minute_affected_pair_count": int(
            affected_scope_manifest["pair_count"]
        ),
        "one_minute_affected_file_count": len(one_minute_sources),
        "one_minute_affected_date_count": int(affected_scope_manifest["date_count"]),
        "one_minute_affected_code_count": int(affected_scope_manifest["code_count"]),
        "one_minute_tail_row_count": int(affected_scope_manifest["tail_row_count"]),
        "one_minute_already_canonical": int(affected_scope_manifest["pair_count"])
        == 0,
        "as_of_adj_factor_code_count": int(as_of_snapshot_manifest["row_count"]),
        "estimated_candidate_bytes": estimated_candidate_bytes,
        "available_bytes": free_bytes,
        "required_free_bytes": required_free_bytes,
        "same_filesystem": lake_root.stat().st_dev == staging_root.stat().st_dev,
        "elapsed_seconds": round(perf_counter() - started_at, 3),
        "should_stop": free_bytes < required_free_bytes,
        "stop_reason_code": (
            "insufficient_staging_space" if free_bytes < required_free_bytes else None
        ),
        "write_counters": {
            "formal_lake": 0,
            "dagster_events": 0,
            "dagster_runs": 0,
            "dynamic_partitions": 0,
        },
    }
    report_root.mkdir(parents=True, exist_ok=True)
    _atomic_json(phase_root / "plan.json", report)
    _atomic_json(report_root / f"plan_{plan_hash}.json", _bounded_summary(report))
    return report


def build_stk_mins_qfq_canonical_candidates(
    *,
    plan_path: Path,
    expected_plan_hash: str,
    freq: int,
    duckdb_resource: DuckDBResource,
    confirm_build: bool,
) -> dict[str, Any]:
    if not confirm_build:
        raise StkMinsQfqCanonicalHistoryError(
            "Candidate build requires explicit confirmation."
        )
    started_at = perf_counter()
    plan = _load_plan(plan_path, expected_plan_hash=expected_plan_hash)
    _assert_plan_unchanged(plan)
    normalized_freq = _normalize_rebuild_freq(freq)
    phase_root = Path(str(plan["phase_root"]))
    manifest_path = phase_root / f"candidate-manifest-freq-{normalized_freq}.json"
    checkpoint = _load_candidate_manifest(
        manifest_path,
        plan_hash=expected_plan_hash,
        freq=normalized_freq,
    )
    completed = set(checkpoint["completed_batch_keys"])
    files_by_path = {
        str(entry["candidate_path"]): entry for entry in checkpoint["files"]
    }
    candidate_lake_root = Path(str(plan["candidate_lake_root"]))
    candidate_lake_root.mkdir(parents=True, exist_ok=True)
    executed_batch_count = 0
    resumed_batch_count = 0

    if normalized_freq == 1:
        batches = _one_minute_batches(plan)
        for batch_key, year in batches:
            entries = _one_minute_scope_groups(
                plan,
                year=year,
                duckdb_resource=duckdb_resource,
            )
            batch_started_at = perf_counter()
            if batch_key in completed:
                _assert_candidate_entries_unchanged(
                    tuple(
                        files_by_path[str(_candidate_path(plan, Path(str(entry["target_path"]))))]
                        for entry in entries
                    )
                )
                resumed_batch_count += 1
                continue
            _assert_one_minute_formal_sources_unchanged(plan, entries)
            batch_files = _build_one_minute_candidate_batch(
                plan=plan,
                scope_entries=entries,
                duckdb_resource=duckdb_resource,
            )
            _assert_batch_budget(batch_key, batch_started_at)
            files_by_path.update(
                {str(entry["candidate_path"]): entry for entry in batch_files}
            )
            completed.add(batch_key)
            executed_batch_count += 1
            _write_candidate_manifest(
                manifest_path,
                plan_hash=expected_plan_hash,
                freq=normalized_freq,
                completed=completed,
                files=tuple(files_by_path.values()),
            )
    else:
        for batch in _history_batches(plan, normalized_freq):
            batch_key = _history_batch_key(batch)
            batch_started_at = perf_counter()
            if batch_key in completed:
                batch_entries = tuple(
                    entry
                    for entry in files_by_path.values()
                    if entry["batch_key"] == batch_key
                )
                if len(batch_entries) != _planned_batch_file_count(plan, batch_key):
                    raise StkMinsQfqCanonicalHistoryError(
                        f"Checkpoint manifest is incomplete for {batch_key}."
                    )
                _assert_candidate_entries_unchanged(batch_entries)
                resumed_batch_count += 1
                continue
            _assert_history_batch_sources_unchanged(plan, batch)
            result = _generate_qfq_history_batch(
                lake_root=Path(str(plan["lake_root"])),
                target_lake_root=candidate_lake_root,
                duckdb_resource=duckdb_resource,
                batch=batch,
                as_of_adj_factor_paths=[
                    Path(
                        str(
                            plan["as_of_adj_factor_snapshot_manifest"]["path"]
                        )
                    )
                ],
                fail_if_target_exists=False,
                candidate_export_root=phase_root / "batch-export",
                connection_settings=DuckDBConnectionSettings(
                    temp_directory=phase_root / "duckdb-temp",
                    max_temp_directory_size=P7_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
                    memory_limit=P7_DUCKDB_MEMORY_LIMIT,
                    threads=P7_DUCKDB_THREADS,
                ),
                candidate_stock_chunk_size=P7_STOCK_CHUNK_SIZE,
            )
            _assert_batch_budget(batch_key, batch_started_at)
            if result.written_file_count != _planned_batch_file_count(plan, batch_key):
                raise StkMinsQfqCanonicalHistoryError(
                    f"Candidate file count differs from the frozen plan for {batch_key}."
                )
            batch_files = tuple(
                _candidate_manifest_entry(
                    plan=plan,
                    candidate_path=write.path,
                    batch_key=batch_key,
                    row_count=write.row_count,
                    replacement_row_count=write.replacement_row_count,
                )
                for write in result.write_results
            )
            files_by_path.update(
                {str(entry["candidate_path"]): entry for entry in batch_files}
            )
            completed.add(batch_key)
            executed_batch_count += 1
            _write_candidate_manifest(
                manifest_path,
                plan_hash=expected_plan_hash,
                freq=normalized_freq,
                completed=completed,
                files=tuple(files_by_path.values()),
            )

    manifest = _load_json(manifest_path, label="candidate manifest")
    elapsed_seconds = perf_counter() - started_at
    report = {
        "report_type": "stk_mins_qfq_canonical_candidates",
        "created_at": _utc_now(),
        "plan_hash": expected_plan_hash,
        "freq": normalized_freq,
        "manifest_path": str(manifest_path),
        "completed_batch_count": len(manifest["completed_batch_keys"]),
        "candidate_file_count": len(manifest["files"]),
        "candidate_row_count": sum(int(entry["row_count"]) for entry in manifest["files"]),
        "candidate_bytes": sum(int(entry["candidate_size_bytes"]) for entry in manifest["files"]),
        "executed_batch_count": executed_batch_count,
        "resumed_batch_count": resumed_batch_count,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "within_total_budget": elapsed_seconds <= MAX_TOTAL_SECONDS,
        "formal_lake_write_count": 0,
        "should_stop": elapsed_seconds > MAX_TOTAL_SECONDS,
    }
    _write_report(plan, f"candidate_build_freq_{normalized_freq}", report)
    return report


def audit_stk_mins_qfq_canonical_candidates(
    *,
    plan_path: Path,
    expected_plan_hash: str,
    freq: int,
    duckdb_resource: DuckDBResource,
) -> dict[str, Any]:
    started_at = perf_counter()
    plan = _load_plan(plan_path, expected_plan_hash=expected_plan_hash)
    _assert_plan_unchanged(plan)
    normalized_freq = _normalize_rebuild_freq(freq)
    manifest_path = Path(str(plan["phase_root"])) / (
        f"candidate-manifest-freq-{normalized_freq}.json"
    )
    manifest = _load_candidate_manifest(
        manifest_path,
        plan_hash=expected_plan_hash,
        freq=normalized_freq,
    )
    expected_batches = _expected_batch_keys(plan, normalized_freq)
    completed_batches = tuple(manifest["completed_batch_keys"])
    if set(completed_batches) != set(expected_batches):
        raise StkMinsQfqCanonicalHistoryError(
            f"Frequency {normalized_freq} candidates are incomplete."
        )
    entries = tuple(manifest["files"])
    _assert_candidate_entries_unchanged(entries)
    shape = _audit_frequency_shape(
        paths=tuple(Path(str(entry["candidate_path"])) for entry in entries),
        freq=normalized_freq,
        duckdb_resource=duckdb_resource,
    )
    coverage = (
        {"missing_code_date_count": 0, "extra_code_date_count": 0}
        if normalized_freq == 1
        else _audit_full_rebuild_coverage(
            plan=plan,
            freq=normalized_freq,
            candidate_paths=tuple(
                Path(str(entry["candidate_path"])) for entry in entries
            ),
            duckdb_resource=duckdb_resource,
        )
    )
    expected_file_count = (
        int(plan["one_minute_affected_file_count"])
        if normalized_freq == 1
        else sum(
            int(batch["planned_target_file_count"])
            for batch in plan["batches"]
            if int(batch["freq"]) == normalized_freq
        )
    )
    one_minute_diff_failures = sum(
        int(entry.get("unexpected_difference_count", 0)) for entry in entries
    )
    removed_rows = sum(int(entry.get("removed_row_count", 0)) for entry in entries)
    ready = (
        len(entries) == expected_file_count
        and shape["schema_matches"]
        and shape["duplicate_key_count"] == 0
        and shape["after_1500_row_count"] == 0
        and shape["unexpected_first_time_count"] == 0
        and shape["unexpected_last_time_count"] == 0
        and (
            normalized_freq == 1
            or shape["at_0930_row_count"] == 0
        )
        and one_minute_diff_failures == 0
        and coverage["missing_code_date_count"] == 0
        and coverage["extra_code_date_count"] == 0
        and (
            normalized_freq != 1
            or removed_rows == int(plan["one_minute_tail_row_count"])
        )
    )
    candidate_fingerprint = _hash_json(
        [
            {
                "path": entry["candidate_path"],
                "sha256": entry["candidate_sha256"],
                "size_bytes": entry["candidate_size_bytes"],
            }
            for entry in sorted(entries, key=lambda item: str(item["candidate_path"]))
        ]
    )
    report = {
        "report_type": "stk_mins_qfq_canonical_candidate_audit",
        "audited_at": _utc_now(),
        "plan_hash": expected_plan_hash,
        "freq": normalized_freq,
        "manifest_path": str(manifest_path),
        "candidate_file_count": len(entries),
        "expected_file_count": expected_file_count,
        "candidate_fingerprint": candidate_fingerprint,
        "shape": shape,
        "coverage": coverage,
        "one_minute_unexpected_difference_count": one_minute_diff_failures,
        "one_minute_removed_row_count": removed_rows,
        "ready": ready,
        "should_stop": not ready,
        "elapsed_seconds": round(perf_counter() - started_at, 3),
    }
    path = _write_report(plan, f"candidate_audit_freq_{normalized_freq}", report)
    _atomic_json(
        Path(str(plan["phase_root"])) / f"candidate-audit-freq-{normalized_freq}.json",
        {**report, "report_path": str(path)},
    )
    return report


def promote_stk_mins_qfq_canonical_candidates(
    *,
    plan_path: Path,
    expected_plan_hash: str,
    freq: int,
    confirm_promote: bool,
) -> dict[str, Any]:
    if not confirm_promote:
        raise StkMinsQfqCanonicalHistoryError(
            "Formal promotion requires explicit confirmation."
        )
    started_at = perf_counter()
    plan = _load_plan(plan_path, expected_plan_hash=expected_plan_hash)
    _assert_plan_unchanged(plan)
    normalized_freq = _normalize_rebuild_freq(freq)
    phase_root = Path(str(plan["phase_root"]))
    manifest = _load_candidate_manifest(
        phase_root / f"candidate-manifest-freq-{normalized_freq}.json",
        plan_hash=expected_plan_hash,
        freq=normalized_freq,
    )
    audit = _load_json(
        phase_root / f"candidate-audit-freq-{normalized_freq}.json",
        label="candidate audit",
    )
    if (
        audit.get("plan_hash") != expected_plan_hash
        or audit.get("freq") != normalized_freq
        or audit.get("ready") is not True
    ):
        raise StkMinsQfqCanonicalHistoryError(
            "Candidates are not eligible for formal promotion."
        )
    if Path(str(plan["candidate_lake_root"])).stat().st_dev != Path(
        str(plan["lake_root"])
    ).stat().st_dev:
        raise StkMinsQfqCanonicalHistoryError(
            "Candidate and formal Lake roots are not on the same filesystem."
        )
    entries_by_batch: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for entry in manifest["files"]:
        entries_by_batch[str(entry["batch_key"])].append(entry)
    expected_batches = _expected_batch_keys(plan, normalized_freq)
    checkpoint_path = phase_root / f"promotion-checkpoint-freq-{normalized_freq}.json"
    checkpoint = _load_promotion_checkpoint(
        checkpoint_path,
        plan_hash=expected_plan_hash,
        freq=normalized_freq,
    )
    completed = set(checkpoint["completed_batch_keys"])
    _assert_source_manifest_unchanged(plan)
    for batch_key in expected_batches:
        batch_entries = tuple(entries_by_batch[batch_key])
        if batch_key in completed:
            _assert_formal_entries_match_candidates(batch_entries)
            continue
        for entry in batch_entries:
            _assert_promotable_entry_state(entry)
    promoted_file_count = 0
    resumed_batch_count = 0
    for batch_key in expected_batches:
        batch_entries = tuple(
            sorted(entries_by_batch[batch_key], key=lambda item: str(item["formal_path"]))
        )
        if batch_key in completed:
            _assert_formal_entries_match_candidates(batch_entries)
            resumed_batch_count += 1
            continue
        for entry in batch_entries:
            _assert_promotable_entry_state(entry)
        for entry in batch_entries:
            candidate = Path(str(entry["candidate_path"]))
            formal = Path(str(entry["formal_path"]))
            if candidate.exists():
                formal.parent.mkdir(parents=True, exist_ok=True)
                os.replace(candidate, formal)
                promoted_file_count += 1
            elif _file_sha256(formal) != entry["candidate_sha256"]:
                raise StkMinsQfqCanonicalHistoryError(
                    f"Candidate is missing and formal target is not promoted: {formal}."
                )
        _assert_formal_entries_match_candidates(batch_entries)
        completed.add(batch_key)
        _atomic_json(
            checkpoint_path,
            {
                "schema_version": 1,
                "plan_hash": expected_plan_hash,
                "freq": normalized_freq,
                "completed_batch_keys": sorted(completed),
            },
        )
    report = {
        "report_type": "stk_mins_qfq_canonical_promotion",
        "promoted_at": _utc_now(),
        "plan_hash": expected_plan_hash,
        "freq": normalized_freq,
        "promoted_file_count": promoted_file_count,
        "resumed_batch_count": resumed_batch_count,
        "completed_batch_count": len(completed),
        "formal_lake_write_count": promoted_file_count,
        "dagster_event_write_count": 0,
        "elapsed_seconds": round(perf_counter() - started_at, 3),
        "should_stop": False,
    }
    _write_report(plan, f"promote_freq_{normalized_freq}", report)
    return report


def audit_stk_mins_qfq_canonical_formal(
    *,
    plan_path: Path,
    expected_plan_hash: str,
    freq: int,
    duckdb_resource: DuckDBResource,
) -> dict[str, Any]:
    started_at = perf_counter()
    plan = _load_plan(plan_path, expected_plan_hash=expected_plan_hash)
    normalized_freq = _normalize_rebuild_freq(freq)
    manifest = _load_candidate_manifest(
        Path(str(plan["phase_root"])) / f"candidate-manifest-freq-{normalized_freq}.json",
        plan_hash=expected_plan_hash,
        freq=normalized_freq,
    )
    entries = tuple(manifest["files"])
    hash_mismatch_count = 0
    missing_file_count = 0
    for entry in entries:
        formal = Path(str(entry["formal_path"]))
        if not formal.exists():
            missing_file_count += 1
        elif _file_sha256(formal) != entry["candidate_sha256"]:
            hash_mismatch_count += 1
    shape = _audit_frequency_shape(
        paths=tuple(Path(str(entry["formal_path"])) for entry in entries),
        freq=normalized_freq,
        duckdb_resource=duckdb_resource,
    )
    candidate_residual_count = sum(
        1 for entry in entries if Path(str(entry["candidate_path"])).exists()
    )
    ready = (
        missing_file_count == 0
        and hash_mismatch_count == 0
        and candidate_residual_count == 0
        and shape["schema_matches"]
        and shape["duplicate_key_count"] == 0
        and shape["after_1500_row_count"] == 0
        and shape["unexpected_first_time_count"] == 0
        and shape["unexpected_last_time_count"] == 0
        and (normalized_freq == 1 or shape["at_0930_row_count"] == 0)
    )
    report = {
        "report_type": "stk_mins_qfq_canonical_formal_audit",
        "audited_at": _utc_now(),
        "plan_hash": expected_plan_hash,
        "freq": normalized_freq,
        "formal_file_count": len(entries),
        "missing_file_count": missing_file_count,
        "hash_mismatch_count": hash_mismatch_count,
        "candidate_residual_count": candidate_residual_count,
        "shape": shape,
        "ready": ready,
        "should_stop": not ready,
        "elapsed_seconds": round(perf_counter() - started_at, 3),
    }
    _write_report(plan, f"formal_audit_freq_{normalized_freq}", report)
    return report


def audit_stk_mins_qfq_derived_equivalence_to_report(
    *,
    plan_path: Path,
    expected_plan_hash: str,
    freq: int,
    year: int,
    duckdb_resource: DuckDBResource,
) -> dict[str, Any]:
    started_at = perf_counter()
    plan = _load_plan(plan_path, expected_plan_hash=expected_plan_hash)
    _assert_plan_unchanged(plan)
    if freq not in DERIVED_EQUIVALENCE_FREQS:
        raise StkMinsQfqCanonicalHistoryError(
            f"Derived equivalence freq must be one of {DERIVED_EQUIVALENCE_FREQS}."
        )
    if year not in DERIVED_EQUIVALENCE_SAMPLE_YEARS:
        raise StkMinsQfqCanonicalHistoryError(
            "Derived equivalence year must be one of the frozen sample years: "
            f"{DERIVED_EQUIVALENCE_SAMPLE_YEARS}."
        )
    try:
        result = audit_stk_mins_qfq_derived_canonical_equivalence(
            lake_root=Path(str(plan["lake_root"])),
            duckdb_resource=duckdb_resource,
            registered_partition_keys=tuple(plan["selected_partition_keys"]),
            start_date=str(plan["start_date"]),
            end_date=str(plan["end_date"]),
            freqs=(freq,),
            years=(year,),
            max_elapsed_seconds=GOLD_STK_MINS_QFQ_DERIVED_AUDIT_MAX_SECONDS,
            as_of_adj_factor_paths=(
                Path(str(plan["as_of_adj_factor_snapshot_manifest"]["path"])),
            ),
        )
    except TimeoutError as error:
        raise StkMinsQfqCanonicalHistoryError(str(error)) from error
    audits = [
        {
            "freq": audit.target_freq,
            "year": audit.year,
            "candidate_row_count": audit.candidate_row_count,
            "existing_row_count": audit.existing_row_count,
            "candidate_key_hash": audit.candidate_key_hash,
            "existing_key_hash": audit.existing_key_hash,
            "candidate_value_hash": audit.candidate_value_hash,
            "existing_value_hash": audit.existing_value_hash,
            "missing_key_count": audit.missing_key_count,
            "extra_key_count": audit.extra_key_count,
            "value_mismatch_count": audit.value_mismatch_count,
            "max_ohlc_abs_difference": audit.max_ohlc_abs_difference,
            "max_amount_abs_difference": audit.max_amount_abs_difference,
            "passed": audit.passed,
        }
        for audit in result.batch_audits
    ]
    elapsed_seconds = perf_counter() - started_at
    within_time_budget = (
        elapsed_seconds <= GOLD_STK_MINS_QFQ_DERIVED_AUDIT_MAX_SECONDS
    )
    ready = result.passed and within_time_budget
    report = {
        "report_type": "stk_mins_qfq_derived_equivalence",
        "audited_at": _utc_now(),
        "plan_hash": expected_plan_hash,
        "freq": freq,
        "year": year,
        "ohlc_decimal_places": GOLD_STK_MINS_QFQ_DERIVED_OHLC_DECIMAL_PLACES,
        "ohlc_abs_tolerance": GOLD_STK_MINS_QFQ_DERIVED_OHLC_ABS_TOLERANCE,
        "amount_abs_tolerance": GOLD_STK_MINS_QFQ_DERIVED_AMOUNT_ABS_TOLERANCE,
        "max_elapsed_seconds": GOLD_STK_MINS_QFQ_DERIVED_AUDIT_MAX_SECONDS,
        "batch_count": len(audits),
        "batch_audits": audits,
        "within_time_budget": within_time_budget,
        "ready": ready,
        "should_stop": not ready,
        "formal_lake_write_count": 0,
        "elapsed_seconds": round(elapsed_seconds, 3),
    }
    _write_report(plan, f"derived_equivalence_freq_{freq}_year_{year}", report)
    return report


def _discover_one_minute_affected_scope(
    *,
    lake_root: Path,
    selected_partition_keys: Sequence[str],
    duckdb_resource: DuckDBResource,
    output_path: Path,
) -> dict[str, Any]:
    selected_set = set(selected_partition_keys)
    silver_pattern = str(
        lake_root / "silver/quote/stk_mins/freq=1/trade_date=*/part-000.parquet"
    )
    with duckdb_resource.connect() as connection:
        silver_rows = connection.execute(
            """
            SELECT DISTINCT
              regexp_extract(file_name, 'trade_date=([0-9-]+)', 1) AS trade_date
            FROM parquet_metadata(?)
            WHERE path_in_schema = 'trade_time'
              AND CAST(stats_max AS TIMESTAMP)::TIME > TIME '15:00:00'
              AND CAST(stats_max AS TIMESTAMP)::TIME <= TIME '15:30:00'
            ORDER BY trade_date
            """,
            [silver_pattern],
        ).fetchall()
        candidate_dates = tuple(
            str(row[0]) for row in silver_rows if str(row[0]) in selected_set
        )
        if not candidate_dates:
            return _empty_affected_scope_manifest(
                output_path,
                duckdb_resource=duckdb_resource,
            )
        candidate_years = tuple(sorted({date[:4] for date in candidate_dates}))
        paths = tuple(
            sorted(
                path
                for year in candidate_years
                for path in (
                    lake_root / "gold/quote/stk_mins_qfq/freq=1"
                ).glob(f"ts_code=*/year={year}/part-000.parquet")
            )
        )
        if not paths:
            return _empty_affected_scope_manifest(
                output_path,
                duckdb_resource=duckdb_resource,
            )
        connection.execute(
            """
            CREATE TEMP TABLE affected_scope (
              ts_code VARCHAR,
              trade_date DATE,
              tail_row_count BIGINT
            )
            """
        )
        date_values = ", ".join(
            f"DATE {duckdb_string(trade_date)}" for trade_date in candidate_dates
        )
        for chunk in _chunks(paths, 250):
            source = _read_paths(chunk)
            invalid_after_close = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM {source}
                    WHERE CAST(trade_date AS DATE) IN ({date_values})
                      AND CAST(trade_time AS TIME) > TIME '15:30:00'
                    """
                ).fetchone()[0]
            )
            if invalid_after_close:
                raise StkMinsQfqCanonicalHistoryError(
                    "Gold 1m contains rows after 15:30; the approved scope only "
                    "covers 15:01-15:30."
                )
            connection.execute(
                f"""
                INSERT INTO affected_scope
                SELECT
                  CAST(ts_code AS VARCHAR),
                  CAST(trade_date AS DATE),
                  count(*)
                FROM {source}
                WHERE CAST(trade_date AS DATE) IN ({date_values})
                  AND CAST(trade_time AS TIME) > TIME '15:00:00'
                  AND CAST(trade_time AS TIME) <= TIME '15:30:00'
                GROUP BY ts_code, trade_date
                """
            )
        duplicate_pairs = int(
            connection.execute(
                """
                SELECT count(*)
                FROM (
                  SELECT ts_code, trade_date, count(*)
                  FROM affected_scope
                  GROUP BY ts_code, trade_date
                  HAVING count(*) > 1
                )
                """
            ).fetchone()[0]
        )
        if duplicate_pairs:
            raise StkMinsQfqCanonicalHistoryError(
                "The exact Gold 1m affected scope contains duplicate pairs."
            )
        rows = connection.execute(
            """
            SELECT
              count(*) AS pair_count,
              count(DISTINCT ts_code) AS code_count,
              count(DISTINCT trade_date) AS date_count,
              min(trade_date) AS first_trade_date,
              max(trade_date) AS last_trade_date,
              sum(tail_row_count) AS tail_row_count
            FROM affected_scope
            """
        ).fetchone()
        if rows is None or int(rows[0]) == 0:
            return _empty_affected_scope_manifest(
                output_path,
                duckdb_resource=duckdb_resource,
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
        connection.execute(
            copy_query_to_parquet(
                """
                SELECT
                  ts_code,
                  trade_date,
                  CAST(year(trade_date) AS VARCHAR) AS year,
                  tail_row_count
                FROM affected_scope
                ORDER BY trade_date, ts_code
                """,
                output_path,
            )
        )
    return {
        "path": str(output_path),
        "sha256": _file_sha256(output_path),
        "size_bytes": output_path.stat().st_size,
        "pair_count": int(rows[0]),
        "code_count": int(rows[1]),
        "date_count": int(rows[2]),
        "first_trade_date": rows[3].isoformat(),
        "last_trade_date": rows[4].isoformat(),
        "tail_row_count": int(rows[5]),
        "years": sorted({date[:4] for date in candidate_dates}),
        "footer_candidate_date_count": len(candidate_dates),
    }


def _empty_affected_scope_manifest(
    path: Path,
    *,
    duckdb_resource: DuckDBResource,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with duckdb_resource.connect() as connection:
        connection.execute(
            copy_query_to_parquet(
                """
                SELECT
                  NULL::VARCHAR AS ts_code,
                  NULL::DATE AS trade_date,
                  NULL::VARCHAR AS year,
                  NULL::BIGINT AS tail_row_count
                WHERE false
                """,
                path,
            )
        )
    return {
        "path": str(path),
        "sha256": _file_sha256(path),
        "size_bytes": path.stat().st_size,
        "pair_count": 0,
        "code_count": 0,
        "date_count": 0,
        "first_trade_date": None,
        "last_trade_date": None,
        "tail_row_count": 0,
        "years": [],
        "footer_candidate_date_count": 0,
    }


def _build_as_of_adj_factor_snapshot(
    *,
    lake_root: Path,
    selected_partition_keys: Sequence[str],
    output_path: Path,
    duckdb_resource: DuckDBResource,
) -> dict[str, Any]:
    factor_paths = tuple(
        silver_adj_factor_path(lake_root, trade_date)
        for trade_date in selected_partition_keys
    )
    as_of_sql = build_as_of_adj_factor_by_code_sql(factor_paths)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    with duckdb_resource.connect() as connection:
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT
                  ts_code,
                  as_of_trade_date AS trade_date,
                  as_of_adj_factor AS adj_factor
                FROM ({as_of_sql})
                ORDER BY ts_code
                """,
                output_path,
            )
        )
        row = connection.execute(
            f"""
            SELECT
              count(*),
              count(DISTINCT ts_code),
              count(*) FILTER (
                WHERE ts_code IS NULL OR trim(ts_code) = ''
                   OR trade_date IS NULL
                   OR adj_factor IS NULL
                   OR NOT isfinite(adj_factor)
                   OR adj_factor <= 0
              ),
              min(trade_date),
              max(trade_date)
            FROM {read_parquet(output_path, hive_partitioning=False)}
            """
        ).fetchone()
    if row is None or int(row[0]) == 0:
        raise StkMinsQfqCanonicalHistoryError(
            "The frozen as-of adj-factor snapshot is empty."
        )
    if int(row[0]) != int(row[1]) or int(row[2]):
        raise StkMinsQfqCanonicalHistoryError(
            "The frozen as-of adj-factor snapshot failed its key/value contract."
        )
    return {
        "path": str(output_path),
        "sha256": _file_sha256(output_path),
        "size_bytes": output_path.stat().st_size,
        "row_count": int(row[0]),
        "first_factor_trade_date": row[3].isoformat(),
        "last_factor_trade_date": row[4].isoformat(),
        "as_of_trade_date": selected_partition_keys[-1],
    }


def _build_one_minute_candidate_batch(
    *,
    plan: Mapping[str, Any],
    scope_entries: Sequence[Mapping[str, Any]],
    duckdb_resource: DuckDBResource,
) -> tuple[dict[str, Any], ...]:
    results: list[dict[str, Any]] = []
    for entry in sorted(scope_entries, key=lambda item: str(item["target_path"])):
        formal = Path(str(entry["target_path"]))
        candidate = _candidate_path(plan, formal)
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.unlink(missing_ok=True)
        shutil.copy2(formal, candidate)
        trade_dates = tuple(str(value) for value in entry["trade_dates"])
        dates_sql = ", ".join(
            f"DATE {duckdb_string(trade_date)}" for trade_date in trade_dates
        )
        columns = ", ".join(GOLD_STK_MINS_QFQ_COLUMNS)
        replacement_sql = f"""
        SELECT {columns}
        FROM {read_parquet(formal, hive_partitioning=False)}
        WHERE CAST(trade_date AS DATE) IN ({dates_sql})
          AND CAST(trade_time AS TIME) <= TIME '15:00:00'
        ORDER BY trade_date, trade_time
        """
        write_results = write_gold_stk_mins_qfq_rows_to_year_files(
            lake_root=Path(str(plan["candidate_lake_root"])),
            freq=1,
            qfq_select_sql=replacement_sql,
            replace_trade_dates=trade_dates,
            fail_if_target_exists=False,
        )
        if len(write_results) != 1 or write_results[0].path != candidate:
            raise StkMinsQfqCanonicalHistoryError(
                f"Unexpected 1m candidate target for {formal}."
            )
        removed = _row_count(formal, duckdb_resource) - _row_count(
            candidate, duckdb_resource
        )
        expected_removed = int(entry["tail_row_count"])
        unexpected_difference_count = _one_minute_unexpected_difference_count(
            formal=formal,
            candidate=candidate,
            trade_dates=trade_dates,
            duckdb_resource=duckdb_resource,
        )
        if removed != expected_removed or unexpected_difference_count:
            raise StkMinsQfqCanonicalHistoryError(
                f"1m candidate changed rows outside the approved tail scope: {formal}."
            )
        results.append(
            _candidate_manifest_entry(
                plan=plan,
                candidate_path=candidate,
                batch_key=f"1:{entry['year']}",
                row_count=write_results[0].row_count,
                replacement_row_count=write_results[0].replacement_row_count,
                removed_row_count=removed,
                unexpected_difference_count=unexpected_difference_count,
            )
        )
    return tuple(results)


def _one_minute_unexpected_difference_count(
    *,
    formal: Path,
    candidate: Path,
    trade_dates: Sequence[str],
    duckdb_resource: DuckDBResource,
) -> int:
    dates_sql = ", ".join(
        f"DATE {duckdb_string(trade_date)}" for trade_date in trade_dates
    )
    columns = ", ".join(GOLD_STK_MINS_QFQ_COLUMNS)
    with duckdb_resource.connect() as connection:
        return int(
            connection.execute(
                f"""
                WITH expected AS (
                  SELECT {columns}
                  FROM {read_parquet(formal, hive_partitioning=False)}
                  WHERE CAST(trade_date AS DATE) NOT IN ({dates_sql})
                     OR CAST(trade_time AS TIME) <= TIME '15:00:00'
                ),
                actual AS (
                  SELECT {columns}
                  FROM {read_parquet(candidate, hive_partitioning=False)}
                ),
                differences AS (
                  (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
                  UNION ALL
                  (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
                )
                SELECT count(*) FROM differences
                """
            ).fetchone()[0]
        )


def _audit_frequency_shape(
    *,
    paths: Sequence[Path],
    freq: int,
    duckdb_resource: DuckDBResource,
) -> dict[str, Any]:
    if not paths:
        raise StkMinsQfqCanonicalHistoryError("Frequency audit path scope is empty.")
    expected_first = EXPECTED_FIRST_TIME_BY_FREQ[freq]
    total_row_count = 0
    at_0930_row_count = 0
    after_1500_row_count = 0
    duplicate_key_count = 0
    unexpected_first_time_count = 0
    unexpected_last_time_count = 0
    schema_matches = True
    expected_schema = [(column.name, column.type) for column in GOLD_STK_MINS_QFQ_SCHEMA]
    with duckdb_resource.connect() as connection:
        for chunk in _chunks(tuple(paths), 250):
            source = _read_paths(chunk)
            observed_schema = [
                (str(row[0]), str(row[1]))
                for row in connection.execute(
                    f"DESCRIBE SELECT * FROM {source}"
                ).fetchall()
            ]
            schema_matches = schema_matches and observed_schema == expected_schema
            row = connection.execute(
                f"""
                WITH source_rows AS MATERIALIZED (
                  SELECT * FROM {source}
                ),
                per_day AS (
                  SELECT
                    ts_code,
                    trade_date,
                    min(CAST(trade_time AS TIME)) AS first_time,
                    max(CAST(trade_time AS TIME)) AS last_time
                  FROM source_rows
                  GROUP BY ts_code, trade_date
                ),
                duplicate_keys AS (
                  SELECT count(*) AS duplicate_key_count
                  FROM (
                    SELECT ts_code, trade_time
                    FROM source_rows
                    GROUP BY ts_code, trade_time
                    HAVING count(*) > 1
                  )
                )
                SELECT
                  count(*) AS row_count,
                  count(*) FILTER (
                    WHERE CAST(trade_time AS TIME) = TIME '09:30:00'
                  ) AS at_0930,
                  count(*) FILTER (
                    WHERE CAST(trade_time AS TIME) > TIME '15:00:00'
                  ) AS after_1500,
                  (SELECT duplicate_key_count FROM duplicate_keys),
                  (SELECT count(*) FROM per_day
                   WHERE first_time <> CAST({duckdb_string(expected_first)} AS TIME)),
                  (SELECT count(*) FROM per_day
                   WHERE last_time <> TIME '15:00:00')
                FROM source_rows
                """
            ).fetchone()
            total_row_count += int(row[0])
            at_0930_row_count += int(row[1])
            after_1500_row_count += int(row[2])
            duplicate_key_count += int(row[3])
            unexpected_first_time_count += int(row[4])
            unexpected_last_time_count += int(row[5])
    return {
        "row_count": total_row_count,
        "schema_matches": schema_matches,
        "duplicate_key_count": duplicate_key_count,
        "at_0930_row_count": at_0930_row_count,
        "after_1500_row_count": after_1500_row_count,
        "unexpected_first_time_count": unexpected_first_time_count,
        "unexpected_last_time_count": unexpected_last_time_count,
        "expected_first_time": expected_first,
        "expected_last_time": "15:00:00",
    }


def _audit_full_rebuild_coverage(
    *,
    plan: Mapping[str, Any],
    freq: int,
    candidate_paths: Sequence[Path],
    duckdb_resource: DuckDBResource,
) -> dict[str, int]:
    source_freq = {5: 1, 15: 5, 30: 5, 60: 30}[freq]
    candidate_by_year: dict[str, list[Path]] = defaultdict(list)
    for path in candidate_paths:
        candidate_by_year[path.parent.name.removeprefix("year=")].append(path)
    missing_count = 0
    extra_count = 0
    with duckdb_resource.connect() as connection:
        for batch in _history_batches(plan, freq):
            source_paths = tuple(
                Path(str(plan["lake_root"]))
                / (
                    "silver/quote/stk_mins/"
                    f"freq={source_freq}/trade_date={trade_date}/part-000.parquet"
                )
                for trade_date in batch.partition_keys
            )
            year_candidates = tuple(candidate_by_year[batch.year])
            if not year_candidates:
                raise StkMinsQfqCanonicalHistoryError(
                    f"No candidate files are available for {freq}:{batch.year}."
                )
            connection.execute(
                "CREATE OR REPLACE TEMP TABLE expected_coverage "
                "(ts_code VARCHAR, trade_date DATE)"
            )
            connection.execute(
                "CREATE OR REPLACE TEMP TABLE actual_coverage "
                "(ts_code VARCHAR, trade_date DATE)"
            )
            for chunk in _chunks(source_paths, 250):
                connection.execute(
                    f"""
                    INSERT INTO expected_coverage
                    SELECT DISTINCT
                      CAST(ts_code AS VARCHAR),
                      CAST(trade_date AS DATE)
                    FROM {_read_paths(chunk)}
                    """
                )
            for chunk in _chunks(year_candidates, 250):
                connection.execute(
                    f"""
                    INSERT INTO actual_coverage
                    SELECT DISTINCT
                      CAST(ts_code AS VARCHAR),
                      CAST(trade_date AS DATE)
                    FROM {_read_paths(chunk)}
                    """
                )
            missing_count += int(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM (
                      SELECT * FROM expected_coverage
                      EXCEPT
                      SELECT * FROM actual_coverage
                    )
                    """
                ).fetchone()[0]
            )
            extra_count += int(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM (
                      SELECT * FROM actual_coverage
                      EXCEPT
                      SELECT * FROM expected_coverage
                    )
                    """
                ).fetchone()[0]
            )
    return {
        "missing_code_date_count": missing_count,
        "extra_code_date_count": extra_count,
    }


def _candidate_manifest_entry(
    *,
    plan: Mapping[str, Any],
    candidate_path: Path,
    batch_key: str,
    row_count: int,
    replacement_row_count: int,
    removed_row_count: int = 0,
    unexpected_difference_count: int = 0,
) -> dict[str, Any]:
    formal = Path(str(plan["lake_root"])) / candidate_path.relative_to(
        Path(str(plan["candidate_lake_root"]))
    )
    before = _optional_file_content_entry(formal, root=Path(str(plan["lake_root"])))
    return {
        "batch_key": batch_key,
        "candidate_path": str(candidate_path),
        "formal_path": str(formal),
        "candidate_sha256": _file_sha256(candidate_path),
        "candidate_size_bytes": candidate_path.stat().st_size,
        "row_count": int(row_count),
        "replacement_row_count": int(replacement_row_count),
        "removed_row_count": int(removed_row_count),
        "unexpected_difference_count": int(unexpected_difference_count),
        "formal_before": before,
    }


def _source_paths_for_plan(
    *, lake_root: Path, selected_partition_keys: Sequence[str]
) -> tuple[Path, ...]:
    source_freqs = (1, 5, 30)
    paths = [
        lake_root
        / f"silver/quote/stk_mins/freq={freq}/trade_date={trade_date}/part-000.parquet"
        for freq in source_freqs
        for trade_date in selected_partition_keys
    ]
    paths.extend(
        silver_adj_factor_path(lake_root, trade_date)
        for trade_date in selected_partition_keys
    )
    missing = tuple(path for path in paths if not path.exists())
    if missing:
        raise StkMinsQfqCanonicalHistoryError(
            f"Frozen source manifest is incomplete: {missing[:5]}."
        )
    return tuple(paths)


def _estimated_candidate_bytes(
    *,
    lake_root: Path,
    one_minute_target_paths: Sequence[Path],
    freqs: Sequence[int],
) -> int:
    paths = set(one_minute_target_paths)
    for freq in freqs:
        root = lake_root / f"gold/quote/stk_mins_qfq/freq={freq}"
        paths.update(root.glob("ts_code=*/year=*/part-000.parquet"))
    return sum(path.stat().st_size for path in paths if path.exists())


def _history_batches(
    plan: Mapping[str, Any], freq: int
) -> tuple[StkMinsQfqHistoryBatch, ...]:
    return tuple(
        StkMinsQfqHistoryBatch(
            freq=freq,
            year=str(batch["year"]),
            partition_keys=tuple(batch["partition_keys"]),
        )
        for batch in plan["batches"]
        if int(batch["freq"]) == freq
    )


def _one_minute_batches(
    plan: Mapping[str, Any]
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (f"1:{year}", str(year))
        for year in plan["affected_scope_manifest"]["years"]
    )


def _expected_batch_keys(plan: Mapping[str, Any], freq: int) -> tuple[str, ...]:
    if freq == 1:
        return tuple(batch_key for batch_key, _year in _one_minute_batches(plan))
    return tuple(_history_batch_key(batch) for batch in _history_batches(plan, freq))


def _planned_batch_file_count(plan: Mapping[str, Any], batch_key: str) -> int:
    for batch in plan["batches"]:
        if batch["batch_key"] == batch_key:
            return int(batch["planned_target_file_count"])
    raise StkMinsQfqCanonicalHistoryError(f"Unknown frozen batch: {batch_key}.")


def _one_minute_target_paths(
    scope_path: Path,
    *,
    duckdb_resource: DuckDBResource,
    lake_root: Path,
) -> tuple[Path, ...]:
    with duckdb_resource.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT DISTINCT ts_code, year
            FROM {read_parquet(scope_path, hive_partitioning=False)}
            ORDER BY ts_code, year
            """
        ).fetchall()
    return tuple(
        gold_stk_mins_qfq_path(lake_root, 1, str(ts_code), str(year))
        for ts_code, year in rows
    )


def _one_minute_scope_groups(
    plan: Mapping[str, Any],
    *,
    year: str,
    duckdb_resource: DuckDBResource,
) -> tuple[dict[str, Any], ...]:
    scope_path = Path(str(plan["affected_scope_manifest"]["path"]))
    with duckdb_resource.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT
              ts_code,
              year,
              list(strftime(trade_date, '%Y-%m-%d') ORDER BY trade_date),
              sum(tail_row_count)
            FROM {read_parquet(scope_path, hive_partitioning=False)}
            WHERE year = ?
            GROUP BY ts_code, year
            ORDER BY ts_code
            """,
            [year],
        ).fetchall()
    lake_root = Path(str(plan["lake_root"]))
    return tuple(
        {
            "ts_code": str(ts_code),
            "year": str(scope_year),
            "trade_dates": list(trade_dates),
            "tail_row_count": int(tail_row_count),
            "target_path": str(
                gold_stk_mins_qfq_path(
                    lake_root,
                    1,
                    str(ts_code),
                    str(scope_year),
                )
            ),
        }
        for ts_code, scope_year, trade_dates, tail_row_count in rows
    )


def _candidate_path(plan: Mapping[str, Any], formal_path: Path) -> Path:
    return Path(str(plan["candidate_lake_root"])) / formal_path.relative_to(
        Path(str(plan["lake_root"]))
    )


def _assert_plan_unchanged(plan: Mapping[str, Any]) -> None:
    if plan.get("should_stop") is not False:
        raise StkMinsQfqCanonicalHistoryError("The frozen plan is not green.")
    _assert_source_manifest_unchanged(plan)
    _assert_scope_manifest_unchanged(plan)
    _assert_as_of_snapshot_unchanged(plan)
    _assert_code_manifest_unchanged(plan)


def _assert_source_manifest_unchanged(plan: Mapping[str, Any]) -> None:
    lake_root = Path(str(plan["lake_root"]))
    for entry in plan["source_manifest"]:
        path = lake_root / str(entry["relative_path"])
        observed = _file_stat(path, root=lake_root)
        if observed != entry:
            raise StkMinsQfqCanonicalHistoryError(
                f"Frozen source file changed: {path}."
            )


def _assert_history_batch_sources_unchanged(
    plan: Mapping[str, Any], batch: StkMinsQfqHistoryBatch
) -> None:
    source_freq = {5: 1, 15: 5, 30: 5, 60: 30}[batch.freq]
    lake_root = Path(str(plan["lake_root"]))
    expected_by_path = {
        str(lake_root / str(entry["relative_path"])): entry
        for entry in plan["source_manifest"]
    }
    paths = [
        lake_root
        / (
            "silver/quote/stk_mins/"
            f"freq={source_freq}/trade_date={trade_date}/part-000.parquet"
        )
        for trade_date in batch.partition_keys
    ]
    paths.extend(
        silver_adj_factor_path(lake_root, trade_date)
        for trade_date in batch.partition_keys
    )
    for path in paths:
        expected = expected_by_path.get(str(path))
        if expected is None or _file_stat(path, root=lake_root) != expected:
            raise StkMinsQfqCanonicalHistoryError(
                f"Frozen source file changed for {_history_batch_key(batch)}: {path}."
            )


def _assert_as_of_snapshot_unchanged(plan: Mapping[str, Any]) -> None:
    manifest = plan["as_of_adj_factor_snapshot_manifest"]
    path = Path(str(manifest["path"]))
    if (
        not path.exists()
        or path.stat().st_size != int(manifest["size_bytes"])
        or _file_sha256(path) != manifest["sha256"]
    ):
        raise StkMinsQfqCanonicalHistoryError(
            f"Frozen as-of adj-factor snapshot changed: {path}."
        )


def _assert_code_manifest_unchanged(plan: Mapping[str, Any]) -> None:
    repo_root = _repository_root()
    for entry in plan["code_manifest"]:
        path = repo_root / str(entry["relative_path"])
        if _file_content_entry(path, root=repo_root) != entry:
            raise StkMinsQfqCanonicalHistoryError(
                f"Frozen rebuild code or LLD changed: {path}."
            )


def _assert_one_minute_formal_sources_unchanged(
    plan: Mapping[str, Any], scope_entries: Sequence[Mapping[str, Any]]
) -> None:
    lake_root = Path(str(plan["lake_root"]))
    expected_by_path = {
        str(lake_root / str(entry["relative_path"])): entry
        for entry in plan["one_minute_source_manifest"]
    }
    for entry in scope_entries:
        path = Path(str(entry["target_path"]))
        expected = expected_by_path[str(path)]
        if _file_content_entry(path, root=lake_root) != expected:
            raise StkMinsQfqCanonicalHistoryError(
                f"Frozen 1m Gold source changed: {path}."
            )


def _assert_scope_manifest_unchanged(plan: Mapping[str, Any]) -> None:
    manifest = plan["affected_scope_manifest"]
    path = Path(str(manifest["path"]))
    if (
        not path.exists()
        or path.stat().st_size != int(manifest["size_bytes"])
        or _file_sha256(path) != manifest["sha256"]
    ):
        raise StkMinsQfqCanonicalHistoryError(
            f"Frozen affected scope manifest changed: {path}."
        )


def _assert_candidate_entries_unchanged(
    entries: Sequence[Mapping[str, Any]],
) -> None:
    for entry in entries:
        _assert_candidate_entry_unchanged(entry)


def _assert_candidate_entry_unchanged(entry: Mapping[str, Any]) -> None:
    path = Path(str(entry["candidate_path"]))
    if (
        not path.exists()
        or path.stat().st_size != int(entry["candidate_size_bytes"])
        or _file_sha256(path) != entry["candidate_sha256"]
    ):
        raise StkMinsQfqCanonicalHistoryError(
            f"Candidate file is missing or changed: {path}."
        )


def _assert_formal_before_state(entry: Mapping[str, Any]) -> None:
    formal = Path(str(entry["formal_path"]))
    before = entry.get("formal_before")
    if before is None:
        if formal.exists():
            raise StkMinsQfqCanonicalHistoryError(
                f"A new formal target appeared after candidate build: {formal}."
            )
        return
    root = Path(str(before["root"]))
    if _file_content_entry(formal, root=root) != before:
        raise StkMinsQfqCanonicalHistoryError(
            f"Formal target changed after candidate build: {formal}."
        )


def _assert_promotable_entry_state(entry: Mapping[str, Any]) -> None:
    candidate = Path(str(entry["candidate_path"]))
    formal = Path(str(entry["formal_path"]))
    if candidate.exists():
        _assert_candidate_entry_unchanged(entry)
        _assert_formal_before_state(entry)
        return
    if formal.exists() and _file_sha256(formal) == entry["candidate_sha256"]:
        return
    raise StkMinsQfqCanonicalHistoryError(
        f"Candidate is missing and formal target is not promoted: {formal}."
    )


def _assert_formal_entries_match_candidates(
    entries: Sequence[Mapping[str, Any]],
) -> None:
    for entry in entries:
        formal = Path(str(entry["formal_path"]))
        if not formal.exists() or _file_sha256(formal) != entry["candidate_sha256"]:
            raise StkMinsQfqCanonicalHistoryError(
                f"Promoted formal file does not match its candidate: {formal}."
            )


def _load_candidate_manifest(
    path: Path, *, plan_hash: str, freq: int
) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "plan_hash": plan_hash,
            "freq": freq,
            "completed_batch_keys": [],
            "files": [],
        }
    payload = _load_json(path, label="candidate manifest")
    if payload.get("plan_hash") != plan_hash or payload.get("freq") != freq:
        raise StkMinsQfqCanonicalHistoryError(
            "Candidate manifest belongs to another plan or frequency."
        )
    return payload


def _write_candidate_manifest(
    path: Path,
    *,
    plan_hash: str,
    freq: int,
    completed: set[str],
    files: Sequence[Mapping[str, Any]],
) -> None:
    _atomic_json(
        path,
        {
            "schema_version": 1,
            "plan_hash": plan_hash,
            "freq": freq,
            "completed_batch_keys": sorted(completed),
            "files": sorted(files, key=lambda entry: str(entry["candidate_path"])),
        },
    )


def _load_promotion_checkpoint(
    path: Path, *, plan_hash: str, freq: int
) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "plan_hash": plan_hash,
            "freq": freq,
            "completed_batch_keys": [],
        }
    payload = _load_json(path, label="promotion checkpoint")
    if payload.get("plan_hash") != plan_hash or payload.get("freq") != freq:
        raise StkMinsQfqCanonicalHistoryError(
            "Promotion checkpoint belongs to another plan or frequency."
        )
    return payload


def _load_plan(path: Path, *, expected_plan_hash: str) -> dict[str, Any]:
    plan = _load_json(path, label="canonical rebuild plan")
    if (
        plan.get("schema_version") != PLAN_SCHEMA_VERSION
        or plan.get("report_type") != "stk_mins_qfq_canonical_history_plan"
        or plan.get("plan_hash") != expected_plan_hash
    ):
        raise StkMinsQfqCanonicalHistoryError(
            "Canonical rebuild plan identity is invalid."
        )
    return plan


def _assert_formal_roots(*, lake_root: Path, staging_root: Path) -> None:
    if (
        lake_root != Path(DEFAULT_LAKE_ROOT).resolve()
        and str(lake_root).startswith("/Volumes/")
    ):
        raise StkMinsQfqCanonicalHistoryError(
            "Formal QFQ rebuild must use /Volumes/datasource/data_lake."
        )
    if (
        staging_root != DEFAULT_REBUILD_STAGING_ROOT.resolve()
        and str(staging_root).startswith("/Volumes/")
    ):
        raise StkMinsQfqCanonicalHistoryError(
            "Formal QFQ rebuild must use the fixed P7 staging root."
        )
    staging_root.mkdir(parents=True, exist_ok=True)
    if lake_root.stat().st_dev != staging_root.stat().st_dev:
        raise StkMinsQfqCanonicalHistoryError(
            "Formal Lake and staging root must share a filesystem."
        )


def _code_contract_paths() -> tuple[Path, ...]:
    repo_root = _repository_root()
    return (
        Path(__file__).resolve(),
        repo_root
        / "lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_qfq_history.py",
        repo_root
        / "lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_qfq_derived_history.py",
        repo_root
        / "lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq.py",
        repo_root
        / "lake_console/orchestrator/src/orchestrator/defs/io/cn_a_gold_minute_bars.py",
        repo_root
        / "lake_console/orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py",
        repo_root
        / "lake_console/docs/design/dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md",
    )


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _file_stat(path: Path, *, root: Path) -> dict[str, Any]:
    if not path.exists():
        raise StkMinsQfqCanonicalHistoryError(f"Required file is missing: {path}.")
    stat = path.stat()
    return {
        "relative_path": str(path.relative_to(root)),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _file_content_entry(path: Path, *, root: Path) -> dict[str, Any]:
    entry = _file_stat(path, root=root)
    return {**entry, "root": str(root), "sha256": _file_sha256(path)}


def _optional_file_content_entry(path: Path, *, root: Path) -> dict[str, Any] | None:
    return _file_content_entry(path, root=root) if path.exists() else None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _row_count(path: Path, duckdb_resource: DuckDBResource) -> int:
    with duckdb_resource.connect() as connection:
        return int(
            connection.execute(
                f"SELECT count(*) FROM {read_parquet(path, hive_partitioning=False)}"
            ).fetchone()[0]
        )


def _read_paths(paths: Sequence[Path]) -> str:
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False)
    values = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{values}], hive_partitioning=false, union_by_name=true)"


def _chunks(values: Sequence[Path], size: int) -> Iterator[tuple[Path, ...]]:
    for index in range(0, len(values), size):
        yield tuple(values[index : index + size])


def _assert_batch_budget(batch_key: str, started_at: float) -> None:
    elapsed_seconds = perf_counter() - started_at
    if elapsed_seconds > MAX_BATCH_SECONDS:
        raise StkMinsQfqCanonicalHistoryError(
            f"Candidate batch exceeded {MAX_BATCH_SECONDS:.0f}s: "
            f"{batch_key} took {elapsed_seconds:.3f}s."
        )


def _normalize_rebuild_freq(freq: int) -> int:
    normalized = int(freq)
    if normalized not in CANONICAL_REBUILD_FREQS:
        raise StkMinsQfqCanonicalHistoryError(
            f"Canonical rebuild frequency is not allowed: {freq}."
        )
    return normalized


def _hash_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.exists():
        raise StkMinsQfqCanonicalHistoryError(f"{label} is missing: {path}.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StkMinsQfqCanonicalHistoryError(f"{label} must be a JSON object.")
    return payload


def _write_report(
    plan: Mapping[str, Any], name: str, report: Mapping[str, Any]
) -> Path:
    root = Path(str(plan.get("report_root", DEFAULT_REPORT_ROOT)))
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}_{plan['plan_hash']}.json"
    _atomic_json(path, report)
    return path


def _bounded_summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in plan.items()
        if key not in {
            "affected_scope",
            "source_manifest",
            "one_minute_source_manifest",
            "code_manifest",
            "selected_partition_keys",
            "batches",
        }
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "DEFAULT_REBUILD_STAGING_ROOT",
    "StkMinsQfqCanonicalHistoryError",
    "audit_stk_mins_qfq_canonical_candidates",
    "audit_stk_mins_qfq_canonical_formal",
    "audit_stk_mins_qfq_derived_equivalence_to_report",
    "build_stk_mins_qfq_canonical_candidates",
    "plan_stk_mins_qfq_canonical_history",
    "promote_stk_mins_qfq_canonical_candidates",
]
