"""Bounded recursive indicator recovery from the frozen BSE QFQ manifest."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    gold_stk_mins_qfq_nineturn_path,
)
from orchestrator.defs.qfq_nineturn import (
    GOLD_STK_MINS_QFQ_NINETURN_COLUMNS,
    build_gold_stk_mins_qfq_nineturn_select_sql,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
    GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMNS,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMNS,
    discover_gold_stk_mins_qfq_source_year_paths,
    write_gold_stk_mins_qfq_macd_kdj_rows,
)

RECURSIVE_SCHEMA_VERSION = 1
RECURSIVE_STAGE_NAME = "bse_recursive_indicator_recovery"
RECURSIVE_PLAN_FILE_NAME = "recursive-recovery-plan.json"
RECURSIVE_CANDIDATE_ROOT_NAME = "recursive-candidates"
RECURSIVE_CANDIDATE_CHECKPOINT_NAME = "recursive-candidate-checkpoint.json"
RECURSIVE_AUDIT_CHECKPOINT_NAME = "recursive-audit-checkpoint.json"
RECURSIVE_PROMOTE_CHECKPOINT_NAME = "recursive-promote-checkpoint.json"
RECURSIVE_CHANGED_MANIFEST_NAME = "actual-changed-recursive-manifest.json"
RECURSIVE_MAX_STAGE_SECONDS = 300.0
RECURSIVE_MIN_FREE_SPACE_BYTES = 20 * 1024**3
RECURSIVE_NINETURN_FREQS = (30, 60, 90, 120)


class BseRecursiveRecoveryError(RuntimeError):
    pass


def plan_bse_recursive_recovery(
    *,
    changed_qfq_manifest_path: Path,
    registered_partition_keys: Sequence[str],
    output_path: Path,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> dict[str, object]:
    """Freeze exact code-specific forward ranges without changing formal Gold."""

    started_at = perf_counter()
    manifest_path = changed_qfq_manifest_path.resolve()
    plan_root = manifest_path.parent
    lake_root = lake_root.resolve()
    _assert_staging_path(plan_root, lake_root=lake_root)
    manifest = _load_changed_qfq_manifest(manifest_path)
    registered_dates = _normalize_registered_dates(registered_partition_keys)
    frontier = registered_dates[-1]
    scopes = _scope_rows(manifest, frontier=frontier, registered_dates=registered_dates)
    macd_batches = _macd_batches(
        scopes=scopes,
        registered_dates=registered_dates,
        lake_root=lake_root,
    )
    nineturn_batches = _nineturn_batches(
        scopes=scopes,
        registered_dates=registered_dates,
        lake_root=lake_root,
    )

    target_specs = _target_specs(macd_batches=macd_batches, nineturn_batches=nineturn_batches)
    source_paths = sorted(
        {
            Path(path)
            for batch in (*macd_batches, *nineturn_batches)
            for path in batch["source_paths"]
        }
    )
    previous_state_paths = sorted(
        {
            Path(str(batch["previous_state_path"]))
            for batch in macd_batches
            if batch.get("previous_state_kind") == "formal"
        }
    )
    missing_paths = sorted(
        {
            str(path)
            for path in (*source_paths, *previous_state_paths)
            if not path.is_file()
        }
        | {
            str(spec["target_path"])
            for spec in target_specs
            if not Path(str(spec["target_path"])).is_file()
        }
    )
    source_fingerprints = [_required_file_fingerprint(path) for path in source_paths]
    previous_state_fingerprints = [
        _required_file_fingerprint(path) for path in previous_state_paths
    ]
    target_fingerprints = [
        {
            **spec,
            "target_fingerprint": _required_file_fingerprint(
                Path(str(spec["target_path"]))
            ),
        }
        for spec in target_specs
    ]
    estimated_candidate_bytes = sum(
        int(spec["target_fingerprint"]["size_bytes"])
        for spec in target_fingerprints
    )
    available_bytes = shutil.disk_usage(plan_root).free
    required_free_bytes = (
        estimated_candidate_bytes * 2 + RECURSIVE_MIN_FREE_SPACE_BYTES
    )
    same_filesystem = plan_root.stat().st_dev == lake_root.stat().st_dev
    code_fingerprints = [
        _content_fingerprint(path) for path in _recursive_contract_paths()
    ]
    frozen: dict[str, object] = {
        "schema_version": RECURSIVE_SCHEMA_VERSION,
        "stage": RECURSIVE_STAGE_NAME,
        "lake_root": str(lake_root),
        "plan_root": str(plan_root),
        "changed_qfq_manifest_path": str(manifest_path),
        "changed_qfq_manifest_hash": manifest["manifest_hash"],
        "registered_partition_keys": list(registered_dates),
        "registered_partition_hash": _hash_payload(registered_dates),
        "frontier_trade_date": frontier,
        "scopes": scopes,
        "macd_batches": macd_batches,
        "nineturn_batches": nineturn_batches,
        "source_fingerprints": source_fingerprints,
        "previous_state_fingerprints": previous_state_fingerprints,
        "target_fingerprints": target_fingerprints,
        "code_fingerprints": code_fingerprints,
        "estimated_candidate_bytes": estimated_candidate_bytes,
    }
    plan_hash = _hash_payload(frozen)
    should_stop = bool(missing_paths) or not same_filesystem or available_bytes < required_free_bytes
    stop_reason_code = None
    if missing_paths:
        stop_reason_code = "required_file_missing"
    elif not same_filesystem:
        stop_reason_code = "different_filesystem"
    elif available_bytes < required_free_bytes:
        stop_reason_code = "insufficient_staging_space"
    payload: dict[str, object] = {
        **frozen,
        "plan_hash": plan_hash,
        "scope_count": len(scopes),
        "macd_batch_count": len(macd_batches),
        "nineturn_partition_count": sum(
            len(batch["target_trade_dates"]) for batch in nineturn_batches
        ),
        "target_file_count": len(target_fingerprints),
        "missing_path_count": len(missing_paths),
        "missing_path_samples": missing_paths[:20],
        "available_bytes": available_bytes,
        "required_free_bytes": required_free_bytes,
        "same_filesystem": same_filesystem,
        "elapsed_seconds": round(perf_counter() - started_at, 3),
        "generated_at": _utc_now(),
        "should_stop": should_stop,
        "stop_reason_code": stop_reason_code,
        "write_counters": _zero_control_plane_writes(),
    }
    _atomic_write_json(plan_root / RECURSIVE_PLAN_FILE_NAME, payload)
    _atomic_write_json(output_path, payload)
    return payload


def build_bse_recursive_recovery_candidates(
    *,
    plan_path: Path,
    duckdb_resource: DuckDBResource,
    output_path: Path,
    confirm: bool,
    max_macd_batch_count: int | None = None,
    max_nineturn_date_count: int | None = None,
) -> dict[str, object]:
    """Build resumable MACD/KDJ, state and minute nine-turn candidates."""

    if not confirm:
        raise BseRecursiveRecoveryError("recursive candidate build requires confirmation")
    started_at = perf_counter()
    plan = _load_plan(plan_path)
    _assert_plan_unchanged(plan)
    checkpoint_path = Path(str(plan["plan_root"])) / RECURSIVE_CANDIDATE_CHECKPOINT_NAME
    checkpoint = _load_checkpoint(checkpoint_path, plan_hash=str(plan["plan_hash"]))
    completed_macd = set(checkpoint.get("completed_macd_batches", ()))
    completed_nineturn = set(checkpoint.get("completed_nineturn_partitions", ()))

    pending_macd = [
        batch
        for batch in plan["macd_batches"]
        if str(batch["batch_key"]) not in completed_macd
    ]
    if max_macd_batch_count is not None:
        if max_macd_batch_count <= 0:
            raise BseRecursiveRecoveryError("max_macd_batch_count must be positive")
        pending_macd = pending_macd[:max_macd_batch_count]
    for batch in pending_macd:
        batch_started = perf_counter()
        _build_macd_batch(plan=plan, batch=batch)
        if perf_counter() - batch_started > RECURSIVE_MAX_STAGE_SECONDS:
            raise BseRecursiveRecoveryError(
                f"MACD/KDJ candidate batch exceeded 300 seconds: {batch['batch_key']}"
            )
        completed_macd.add(str(batch["batch_key"]))
        _write_candidate_checkpoint(
            checkpoint_path,
            plan_hash=str(plan["plan_hash"]),
            completed_macd=completed_macd,
            completed_nineturn=completed_nineturn,
        )

    if len(completed_macd) == len(plan["macd_batches"]):
        remaining = None if max_nineturn_date_count is None else max_nineturn_date_count
        for batch in plan["nineturn_batches"]:
            pending_dates = [
                value
                for value in batch["target_trade_dates"]
                if _nineturn_partition_key(int(batch["freq"]), str(value))
                not in completed_nineturn
            ]
            if remaining is not None:
                if remaining <= 0:
                    break
                pending_dates = pending_dates[:remaining]
            if not pending_dates:
                continue
            batch_started = perf_counter()
            _build_nineturn_dates(
                plan=plan,
                batch=batch,
                target_trade_dates=pending_dates,
                duckdb_resource=duckdb_resource,
            )
            if perf_counter() - batch_started > RECURSIVE_MAX_STAGE_SECONDS:
                raise BseRecursiveRecoveryError(
                    f"nine-turn candidate batch exceeded 300 seconds: freq={batch['freq']}"
                )
            completed_nineturn.update(
                _nineturn_partition_key(int(batch["freq"]), str(value))
                for value in pending_dates
            )
            _write_candidate_checkpoint(
                checkpoint_path,
                plan_hash=str(plan["plan_hash"]),
                completed_macd=completed_macd,
                completed_nineturn=completed_nineturn,
            )
            if remaining is not None:
                remaining -= len(pending_dates)

    expected_nineturn = {
        _nineturn_partition_key(int(batch["freq"]), str(value))
        for batch in plan["nineturn_batches"]
        for value in batch["target_trade_dates"]
    }
    complete = (
        len(completed_macd) == len(plan["macd_batches"])
        and completed_nineturn == expected_nineturn
    )
    candidate_files = _candidate_file_rows(plan) if complete else []
    frozen: dict[str, object] = {
        "schema_version": RECURSIVE_SCHEMA_VERSION,
        "stage": "recursive_candidate_build",
        "plan_hash": plan["plan_hash"],
        "completed_macd_batch_count": len(completed_macd),
        "planned_macd_batch_count": len(plan["macd_batches"]),
        "completed_nineturn_partition_count": len(completed_nineturn),
        "planned_nineturn_partition_count": len(expected_nineturn),
        "candidate_file_count": len(candidate_files),
        "candidate_files": candidate_files,
        "complete": complete,
    }
    payload = {
        **frozen,
        "candidate_report_hash": _hash_payload(frozen),
        "elapsed_seconds": round(perf_counter() - started_at, 3),
        "generated_at": _utc_now(),
        "should_stop": not complete,
        "write_counters": _zero_control_plane_writes(),
    }
    _atomic_write_json(output_path, payload)
    return payload


def audit_bse_recursive_recovery_candidates(
    *,
    plan_path: Path,
    candidate_report_path: Path,
    duckdb_resource: DuckDBResource,
    output_path: Path,
    max_candidate_count: int | None = None,
) -> dict[str, object]:
    """Audit candidate contracts and exact non-target preservation."""

    started_at = perf_counter()
    plan = _load_plan(plan_path)
    _assert_plan_unchanged(plan)
    report = _load_candidate_report(candidate_report_path, plan=plan)
    checkpoint_path = Path(str(plan["plan_root"])) / RECURSIVE_AUDIT_CHECKPOINT_NAME
    checkpoint = _load_checkpoint(checkpoint_path, plan_hash=str(plan["plan_hash"]))
    audited = list(checkpoint.get("audited_files", ()))
    completed = {str(row["target_path"]) for row in audited}
    pending = [
        row for row in report["candidate_files"] if str(row["target_path"]) not in completed
    ]
    if max_candidate_count is not None:
        if max_candidate_count <= 0:
            raise BseRecursiveRecoveryError("max_candidate_count must be positive")
        pending = pending[:max_candidate_count]
    failures: list[dict[str, object]] = []
    with duckdb_resource.connect() as connection:
        for row in pending:
            if perf_counter() - started_at > RECURSIVE_MAX_STAGE_SECONDS:
                break
            try:
                audited_row = _audit_candidate(connection, plan=plan, row=row)
                audited.append(audited_row)
                _atomic_write_json(
                    checkpoint_path,
                    {
                        "plan_hash": plan["plan_hash"],
                        "candidate_report_hash": report["candidate_report_hash"],
                        "audited_files": audited,
                    },
                )
            except Exception as error:  # noqa: BLE001 - bounded diagnostics.
                failures.append(
                    {
                        "target_path": row.get("target_path"),
                        "error_type": type(error).__name__,
                        "reason": str(error)[:500],
                    }
                )
                break
    complete = len(audited) == len(report["candidate_files"]) and not failures
    changed = [row for row in audited if row["change_status"] == "changed"]
    no_op = [row for row in audited if row["change_status"] == "no_op"]
    frozen = {
        "schema_version": RECURSIVE_SCHEMA_VERSION,
        "stage": "recursive_candidate_audit",
        "plan_hash": plan["plan_hash"],
        "candidate_report_hash": report["candidate_report_hash"],
        "audited_file_count": len(audited),
        "candidate_file_count": len(report["candidate_files"]),
        "changed_file_count": len(changed),
        "no_op_file_count": len(no_op),
        "audited_files": audited,
        "failure_samples": failures[:20],
        "complete": complete,
    }
    payload = {
        **frozen,
        "audit_hash": _hash_payload(frozen),
        "elapsed_seconds": round(perf_counter() - started_at, 3),
        "generated_at": _utc_now(),
        "should_stop": not complete,
        "write_counters": _zero_control_plane_writes(),
    }
    _atomic_write_json(output_path, payload)
    return payload


def promote_bse_recursive_recovery_candidates(
    *,
    plan_path: Path,
    candidate_report_path: Path,
    audit_report_path: Path,
    checkpoint_path: Path,
    changed_manifest_path: Path,
    output_path: Path,
    confirm: bool,
) -> dict[str, object]:
    """Atomically promote only logically changed audited candidates."""

    if not confirm:
        raise BseRecursiveRecoveryError("recursive promotion requires confirmation")
    started_at = perf_counter()
    plan = _load_plan(plan_path)
    _assert_plan_inputs_unchanged(plan)
    report = _load_candidate_report(candidate_report_path, plan=plan)
    audit = _load_audit_report(audit_report_path, plan=plan, report=report)
    checkpoint = _load_checkpoint(checkpoint_path, plan_hash=str(plan["plan_hash"]))
    promoted = list(checkpoint.get("promoted_files", ()))
    completed = {str(row["target_path"]) for row in promoted}
    changed_rows = [
        row for row in audit["audited_files"] if row["change_status"] == "changed"
    ]
    in_progress = checkpoint.get("in_progress")
    if isinstance(in_progress, dict):
        matching = next(
            (
                row
                for row in changed_rows
                if str(row["target_path"]) == str(in_progress.get("target_path"))
            ),
            None,
        )
        if matching is None:
            raise BseRecursiveRecoveryError("interrupted promotion escaped audit scope")
        candidate = Path(str(matching["candidate_path"]))
        target = Path(str(matching["target_path"]))
        expected_sha = str(matching["candidate_sha256"])
        if not candidate.exists() and target.is_file() and _sha256_file(target) == expected_sha:
            if str(target) not in completed:
                promoted.append(_promoted_row(matching))
                completed.add(str(target))
            _atomic_write_json(
                checkpoint_path,
                {
                    "plan_hash": plan["plan_hash"],
                    "audit_hash": audit["audit_hash"],
                    "promoted_files": promoted,
                    "in_progress": None,
                },
            )
        elif not candidate.is_file():
            raise BseRecursiveRecoveryError("ambiguous interrupted recursive promotion")
    for row in changed_rows:
        target_path = str(row["target_path"])
        if target_path in completed:
            _assert_promoted(row)
            continue
        target = Path(target_path)
        candidate = Path(str(row["candidate_path"]))
        if _fingerprint(target) != row["target_fingerprint"]:
            raise BseRecursiveRecoveryError(f"formal recursive target changed: {target}")
        if not candidate.is_file() or _sha256_file(candidate) != row["candidate_sha256"]:
            raise BseRecursiveRecoveryError(f"recursive candidate changed: {candidate}")
        _atomic_write_json(
            checkpoint_path,
            {
                "plan_hash": plan["plan_hash"],
                "audit_hash": audit["audit_hash"],
                "promoted_files": promoted,
                "in_progress": {
                    "target_path": target_path,
                    "candidate_path": str(candidate),
                    "candidate_sha256": row["candidate_sha256"],
                },
            },
        )
        os.replace(candidate, target)
        if _sha256_file(target) != row["candidate_sha256"]:
            raise BseRecursiveRecoveryError(f"promoted recursive hash mismatch: {target}")
        promoted_row = _promoted_row(row)
        promoted.append(promoted_row)
        completed.add(target_path)
        _atomic_write_json(
            checkpoint_path,
            {
                "plan_hash": plan["plan_hash"],
                "audit_hash": audit["audit_hash"],
                "promoted_files": promoted,
                "in_progress": None,
            },
        )

    for row in audit["audited_files"]:
        candidate = Path(str(row["candidate_path"]))
        if row["change_status"] == "no_op":
            candidate.unlink(missing_ok=True)
    changed_manifest = _changed_manifest(plan=plan, audit=audit, promoted=promoted)
    _atomic_write_json(changed_manifest_path, changed_manifest)
    candidate_root = _candidate_root(plan)
    if candidate_root.exists() and not any(candidate_root.rglob("*.parquet")):
        shutil.rmtree(candidate_root)
    frozen = {
        "schema_version": RECURSIVE_SCHEMA_VERSION,
        "stage": "recursive_promote",
        "plan_hash": plan["plan_hash"],
        "audit_hash": audit["audit_hash"],
        "promoted_file_count": len(promoted),
        "no_op_file_count": int(audit["no_op_file_count"]),
        "changed_manifest_hash": changed_manifest["manifest_hash"],
    }
    payload = {
        **frozen,
        "promote_hash": _hash_payload(frozen),
        "changed_manifest_path": str(changed_manifest_path),
        "elapsed_seconds": round(perf_counter() - started_at, 3),
        "generated_at": _utc_now(),
        "should_stop": False,
        "write_counters": _zero_control_plane_writes(),
    }
    _atomic_write_json(output_path, payload)
    return payload


def _scope_rows(
    manifest: Mapping[str, object], *, frontier: str, registered_dates: Sequence[str]
) -> list[dict[str, object]]:
    registered = set(registered_dates)
    rows: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    for row in manifest["changed_qfq_rows"]:
        freq = int(row["freq"])
        ts_code = str(row["ts_code"])
        start = date.fromisoformat(str(row["earliest_changed_trade_date"])).isoformat()
        key = (freq, ts_code)
        if key in seen:
            raise BseRecursiveRecoveryError(f"duplicate QFQ manifest scope: {key}")
        if start not in registered or start > frontier:
            raise BseRecursiveRecoveryError(f"QFQ scope is outside registered dates: {key}")
        seen.add(key)
        rows.append(
            {
                "freq": freq,
                "ts_code": ts_code,
                "start_trade_date": start,
                "end_trade_date": frontier,
            }
        )
    return sorted(rows, key=lambda value: (value["freq"], value["ts_code"]))


def _macd_batches(*, scopes, registered_dates, lake_root: Path) -> list[dict[str, object]]:
    codes_by_freq_start: dict[tuple[int, str], list[str]] = defaultdict(list)
    for row in scopes:
        codes_by_freq_start[(int(row["freq"]), str(row["start_trade_date"]))].append(
            str(row["ts_code"])
        )
    date_index = {value: index for index, value in enumerate(registered_dates)}
    batches: list[dict[str, object]] = []
    for (freq, start), codes in sorted(codes_by_freq_start.items()):
        target_dates = [value for value in registered_dates if value >= start]
        for year in sorted({value[:4] for value in target_dates}):
            year_dates = [value for value in target_dates if value.startswith(year)]
            first_date = year_dates[0]
            previous_index = date_index[first_date] - 1
            previous_date = registered_dates[previous_index] if previous_index >= 0 else None
            source_paths = discover_gold_stk_mins_qfq_source_year_paths(
                lake_root,
                freq=freq,
                trade_dates=year_dates,
                stock_codes=codes,
            )
            indicator_paths = [
                gold_stk_mins_qfq_macd_kdj_path(lake_root, freq, code, year)
                for code in sorted(codes)
                if any(
                    path.parts[-3] == f"ts_code={code}" and path.parts[-2] == f"year={year}"
                    for path in source_paths
                )
            ]
            previous_state_path = (
                gold_stk_mins_qfq_macd_kdj_state_path(lake_root, freq, previous_date)
                if previous_date is not None
                else None
            )
            batches.append(
                {
                    "batch_key": f"macd:{freq}:{start}:{year}",
                    "freq": freq,
                    "start_trade_date": start,
                    "year": year,
                    "stock_codes": sorted(codes),
                    "target_trade_dates": year_dates,
                    "source_paths": [str(path) for path in source_paths],
                    "indicator_target_paths": [str(path) for path in indicator_paths],
                    "state_target_paths": [
                        str(gold_stk_mins_qfq_macd_kdj_state_path(lake_root, freq, value))
                        for value in year_dates
                    ],
                    "previous_state_path": str(previous_state_path) if previous_state_path else None,
                    "previous_state_kind": "formal" if year == start[:4] else "candidate",
                }
            )
    return batches


def _nineturn_batches(*, scopes, registered_dates, lake_root: Path) -> list[dict[str, object]]:
    rows_by_freq: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in scopes:
        if int(row["freq"]) in RECURSIVE_NINETURN_FREQS:
            rows_by_freq[int(row["freq"])].append(row)
    batches: list[dict[str, object]] = []
    for freq, rows in sorted(rows_by_freq.items()):
        start = min(str(row["start_trade_date"]) for row in rows)
        target_dates = [value for value in registered_dates if value >= start]
        source_paths = sorted(
            path
            for row in rows
            for path in (
                lake_root
                / "gold"
                / "quote"
                / "stk_mins_qfq"
                / f"freq={freq}"
                / f"ts_code={row['ts_code']}"
            ).glob("year=*/part-000.parquet")
        )
        batches.append(
            {
                "batch_key": f"nineturn:{freq}:{start}",
                "freq": freq,
                "start_trade_date": start,
                "stock_code_starts": [
                    {
                        "ts_code": str(row["ts_code"]),
                        "start_trade_date": str(row["start_trade_date"]),
                    }
                    for row in sorted(rows, key=lambda value: str(value["ts_code"]))
                ],
                "source_paths": [str(path) for path in sorted(set(source_paths))],
                "target_trade_dates": target_dates,
                "target_paths": [
                    str(gold_stk_mins_qfq_nineturn_path(lake_root, freq, value))
                    for value in target_dates
                ],
            }
        )
    return batches


def _target_specs(*, macd_batches, nineturn_batches) -> list[dict[str, object]]:
    specs: dict[str, dict[str, object]] = {}
    for batch in macd_batches:
        for path in batch["indicator_target_paths"]:
            value = Path(path)
            code = value.parts[-3].removeprefix("ts_code=")
            year = value.parts[-2].removeprefix("year=")
            specs[str(value)] = {
                "asset_family": "macd_kdj",
                "freq": int(batch["freq"]),
                "ts_code": code,
                "year": year,
                "trade_date": None,
                "target_path": str(value),
            }
        for path in batch["state_target_paths"]:
            value = Path(path)
            trade_date = value.parent.name.removeprefix("trade_date=")
            specs[str(value)] = {
                "asset_family": "macd_kdj_state",
                "freq": int(batch["freq"]),
                "ts_code": None,
                "year": None,
                "trade_date": trade_date,
                "target_path": str(value),
            }
    for batch in nineturn_batches:
        for path in batch["target_paths"]:
            value = Path(path)
            trade_date = value.parent.name.removeprefix("trade_date=")
            specs[str(value)] = {
                "asset_family": "nineturn",
                "freq": int(batch["freq"]),
                "ts_code": None,
                "year": None,
                "trade_date": trade_date,
                "target_path": str(value),
            }
    return [specs[key] for key in sorted(specs)]


def _build_macd_batch(*, plan: Mapping[str, object], batch: Mapping[str, object]) -> None:
    for path in (*batch["indicator_target_paths"], *batch["state_target_paths"]):
        _seed_candidate(plan, Path(str(path)))
    previous_path: Path | None = None
    if batch.get("previous_state_path"):
        formal_previous = Path(str(batch["previous_state_path"]))
        previous_path = (
            _candidate_path(plan, formal_previous)
            if batch["previous_state_kind"] == "candidate"
            else formal_previous
        )
        if not previous_path.is_file():
            raise BseRecursiveRecoveryError(f"exact previous state is missing: {previous_path}")
    indicator_results, state_results, _ = write_gold_stk_mins_qfq_macd_kdj_rows(
        lake_root=_candidate_root(plan),
        freq=int(batch["freq"]),
        source_qfq_paths=[Path(str(value)) for value in batch["source_paths"]],
        target_trade_dates=[str(value) for value in batch["target_trade_dates"]],
        previous_state_paths=(previous_path,) if previous_path is not None else (),
        stock_codes=[str(value) for value in batch["stock_codes"]],
        fail_if_target_exists=False,
    )
    expected_indicator = {str(_candidate_path(plan, Path(str(value)))) for value in batch["indicator_target_paths"]}
    observed_indicator = {str(result.path) for result in indicator_results}
    if observed_indicator != expected_indicator:
        raise BseRecursiveRecoveryError(
            f"MACD/KDJ candidate file set mismatch: {batch['batch_key']}"
        )
    if len(state_results) != len(batch["target_trade_dates"]):
        raise BseRecursiveRecoveryError(
            f"state candidate count mismatch: {batch['batch_key']}"
        )


def _build_nineturn_dates(
    *,
    plan: Mapping[str, object],
    batch: Mapping[str, object],
    target_trade_dates: Sequence[str],
    duckdb_resource: DuckDBResource,
) -> None:
    freq = int(batch["freq"])
    codes = [str(row["ts_code"]) for row in batch["stock_code_starts"]]
    source_paths = [Path(str(value)) for value in batch["source_paths"]]
    if not source_paths:
        raise BseRecursiveRecoveryError(f"nine-turn source is missing: freq={freq}")
    values = ", ".join(
        f"({duckdb_string(str(row['ts_code']))}, DATE {duckdb_string(str(row['start_trade_date']))})"
        for row in batch["stock_code_starts"]
    )
    columns = ", ".join(GOLD_STK_MINS_QFQ_NINETURN_COLUMNS)
    full_sql = build_gold_stk_mins_qfq_nineturn_select_sql(
        source_paths=source_paths,
        freq=freq,
        stock_codes=codes,
    )
    with duckdb_resource.connect() as connection:
        connection.execute(f"CREATE TEMP TABLE recursive_nineturn_all AS {full_sql}")
        connection.execute(
            "CREATE TEMP TABLE recursive_nineturn_scope AS "
            f"SELECT * FROM (VALUES {values}) AS scope(ts_code, start_trade_date)"
        )
        for trade_date in target_trade_dates:
            target = gold_stk_mins_qfq_nineturn_path(
                Path(str(plan["lake_root"])), freq, trade_date
            )
            candidate = _candidate_path(plan, target)
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.unlink(missing_ok=True)
            connection.execute(
                copy_query_to_parquet(
                    f"""
                    WITH impacted AS (
                      SELECT ts_code FROM recursive_nineturn_scope
                      WHERE start_trade_date <= DATE {duckdb_string(trade_date)}
                    )
                    SELECT {columns}
                    FROM (
                      SELECT {columns}
                      FROM {read_parquet(target, hive_partitioning=False)} AS existing
                      WHERE NOT EXISTS (
                        SELECT 1 FROM impacted WHERE impacted.ts_code = existing.ts_code
                      )
                      UNION ALL
                      SELECT {columns}
                      FROM recursive_nineturn_all AS replacement
                      WHERE replacement.trade_date = DATE {duckdb_string(trade_date)}
                        AND EXISTS (
                          SELECT 1 FROM impacted WHERE impacted.ts_code = replacement.ts_code
                        )
                    )
                    ORDER BY ts_code, trade_time
                    """,
                    candidate,
                )
            )
            _assert_file_contract(
                connection,
                path=candidate,
                asset_family="nineturn",
                freq=freq,
                trade_date=trade_date,
                ts_code=None,
                year=None,
            )


def _candidate_file_rows(plan: Mapping[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for spec in plan["target_fingerprints"]:
        target = Path(str(spec["target_path"]))
        candidate = _candidate_path(plan, target)
        if not candidate.is_file():
            raise BseRecursiveRecoveryError(f"recursive candidate is missing: {candidate}")
        rows.append(
            {
                "asset_family": spec["asset_family"],
                "freq": spec["freq"],
                "trade_date": spec["trade_date"],
                "ts_code": spec["ts_code"],
                "year": spec["year"],
                "target_path": str(target),
                "target_fingerprint": spec["target_fingerprint"],
                "candidate_path": str(candidate),
                "candidate_sha256": _sha256_file(candidate),
                "candidate_size_bytes": candidate.stat().st_size,
            }
        )
    return rows


def _audit_candidate(connection, *, plan, row) -> dict[str, object]:
    target = Path(str(row["target_path"]))
    candidate = Path(str(row["candidate_path"]))
    if _fingerprint(target) != row["target_fingerprint"]:
        raise BseRecursiveRecoveryError(f"formal target changed: {target}")
    if not candidate.is_file() or _sha256_file(candidate) != row["candidate_sha256"]:
        raise BseRecursiveRecoveryError(f"candidate changed: {candidate}")
    family = str(row["asset_family"])
    freq = int(row["freq"])
    _assert_file_contract(
        connection,
        path=candidate,
        asset_family=family,
        freq=freq,
        trade_date=str(row["trade_date"]) if row.get("trade_date") else None,
        ts_code=str(row["ts_code"]) if row.get("ts_code") else None,
        year=str(row["year"]) if row.get("year") else None,
    )
    scopes = [
        scope
        for scope in plan["scopes"]
        if int(scope["freq"]) == freq
        and (row.get("ts_code") is None or scope["ts_code"] == row["ts_code"])
    ]
    impacted = [
        str(scope["ts_code"])
        for scope in scopes
        if row.get("trade_date") is None
        or str(scope["start_trade_date"]) <= str(row["trade_date"])
    ]
    start_by_code = {str(scope["ts_code"]): str(scope["start_trade_date"]) for scope in scopes}
    old_non_target = _non_target_signature(
        connection,
        path=target,
        family=family,
        impacted_codes=impacted,
        start_by_code=start_by_code,
    )
    new_non_target = _non_target_signature(
        connection,
        path=candidate,
        family=family,
        impacted_codes=impacted,
        start_by_code=start_by_code,
    )
    if old_non_target != new_non_target:
        raise BseRecursiveRecoveryError(f"candidate changed non-target rows: {candidate}")
    changed_row_count, changed_dates = _changed_rows(
        connection, target=target, candidate=candidate, family=family
    )
    recent_dates = sorted(
        set(changed_dates).intersection(plan["registered_partition_keys"][-20:])
    )
    return {
        **row,
        "change_status": "changed" if changed_row_count else "no_op",
        "changed_row_count": changed_row_count,
        "earliest_changed_trade_date": min(changed_dates) if changed_dates else None,
        "latest_changed_trade_date": max(changed_dates) if changed_dates else None,
        "recent_changed_trade_dates": recent_dates,
        "non_target_signature": old_non_target,
    }


def _assert_file_contract(
    connection,
    *,
    path: Path,
    asset_family: str,
    freq: int,
    trade_date: str | None,
    ts_code: str | None,
    year: str | None,
) -> None:
    schema, key_columns = _contract(asset_family)
    relation = read_parquet(path, hive_partitioning=False)
    observed = tuple(
        (str(value[0]), str(value[1]).upper())
        for value in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    )
    expected = tuple((column.name, column.type) for column in schema)
    if observed != expected:
        raise BseRecursiveRecoveryError(f"recursive candidate schema mismatch: {path}")
    identity = [f"freq <> {freq}"]
    if trade_date is not None:
        identity.append(f"trade_date <> DATE {duckdb_string(trade_date)}")
    if ts_code is not None:
        identity.append(f"ts_code <> {duckdb_string(ts_code)}")
    if year is not None:
        identity.append(f"strftime(trade_date, '%Y') <> {duckdb_string(year)}")
    key_sql = ", ".join(key_columns)
    row = connection.execute(
        f"""
        SELECT count(*),
          count(*) FILTER (WHERE {' OR '.join(identity)}),
          count(*) - count(DISTINCT ({key_sql}))
        FROM {relation}
        """
    ).fetchone()
    if int(row[0]) <= 0 or int(row[1]) or int(row[2]):
        raise BseRecursiveRecoveryError(f"recursive candidate contract failed: {path}: {row}")
    if asset_family == "macd_kdj":
        domain_count = int(
            connection.execute(
                f"""
                SELECT count(*) FROM {relation}
                WHERE NOT isfinite(macd_dif_qfq)
                   OR NOT isfinite(macd_dea_qfq)
                   OR NOT isfinite(macd_qfq)
                   OR NOT isfinite(kdj_k_qfq)
                   OR NOT isfinite(kdj_d_qfq)
                   OR NOT isfinite(kdj_qfq)
                   OR params_key <> 'macd_12_26_9__kdj_9_3_3'
                   OR indicator_version <> 1
                """
            ).fetchone()[0]
        )
    elif asset_family == "macd_kdj_state":
        domain_count = int(
            connection.execute(
                f"""
                SELECT count(*) FROM {relation}
                WHERE NOT isfinite(macd_ema_fast)
                   OR NOT isfinite(macd_ema_slow)
                   OR NOT isfinite(macd_dea)
                   OR NOT isfinite(kdj_k)
                   OR NOT isfinite(kdj_d)
                   OR params_key <> 'macd_12_26_9__kdj_9_3_3'
                   OR indicator_version <> 1
                """
            ).fetchone()[0]
        )
    else:
        domain_count = int(
            connection.execute(
                f"""
                SELECT count(*) FROM {relation}
                WHERE up_count IS NULL OR down_count IS NULL
                   OR up_count < 0 OR down_count < 0
                   OR (up_count > 0 AND down_count > 0)
                   OR (nine_up_turn IS NOT NULL AND nine_up_turn <> '+9')
                   OR (nine_down_turn IS NOT NULL AND nine_down_turn <> '-9')
                   OR (nine_up_turn = '+9' AND up_count < 9)
                   OR (nine_down_turn = '-9' AND down_count < 9)
                   OR (nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL)
                """
            ).fetchone()[0]
        )
    if domain_count:
        raise BseRecursiveRecoveryError(
            f"recursive candidate domain failed: {path}: {domain_count}"
        )


def _contract(asset_family: str):
    if asset_family == "macd_kdj":
        return GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA, ("ts_code", "freq", "trade_time")
    if asset_family == "macd_kdj_state":
        return GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA, ("ts_code", "freq", "trade_date")
    if asset_family == "nineturn":
        return GOLD_STK_MINS_QFQ_NINETURN_SCHEMA, ("ts_code", "freq", "trade_time")
    raise BseRecursiveRecoveryError(f"unknown recursive asset family: {asset_family}")


def _columns(asset_family: str) -> tuple[str, ...]:
    if asset_family == "macd_kdj":
        return GOLD_STK_MINS_QFQ_MACD_KDJ_COLUMNS
    if asset_family == "macd_kdj_state":
        return GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_COLUMNS
    if asset_family == "nineturn":
        return GOLD_STK_MINS_QFQ_NINETURN_COLUMNS
    raise BseRecursiveRecoveryError(f"unknown recursive asset family: {asset_family}")


def _non_target_signature(
    connection,
    *,
    path: Path,
    family: str,
    impacted_codes: Sequence[str],
    start_by_code: Mapping[str, str],
) -> str:
    if family == "macd_kdj":
        code = next(iter(start_by_code))
        predicate = f"trade_date < DATE {duckdb_string(start_by_code[code])}"
    else:
        if not impacted_codes:
            predicate = "true"
        else:
            values = ", ".join(duckdb_string(value) for value in impacted_codes)
            predicate = f"ts_code NOT IN ({values})"
    return _logical_signature(connection, path=path, columns=_columns(family), predicate=predicate)


def _logical_signature(connection, *, path: Path, columns, predicate: str = "true") -> str:
    column_sql = ", ".join(f'"{value}"' for value in columns)
    row = connection.execute(
        f"""
        SELECT count(*),
          coalesce(sum(CAST(hash({column_sql}) AS HUGEINT)), 0),
          coalesce(bit_xor(hash({column_sql})), 0)
        FROM {read_parquet(path, hive_partitioning=False)}
        WHERE {predicate}
        """
    ).fetchone()
    return _hash_payload(
        {"row_count": int(row[0]), "hash_sum": str(row[1]), "hash_xor": str(row[2])}
    )


def _changed_rows(connection, *, target: Path, candidate: Path, family: str):
    columns = _columns(family)
    _, key_columns = _contract(family)
    compare_columns = [value for value in columns if value not in key_columns]
    join_sql = " AND ".join(f'old."{value}" = new."{value}"' for value in key_columns)
    changed_sql = " OR ".join(
        f'old."{value}" IS DISTINCT FROM new."{value}"' for value in compare_columns
    )
    row = connection.execute(
        f"""
        WITH old AS (
          SELECT *, true AS present FROM {read_parquet(target, hive_partitioning=False)}
        ), new AS (
          SELECT *, true AS present FROM {read_parquet(candidate, hive_partitioning=False)}
        ), changed AS (
          SELECT coalesce(old.trade_date, new.trade_date) AS trade_date
          FROM old FULL OUTER JOIN new ON {join_sql}
          WHERE old.present IS NULL OR new.present IS NULL OR {changed_sql}
        )
        SELECT count(*), list(DISTINCT strftime(trade_date, '%Y-%m-%d') ORDER BY strftime(trade_date, '%Y-%m-%d'))
        FROM changed
        """
    ).fetchone()
    return int(row[0]), [str(value) for value in (row[1] or ())]


def _changed_manifest(*, plan, audit, promoted):
    recent_by_family: dict[str, set[str]] = defaultdict(set)
    for row in promoted:
        recent_by_family[str(row["asset_family"])].update(row["recent_changed_trade_dates"])
    frozen = {
        "schema_version": RECURSIVE_SCHEMA_VERSION,
        "stage": "actual_changed_recursive_manifest",
        "plan_hash": plan["plan_hash"],
        "audit_hash": audit["audit_hash"],
        "changed_file_count": len(promoted),
        "changed_row_count": sum(int(row["changed_row_count"]) for row in promoted),
        "changed_files": promoted,
        "recent_changed_trade_dates_by_family": {
            key: sorted(values) for key, values in sorted(recent_by_family.items())
        },
    }
    return {
        **frozen,
        "manifest_hash": _hash_payload(frozen),
        "generated_at": _utc_now(),
        "should_stop": False,
    }


def _seed_candidate(plan: Mapping[str, object], target: Path) -> Path:
    candidate = _candidate_path(plan, target)
    if candidate.exists():
        return candidate
    candidate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, candidate)
    return candidate


def _candidate_root(plan: Mapping[str, object]) -> Path:
    return Path(str(plan["plan_root"])) / RECURSIVE_CANDIDATE_ROOT_NAME


def _candidate_path(plan: Mapping[str, object], target: Path) -> Path:
    return _candidate_root(plan) / target.relative_to(Path(str(plan["lake_root"])))


def _nineturn_partition_key(freq: int, trade_date: str) -> str:
    return f"nineturn:{freq}:{trade_date}"


def _normalize_registered_dates(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({date.fromisoformat(str(value)).isoformat() for value in values}))
    if not normalized:
        raise BseRecursiveRecoveryError("registered partition set is empty")
    return normalized


def _load_changed_qfq_manifest(path: Path) -> dict[str, object]:
    payload = _read_json(path)
    if payload.get("stage") != "r3_actual_changed_qfq_manifest":
        raise BseRecursiveRecoveryError("unexpected changed QFQ manifest stage")
    if payload.get("should_stop") is not False:
        raise BseRecursiveRecoveryError("changed QFQ manifest is not green")
    frozen = {
        key: value
        for key, value in payload.items()
        if key not in {"manifest_hash", "generated_at", "should_stop"}
    }
    if _hash_payload(frozen) != payload.get("manifest_hash"):
        raise BseRecursiveRecoveryError("changed QFQ manifest hash mismatch")
    rows = payload.get("changed_qfq_rows")
    if not isinstance(rows, list) or len(rows) != int(payload.get("changed_code_freq_count", -1)):
        raise BseRecursiveRecoveryError("changed QFQ manifest rows are incomplete")
    return payload


def _load_plan(path: Path) -> dict[str, object]:
    payload = _read_json(path)
    if payload.get("stage") != RECURSIVE_STAGE_NAME or payload.get("should_stop") is not False:
        raise BseRecursiveRecoveryError("recursive plan is not green")
    frozen_keys = {
        "schema_version", "stage", "lake_root", "plan_root",
        "changed_qfq_manifest_path", "changed_qfq_manifest_hash",
        "registered_partition_keys", "registered_partition_hash", "frontier_trade_date",
        "scopes", "macd_batches", "nineturn_batches", "source_fingerprints",
        "previous_state_fingerprints", "target_fingerprints", "code_fingerprints",
        "estimated_candidate_bytes",
    }
    frozen = {key: payload[key] for key in frozen_keys}
    if _hash_payload(frozen) != payload.get("plan_hash"):
        raise BseRecursiveRecoveryError("recursive plan hash mismatch")
    return payload


def _assert_plan_unchanged(plan: Mapping[str, object]) -> None:
    _assert_plan_inputs_unchanged(plan)
    for spec in plan["target_fingerprints"]:
        _assert_fingerprint(spec["target_fingerprint"])


def _assert_plan_inputs_unchanged(plan: Mapping[str, object]) -> None:
    manifest = _load_changed_qfq_manifest(Path(str(plan["changed_qfq_manifest_path"])))
    if manifest["manifest_hash"] != plan["changed_qfq_manifest_hash"]:
        raise BseRecursiveRecoveryError("changed QFQ manifest identity changed")
    for entry in (
        *plan["source_fingerprints"],
        *plan["previous_state_fingerprints"],
        *plan["code_fingerprints"],
    ):
        _assert_fingerprint(entry)


def _promoted_row(row: Mapping[str, object]) -> dict[str, object]:
    return {
        key: row[key]
        for key in (
            "target_path",
            "candidate_sha256",
            "asset_family",
            "freq",
            "trade_date",
            "ts_code",
            "year",
            "changed_row_count",
            "earliest_changed_trade_date",
            "latest_changed_trade_date",
            "recent_changed_trade_dates",
        )
    }


def _assert_fingerprint(entry: Mapping[str, object]) -> None:
    path = Path(str(entry["path"]))
    expected = {
        "path": str(entry["path"]),
        "exists": bool(entry["exists"]),
        "size_bytes": int(entry["size_bytes"]),
        "mtime_ns": int(entry["mtime_ns"]),
    }
    if _fingerprint(path) != expected:
        raise BseRecursiveRecoveryError(f"frozen recursive file changed: {path}")
    if "sha256" in entry and _sha256_file(path) != entry["sha256"]:
        raise BseRecursiveRecoveryError(f"frozen recursive content changed: {path}")


def _load_candidate_report(path: Path, *, plan) -> dict[str, object]:
    payload = _read_json(path)
    if payload.get("stage") != "recursive_candidate_build" or payload.get("complete") is not True:
        raise BseRecursiveRecoveryError("recursive candidate report is incomplete")
    frozen = {
        key: value
        for key, value in payload.items()
        if key not in {"candidate_report_hash", "elapsed_seconds", "generated_at", "should_stop", "write_counters"}
    }
    if payload.get("plan_hash") != plan["plan_hash"] or _hash_payload(frozen) != payload.get("candidate_report_hash"):
        raise BseRecursiveRecoveryError("recursive candidate report hash mismatch")
    return payload


def _load_audit_report(path: Path, *, plan, report) -> dict[str, object]:
    payload = _read_json(path)
    if payload.get("stage") != "recursive_candidate_audit" or payload.get("complete") is not True:
        raise BseRecursiveRecoveryError("recursive candidate audit is not green")
    frozen = {
        key: value
        for key, value in payload.items()
        if key not in {"audit_hash", "elapsed_seconds", "generated_at", "should_stop", "write_counters"}
    }
    if payload.get("plan_hash") != plan["plan_hash"] or payload.get("candidate_report_hash") != report["candidate_report_hash"] or _hash_payload(frozen) != payload.get("audit_hash"):
        raise BseRecursiveRecoveryError("recursive audit hash mismatch")
    return payload


def _load_checkpoint(path: Path, *, plan_hash: str) -> dict[str, object]:
    if not path.exists():
        return {"plan_hash": plan_hash}
    payload = _read_json(path)
    if payload.get("plan_hash") != plan_hash:
        raise BseRecursiveRecoveryError(f"checkpoint identity mismatch: {path}")
    return payload


def _write_candidate_checkpoint(path, *, plan_hash, completed_macd, completed_nineturn):
    _atomic_write_json(
        path,
        {
            "plan_hash": plan_hash,
            "completed_macd_batches": sorted(completed_macd),
            "completed_nineturn_partitions": sorted(completed_nineturn),
        },
    )


def _assert_promoted(row: Mapping[str, object]) -> None:
    target = Path(str(row["target_path"]))
    if not target.is_file() or _sha256_file(target) != row["candidate_sha256"]:
        raise BseRecursiveRecoveryError(f"promoted recursive file changed: {target}")


def _required_file_fingerprint(path: Path) -> dict[str, object]:
    value = _fingerprint(path)
    if not value["exists"]:
        raise BseRecursiveRecoveryError(f"required recursive file is missing: {path}")
    return value


def _fingerprint(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "size_bytes": 0, "mtime_ns": 0}
    stat = path.stat()
    return {"path": str(path), "exists": True, "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _recursive_contract_paths() -> tuple[Path, ...]:
    repository_root = Path(__file__).resolve().parents[6]
    return (
        Path(__file__).resolve(),
        repository_root / "lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_bse_history_recovery_cli.py",
        repository_root / "lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq_macd_kdj.py",
        repository_root / "lake_console/orchestrator/src/orchestrator/defs/qfq_nineturn.py",
        repository_root / "lake_console/docs/design/dagster-gold-wealth-market-turnover-dataset-low-level-design.md",
    )


def _content_fingerprint(path: Path) -> dict[str, object]:
    return {**_required_file_fingerprint(path), "sha256": _sha256_file(path)}


def _assert_staging_path(path: Path, *, lake_root: Path) -> None:
    staging_root = Path("/Volumes/datasource/data_lake_staging").resolve()
    if not path.is_relative_to(staging_root) or path.is_relative_to(lake_root):
        raise BseRecursiveRecoveryError("recursive plan root must remain in formal staging")


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BseRecursiveRecoveryError(f"JSON is unreadable: {path}") from error
    if not isinstance(payload, dict):
        raise BseRecursiveRecoveryError(f"JSON payload must be an object: {path}")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp_path, path)


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zero_control_plane_writes() -> dict[str, int]:
    return {"dagster_events": 0, "dagster_runs": 0, "dynamic_partitions": 0}


__all__ = [
    "BseRecursiveRecoveryError",
    "audit_bse_recursive_recovery_candidates",
    "build_bse_recursive_recovery_candidates",
    "plan_bse_recursive_recovery",
    "promote_bse_recursive_recovery_candidates",
]
