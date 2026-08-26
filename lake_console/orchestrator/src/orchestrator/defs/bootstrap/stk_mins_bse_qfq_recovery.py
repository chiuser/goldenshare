"""Bounded R3 QFQ recovery for the frozen BSE Silver change manifest."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import shutil
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET,
)
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_COLUMNS,
    build_as_of_adj_factor_by_code_sql,
    build_canonical_gold_stk_mins_qfq_select_sql,
)

R3_SCHEMA_VERSION = 1
R3_STAGE_NAME = "r3_bounded_qfq_recovery"
R3_CANDIDATE_ROOT_NAME = "r3-qfq-candidates"
R3_SCOPE_FILE_NAME = "r3-qfq-scope.parquet"
R3_PLAN_FILE_NAME = "r3-qfq-plan.json"
R3_CANDIDATE_CHECKPOINT_NAME = "r3-qfq-candidate-checkpoint.json"
R3_AUDIT_CHECKPOINT_NAME = "r3-qfq-audit-checkpoint.json"
R3_PROMOTE_CHECKPOINT_NAME = "r3-qfq-promote-checkpoint.json"
R3_CHANGED_MANIFEST_NAME = "actual-changed-qfq-manifest.json"
R3_AS_OF_FACTOR_FILE_NAME = "r3-as-of-adj-factor.parquet"
R3_AUDIT_MAX_SECONDS = 300.0
R3_MIN_FREE_SPACE_BYTES = 20 * 1024**3

_TARGET_FREQS_BY_SOURCE_FREQ = {
    1: (1, 5),
    5: (15, 30),
    15: (),
    30: (60, 90),
    60: (120,),
}


class BseQfqRecoveryError(RuntimeError):
    pass


def plan_bse_qfq_recovery(
    *,
    changed_silver_manifest_path: Path,
    duckdb_resource: DuckDBResource,
    output_path: Path,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
) -> dict[str, object]:
    """Freeze the exact R3 code/date/frequency scope without changing Gold."""

    started_at = perf_counter()
    manifest_path = changed_silver_manifest_path.resolve()
    plan_root = manifest_path.parent
    lake_root = lake_root.resolve()
    _assert_staging_path(plan_root, lake_root=lake_root)
    manifest = _load_changed_silver_manifest(manifest_path)
    source_scope_path = plan_root / "scope.parquet"
    if not source_scope_path.is_file():
        raise BseQfqRecoveryError(f"R0 scope is missing: {source_scope_path}")

    with duckdb_resource.connect() as connection:
        exact_codes_by_source = _resolve_exact_affected_codes(
            connection,
            manifest=manifest,
            source_scope_path=source_scope_path,
        )
        scope_rows = _map_qfq_scope_rows(
            manifest=manifest,
            exact_codes_by_source=exact_codes_by_source,
        )
        if not scope_rows:
            raise BseQfqRecoveryError("R3 QFQ scope is empty")
        planning_scope_path = plan_root / f".{R3_SCOPE_FILE_NAME}.{os.getpid()}"
        planning_scope_path.unlink(missing_ok=True)
        _write_scope_parquet(connection, rows=scope_rows, output_path=planning_scope_path)

    source_fingerprints = _silver_source_fingerprints(
        manifest=manifest,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
    )
    source_dates = sorted({str(row["trade_date"]) for row in scope_rows})
    trade_factor_fingerprints = tuple(
        _required_file_fingerprint(silver_adj_factor_path(lake_root, trade_date))
        for trade_date in source_dates
    )
    as_of_factor_manifest = _build_as_of_adj_factor_snapshot(
        lake_root=lake_root,
        plan_root=plan_root,
        duckdb_resource=duckdb_resource,
    )

    target_keys = sorted(
        {
            (int(row["target_freq"]), str(row["ts_code"]), int(row["year"]))
            for row in scope_rows
        }
    )
    target_fingerprints = tuple(
        _required_file_fingerprint(
            gold_stk_mins_qfq_path(lake_root, freq, ts_code, year)
        )
        for freq, ts_code, year in target_keys
    )
    scope_sha256 = _sha256_file(planning_scope_path)
    batches = _scope_batches(scope_rows)
    estimated_candidate_bytes = sum(
        int(entry["size_bytes"]) for entry in target_fingerprints
    )
    available_bytes = shutil.disk_usage(plan_root).free
    code_fingerprints = tuple(_content_fingerprint(path) for path in _r3_contract_paths())
    frozen_payload: dict[str, object] = {
        "schema_version": R3_SCHEMA_VERSION,
        "stage": R3_STAGE_NAME,
        "lake_root": str(lake_root),
        "plan_root": str(plan_root),
        "changed_silver_manifest_path": str(manifest_path),
        "changed_silver_manifest_hash": manifest["manifest_hash"],
        "source_scope_path": str(source_scope_path),
        "source_scope_sha256": _sha256_file(source_scope_path),
        "r3_scope_sha256": scope_sha256,
        "as_of_adj_factor_trade_date": as_of_factor_manifest[
            "as_of_trade_date"
        ],
        "as_of_factor_fingerprint": as_of_factor_manifest,
        "trade_factor_fingerprints": list(trade_factor_fingerprints),
        "silver_source_fingerprints": list(source_fingerprints),
        "target_fingerprints": list(target_fingerprints),
        "code_fingerprints": list(code_fingerprints),
        "batches": list(batches),
        "scope_row_count": len(scope_rows),
        "target_stock_year_file_count": len(target_keys),
        "estimated_candidate_bytes": estimated_candidate_bytes,
    }
    r3_plan_hash = _hash_payload(frozen_payload)
    scope_path = plan_root / R3_SCOPE_FILE_NAME
    if scope_path.exists():
        if _sha256_file(scope_path) != scope_sha256:
            raise BseQfqRecoveryError("existing R3 scope belongs to another plan")
        planning_scope_path.unlink(missing_ok=True)
    else:
        os.replace(planning_scope_path, scope_path)
    required_free_bytes = estimated_candidate_bytes * 2 + R3_MIN_FREE_SPACE_BYTES
    payload: dict[str, object] = {
        **frozen_payload,
        "r3_plan_hash": r3_plan_hash,
        "r3_scope_path": str(scope_path),
        "mapped_target_date_freq_count": len(
            {(row["trade_date"], row["target_freq"]) for row in scope_rows}
        ),
        "mapped_code_date_count": len(scope_rows),
        "ignored_silver_15m_count": sum(
            1 for row in manifest["changed_silver_rows"] if int(row["freq"]) == 15
        ),
        "available_bytes": available_bytes,
        "required_free_bytes": required_free_bytes,
        "same_filesystem": lake_root.stat().st_dev == plan_root.stat().st_dev,
        "elapsed_seconds": round(perf_counter() - started_at, 3),
        "generated_at": _utc_now(),
        "should_stop": (
            available_bytes < required_free_bytes
            or lake_root.stat().st_dev != plan_root.stat().st_dev
        ),
        "stop_reason_code": (
            "different_filesystem"
            if lake_root.stat().st_dev != plan_root.stat().st_dev
            else (
                "insufficient_staging_space"
                if available_bytes < required_free_bytes
                else None
            )
        ),
        "write_counters": _zero_control_plane_writes(),
    }
    _atomic_write_json(plan_root / R3_PLAN_FILE_NAME, payload)
    _atomic_write_json(output_path, payload)
    return payload


def build_bse_qfq_recovery_candidates(
    *,
    plan_path: Path,
    duckdb_resource: DuckDBResource,
    output_path: Path,
    confirm: bool,
    max_batch_count: int | None = None,
) -> dict[str, object]:
    if not confirm:
        raise BseQfqRecoveryError("R3 candidate build requires explicit confirmation")
    started_at = perf_counter()
    plan = _load_r3_plan(plan_path)
    _assert_plan_unchanged(plan, duckdb_resource=duckdb_resource)
    plan_root = Path(str(plan["plan_root"]))
    checkpoint_path = plan_root / R3_CANDIDATE_CHECKPOINT_NAME
    checkpoint = _load_checkpoint(
        checkpoint_path,
        plan_hash=str(plan["r3_plan_hash"]),
        row_field="candidate_files",
    )
    completed = {str(value) for value in checkpoint.get("completed_batches", ())}
    candidate_files = list(checkpoint["candidate_files"])
    no_op_pairs = list(checkpoint.get("no_op_pairs", ()))
    pending_batches = [
        batch for batch in plan["batches"] if str(batch["batch_key"]) not in completed
    ]
    if max_batch_count is not None:
        if max_batch_count <= 0:
            raise BseQfqRecoveryError("max_batch_count must be positive")
        pending_batches = pending_batches[:max_batch_count]

    for batch in pending_batches:
        batch_started_at = perf_counter()
        batch_files, batch_no_ops = _build_qfq_batch_candidates(
            plan=plan,
            batch=batch,
            duckdb_resource=duckdb_resource,
        )
        if perf_counter() - batch_started_at > R3_AUDIT_MAX_SECONDS:
            raise BseQfqRecoveryError(
                f"R3 candidate batch exceeded 300 seconds: {batch['batch_key']}"
            )
        candidate_files.extend(batch_files)
        no_op_pairs.extend(batch_no_ops)
        completed.add(str(batch["batch_key"]))
        _atomic_write_json(
            checkpoint_path,
            {
                "r3_plan_hash": plan["r3_plan_hash"],
                "completed_batches": sorted(completed),
                "candidate_files": candidate_files,
                "no_op_pairs": no_op_pairs,
            },
        )

    complete = len(completed) == len(plan["batches"])
    report_payload: dict[str, object] = {
        "schema_version": R3_SCHEMA_VERSION,
        "stage": "r3_qfq_candidate_build",
        "r3_plan_hash": plan["r3_plan_hash"],
        "candidate_file_count": len(candidate_files),
        "changed_code_date_count": sum(
            len(row["changed_trade_dates"]) for row in candidate_files
        ),
        "no_op_code_date_count": len(no_op_pairs),
        "completed_batch_count": len(completed),
        "planned_batch_count": len(plan["batches"]),
        "candidate_files": candidate_files,
        "no_op_pairs": no_op_pairs,
        "complete": complete,
        "elapsed_seconds": round(perf_counter() - started_at, 3),
        "generated_at": _utc_now(),
        "should_stop": not complete,
        "write_counters": _zero_control_plane_writes(),
    }
    frozen = {
        key: value
        for key, value in report_payload.items()
        if key not in {"generated_at", "should_stop"}
    }
    report_payload["candidate_report_hash"] = _hash_payload(frozen)
    _atomic_write_json(output_path, report_payload)
    return report_payload


def audit_bse_qfq_recovery_candidates(
    *,
    plan_path: Path,
    candidate_report_path: Path,
    duckdb_resource: DuckDBResource,
    output_path: Path,
    max_candidate_count: int | None = None,
) -> dict[str, object]:
    started_at = perf_counter()
    plan = _load_r3_plan(plan_path)
    _assert_plan_unchanged(plan, duckdb_resource=duckdb_resource)
    report = _load_candidate_report(candidate_report_path, plan=plan)
    if report.get("complete") is not True:
        raise BseQfqRecoveryError("R3 candidate report is incomplete")
    plan_root = Path(str(plan["plan_root"]))
    checkpoint_path = plan_root / R3_AUDIT_CHECKPOINT_NAME
    checkpoint = _load_checkpoint(
        checkpoint_path,
        plan_hash=str(plan["r3_plan_hash"]),
        row_field="audited_files",
    )
    audited_files = list(checkpoint["audited_files"])
    completed = {str(row["target_path"]) for row in audited_files}
    pending = [
        row
        for row in report["candidate_files"]
        if str(row["target_path"]) not in completed
    ]
    if max_candidate_count is not None:
        if max_candidate_count <= 0:
            raise BseQfqRecoveryError("max_candidate_count must be positive")
        pending = pending[:max_candidate_count]
    failures: list[dict[str, object]] = []
    with duckdb_resource.connect() as connection:
        for row in pending:
            if perf_counter() - started_at > R3_AUDIT_MAX_SECONDS:
                failures.append({"reason_code": "audit_timeout"})
                break
            try:
                _audit_candidate_file(connection, row=row)
                audited_files.append(dict(row))
                _atomic_write_json(
                    checkpoint_path,
                    {
                        "r3_plan_hash": plan["r3_plan_hash"],
                        "candidate_report_hash": report["candidate_report_hash"],
                        "audited_files": audited_files,
                    },
                )
            except Exception as error:  # noqa: BLE001 - bounded report.
                failures.append(
                    {
                        "target_path": row.get("target_path"),
                        "error_type": type(error).__name__,
                        "reason": str(error)[:500],
                    }
                )
                break
    complete = len(audited_files) == len(report["candidate_files"]) and not failures
    frozen: dict[str, object] = {
        "schema_version": R3_SCHEMA_VERSION,
        "stage": "r3_qfq_candidate_audit",
        "r3_plan_hash": plan["r3_plan_hash"],
        "candidate_report_hash": report["candidate_report_hash"],
        "audited_file_count": len(audited_files),
        "candidate_file_count": len(report["candidate_files"]),
        "audited_files": audited_files,
        "failure_samples": failures[:20],
        "complete": complete,
    }
    payload: dict[str, object] = {
        **frozen,
        "audit_hash": _hash_payload(frozen),
        "elapsed_seconds": round(perf_counter() - started_at, 3),
        "generated_at": _utc_now(),
        "should_stop": not complete,
        "write_counters": _zero_control_plane_writes(),
    }
    _atomic_write_json(output_path, payload)
    return payload


def promote_bse_qfq_recovery_candidates(
    *,
    plan_path: Path,
    candidate_report_path: Path,
    audit_report_path: Path,
    checkpoint_path: Path,
    changed_manifest_path: Path,
    output_path: Path,
    confirm: bool,
) -> dict[str, object]:
    if not confirm:
        raise BseQfqRecoveryError("formal QFQ promotion requires explicit confirmation")
    started_at = perf_counter()
    plan = _load_r3_plan(plan_path)
    _assert_non_target_plan_inputs_unchanged(plan)
    report = _load_candidate_report(candidate_report_path, plan=plan)
    audit = _load_audit_report(audit_report_path, plan=plan, report=report)
    if audit.get("complete") is not True:
        raise BseQfqRecoveryError("R3 QFQ audit is not green")
    checkpoint = _load_checkpoint(
        checkpoint_path,
        plan_hash=str(plan["r3_plan_hash"]),
        row_field="promoted_files",
    )
    promoted = list(checkpoint["promoted_files"])
    completed = {str(row["target_path"]) for row in promoted}
    in_progress = checkpoint.get("in_progress")
    if isinstance(in_progress, dict):
        _recover_interrupted_promotion(in_progress, promoted=promoted, completed=completed)

    for row in audit["audited_files"]:
        target_path = str(row["target_path"])
        if target_path in completed:
            _assert_promoted_file(row)
            continue
        candidate = Path(str(row["candidate_path"]))
        target = Path(target_path)
        if _fingerprint(target) != row["target_fingerprint"]:
            raise BseQfqRecoveryError(f"formal QFQ target changed: {target}")
        if not candidate.is_file() or _sha256_file(candidate) != row["candidate_sha256"]:
            raise BseQfqRecoveryError(f"R3 QFQ candidate changed: {candidate}")
        in_progress = {
            "target_path": target_path,
            "candidate_path": str(candidate),
            "candidate_sha256": row["candidate_sha256"],
        }
        _atomic_write_json(
            checkpoint_path,
            {
                "r3_plan_hash": plan["r3_plan_hash"],
                "audit_hash": audit["audit_hash"],
                "promoted_files": promoted,
                "in_progress": in_progress,
            },
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(candidate, target)
        if _sha256_file(target) != row["candidate_sha256"]:
            raise BseQfqRecoveryError(f"promoted QFQ hash mismatch: {target}")
        promoted_row = {
            "target_path": target_path,
            "candidate_sha256": row["candidate_sha256"],
            "freq": row["freq"],
            "ts_code": row["ts_code"],
            "year": row["year"],
            "changed_trade_dates": row["changed_trade_dates"],
        }
        promoted.append(promoted_row)
        completed.add(target_path)
        _atomic_write_json(
            checkpoint_path,
            {
                "r3_plan_hash": plan["r3_plan_hash"],
                "audit_hash": audit["audit_hash"],
                "promoted_files": promoted,
                "in_progress": None,
            },
        )

    changed_manifest = _build_changed_qfq_manifest(
        plan=plan,
        audit=audit,
        promoted=promoted,
    )
    _atomic_write_json(changed_manifest_path, changed_manifest)
    frozen: dict[str, object] = {
        "schema_version": R3_SCHEMA_VERSION,
        "stage": "r3_qfq_promote",
        "r3_plan_hash": plan["r3_plan_hash"],
        "audit_hash": audit["audit_hash"],
        "promoted_file_count": len(promoted),
        "changed_code_date_count": changed_manifest["changed_code_date_count"],
        "changed_qfq_manifest_hash": changed_manifest["manifest_hash"],
    }
    payload: dict[str, object] = {
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


def _resolve_exact_affected_codes(
    connection,
    *,
    manifest: Mapping[str, object],
    source_scope_path: Path,
) -> dict[tuple[str, int], tuple[str, ...]]:
    rows = connection.execute(
        f"""
        SELECT trade_date, freq, latest_ts_code
        FROM {read_parquet(source_scope_path, hive_partitioning=False)}
        WHERE coverage_status <> 'covered'
        ORDER BY trade_date, freq, latest_ts_code
        """
    ).fetchall()
    codes_by_date_freq: dict[str, dict[int, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for trade_date, freq, ts_code in rows:
        codes_by_date_freq[str(trade_date)][int(freq)].add(str(ts_code))

    resolved: dict[tuple[str, int], tuple[str, ...]] = {}
    for row in manifest["changed_silver_rows"]:
        trade_date = str(row["trade_date"])
        source_freq = int(row["freq"])
        expected_count = int(row["affected_latest_code_count"])
        expected_hash = str(row["affected_latest_code_hash"])
        freq_sets = codes_by_date_freq.get(trade_date) or {}
        unique_matches: set[tuple[str, ...]] = set()
        freqs = sorted(freq_sets)
        for size in range(1, len(freqs) + 1):
            for selected_freqs in itertools.combinations(freqs, size):
                codes = tuple(
                    sorted(
                        set().union(*(freq_sets[freq] for freq in selected_freqs))
                    )
                )
                if len(codes) == expected_count and _hash_payload(codes) == expected_hash:
                    unique_matches.add(codes)
        if len(unique_matches) != 1:
            raise BseQfqRecoveryError(
                "R2 affected code hash cannot be resolved uniquely: "
                f"{trade_date} freq={source_freq} matches={len(unique_matches)}"
            )
        codes = next(iter(unique_matches))
        if any(not code.endswith(".BJ") for code in codes):
            raise BseQfqRecoveryError("R3 affected code scope contains non-BSE code")
        resolved[(trade_date, source_freq)] = codes
    return resolved


def _map_qfq_scope_rows(
    *,
    manifest: Mapping[str, object],
    exact_codes_by_source: Mapping[tuple[str, int], tuple[str, ...]],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for source_row in manifest["changed_silver_rows"]:
        trade_date = str(source_row["trade_date"])
        source_freq = int(source_row["freq"])
        codes = exact_codes_by_source[(trade_date, source_freq)]
        for target_freq in _TARGET_FREQS_BY_SOURCE_FREQ[source_freq]:
            if CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[target_freq] != source_freq:
                raise BseQfqRecoveryError("QFQ source frequency mapping drifted")
            for ts_code in codes:
                rows.append(
                    {
                        "trade_date": trade_date,
                        "source_freq": source_freq,
                        "target_freq": target_freq,
                        "ts_code": ts_code,
                        "year": int(trade_date[:4]),
                        "source_affected_code_hash": source_row[
                            "affected_latest_code_hash"
                        ],
                    }
                )
    rows.sort(
        key=lambda row: (
            int(row["target_freq"]),
            int(row["year"]),
            str(row["ts_code"]),
            str(row["trade_date"]),
        )
    )
    return tuple(rows)


def _write_scope_parquet(connection, *, rows, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        """
        CREATE TEMP TABLE r3_qfq_scope (
          trade_date DATE,
          source_freq INTEGER,
          target_freq INTEGER,
          ts_code VARCHAR,
          year INTEGER,
          source_affected_code_hash VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO r3_qfq_scope VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                row["trade_date"],
                row["source_freq"],
                row["target_freq"],
                row["ts_code"],
                row["year"],
                row["source_affected_code_hash"],
            )
            for row in rows
        ],
    )
    connection.execute(
        copy_query_to_parquet(
            """
            SELECT *
            FROM r3_qfq_scope
            ORDER BY target_freq, year, ts_code, trade_date
            """,
            output_path,
        )
    )


def _scope_batches(rows) -> tuple[dict[str, object], ...]:
    grouped: dict[tuple[int, int], dict[str, set[str]]] = defaultdict(
        lambda: {"dates": set(), "codes": set()}
    )
    for row in rows:
        key = (int(row["target_freq"]), int(row["year"]))
        grouped[key]["dates"].add(str(row["trade_date"]))
        grouped[key]["codes"].add(str(row["ts_code"]))
    return tuple(
        {
            "batch_key": f"{freq}:{year}",
            "target_freq": freq,
            "source_freq": CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[freq],
            "year": year,
            "trade_dates": sorted(values["dates"]),
            "stock_code_count": len(values["codes"]),
        }
        for (freq, year), values in sorted(grouped.items())
    )


def _build_qfq_batch_candidates(
    *,
    plan: Mapping[str, object],
    batch: Mapping[str, object],
    duckdb_resource: DuckDBResource,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    lake_root = Path(str(plan["lake_root"]))
    scope_path = Path(str(plan["r3_scope_path"]))
    target_freq = int(batch["target_freq"])
    source_freq = int(batch["source_freq"])
    year = int(batch["year"])
    trade_dates = tuple(str(value) for value in batch["trade_dates"])
    target_index = {
        str(entry["path"]): entry for entry in plan["target_fingerprints"]
    }
    with duckdb_resource.connect() as connection:
        scope_rows = connection.execute(
            f"""
            SELECT ts_code, strftime(trade_date, '%Y-%m-%d') AS trade_date
            FROM {read_parquet(scope_path, hive_partitioning=False)}
            WHERE target_freq = {target_freq}
              AND year = {year}
            ORDER BY ts_code, trade_date
            """
        ).fetchall()
        stock_codes = tuple(sorted({str(row[0]) for row in scope_rows}))
        qfq_sql = build_canonical_gold_stk_mins_qfq_select_sql(
            silver_paths=[
                silver_stk_mins_path(lake_root, source_freq, trade_date)
                for trade_date in trade_dates
            ],
            trade_adj_factor_paths=[
                silver_adj_factor_path(lake_root, trade_date)
                for trade_date in trade_dates
            ],
            as_of_adj_factor_paths=[
                Path(str(plan["as_of_factor_fingerprint"]["path"]))
            ],
            target_freq=target_freq,
            partition_keys=trade_dates,
            stock_codes=stock_codes,
        )
        connection.execute(f"CREATE TEMP TABLE r3_expected_all AS {qfq_sql}")
        connection.execute(
            f"""
            CREATE TEMP TABLE r3_expected AS
            SELECT expected.*
            FROM r3_expected_all AS expected
            INNER JOIN {read_parquet(scope_path, hive_partitioning=False)} AS scope
              ON expected.ts_code = scope.ts_code
             AND expected.trade_date = scope.trade_date
             AND expected.freq = scope.target_freq
            WHERE scope.target_freq = {target_freq}
              AND scope.year = {year}
            """
        )
        _assert_expected_scope_complete(
            connection,
            scope_path=scope_path,
            target_freq=target_freq,
            year=year,
        )
        target_paths = tuple(
            gold_stk_mins_qfq_path(lake_root, target_freq, code, year)
            for code in stock_codes
        )
        formal_relation = _read_parquet_paths(target_paths)
        _create_scoped_changed_pairs(
            connection,
            formal_relation=formal_relation,
            scope_path=scope_path,
            target_freq=target_freq,
            year=year,
        )
        changed_rows = connection.execute(
            """
            SELECT ts_code, strftime(trade_date, '%Y-%m-%d')
            FROM r3_changed_pairs
            ORDER BY ts_code, trade_date
            """
        ).fetchall()
        changed_by_code: dict[str, list[str]] = defaultdict(list)
        for ts_code, trade_date in changed_rows:
            changed_by_code[str(ts_code)].append(str(trade_date))
        scope_set = {(str(code), str(date)) for code, date in scope_rows}
        changed_set = {
            (code, trade_date)
            for code, dates in changed_by_code.items()
            for trade_date in dates
        }
        if not changed_set.issubset(scope_set):
            raise BseQfqRecoveryError("QFQ candidate change escaped R3 scope")
        no_op_pairs = [
            {
                "freq": target_freq,
                "ts_code": code,
                "trade_date": trade_date,
            }
            for code, trade_date in sorted(scope_set - changed_set)
        ]
        candidate_files: list[dict[str, object]] = []
        for ts_code, changed_dates in sorted(changed_by_code.items()):
            target_path = gold_stk_mins_qfq_path(
                lake_root, target_freq, ts_code, year
            )
            target_fingerprint = target_index.get(str(target_path))
            if target_fingerprint is None:
                raise BseQfqRecoveryError(
                    f"QFQ target escaped frozen plan: {target_path}"
                )
            if _fingerprint(target_path) != target_fingerprint:
                raise BseQfqRecoveryError(f"QFQ target changed: {target_path}")
            candidate_path = _candidate_path(plan, target_path)
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.unlink(missing_ok=True)
            dates_sql = _date_values_sql(changed_dates)
            connection.execute(
                copy_query_to_parquet(
                    f"""
                    SELECT {', '.join(GOLD_STK_MINS_QFQ_COLUMNS)}
                    FROM (
                      SELECT {', '.join(GOLD_STK_MINS_QFQ_COLUMNS)}
                      FROM {read_parquet(target_path, hive_partitioning=False)}
                      WHERE trade_date NOT IN ({dates_sql})
                      UNION ALL
                      SELECT {', '.join(GOLD_STK_MINS_QFQ_COLUMNS)}
                      FROM r3_expected
                      WHERE ts_code = {duckdb_string(ts_code)}
                        AND trade_date IN ({dates_sql})
                    )
                    ORDER BY trade_date, trade_time
                    """,
                    candidate_path,
                )
            )
            _assert_qfq_file_contract(
                connection,
                path=candidate_path,
                target_freq=target_freq,
                ts_code=ts_code,
                year=year,
            )
            old_non_target_hash = _qfq_hash(
                connection, target_path, excluded_dates=changed_dates
            )
            new_non_target_hash = _qfq_hash(
                connection, candidate_path, excluded_dates=changed_dates
            )
            if old_non_target_hash != new_non_target_hash:
                raise BseQfqRecoveryError("QFQ candidate changed non-target dates")
            candidate_files.append(
                {
                    "batch_key": batch["batch_key"],
                    "freq": target_freq,
                    "ts_code": ts_code,
                    "year": year,
                    "target_path": str(target_path),
                    "target_fingerprint": target_fingerprint,
                    "candidate_path": str(candidate_path),
                    "candidate_sha256": _sha256_file(candidate_path),
                    "candidate_hash": _qfq_hash(connection, candidate_path),
                    "formal_hash": _qfq_hash(connection, target_path),
                    "non_target_hash": old_non_target_hash,
                    "changed_trade_dates": sorted(changed_dates),
                }
            )
        connection.execute("DROP TABLE r3_expected_all")
        connection.execute("DROP TABLE r3_expected")
        connection.execute("DROP TABLE r3_changed_pairs")
    return candidate_files, no_op_pairs


def _assert_expected_scope_complete(
    connection, *, scope_path: Path, target_freq: int, year: int
) -> None:
    row = connection.execute(
        f"""
        WITH expected_pairs AS (
          SELECT ts_code, trade_date
          FROM {read_parquet(scope_path, hive_partitioning=False)}
          WHERE target_freq = {target_freq} AND year = {year}
        ), output_pairs AS (
          SELECT DISTINCT ts_code, trade_date FROM r3_expected
        )
        SELECT
          (SELECT count(*) FROM expected_pairs),
          (SELECT count(*) FROM output_pairs),
          (SELECT count(*) FROM expected_pairs ANTI JOIN output_pairs USING(ts_code, trade_date)),
          (SELECT count(*) FROM output_pairs ANTI JOIN expected_pairs USING(ts_code, trade_date))
        """
    ).fetchone()
    if tuple(int(value) for value in row[0:4]) != (int(row[0]), int(row[0]), 0, 0):
        raise BseQfqRecoveryError(
            f"QFQ source/output code-date coverage mismatch: {row}"
        )


def _qfq_value_changed_sql(old_alias: str, new_alias: str) -> str:
    key_columns = {"ts_code", "trade_time"}
    return " OR ".join(
        f'{old_alias}."{column}" IS DISTINCT FROM {new_alias}."{column}"'
        for column in GOLD_STK_MINS_QFQ_COLUMNS
        if column not in key_columns
    )


def _create_scoped_changed_pairs(
    connection,
    *,
    formal_relation: str,
    scope_path: Path,
    target_freq: int,
    year: int,
) -> None:
    connection.execute(
        f"""
        CREATE TEMP TABLE r3_changed_pairs AS
        WITH scoped_pairs AS (
          SELECT ts_code, trade_date
          FROM {read_parquet(scope_path, hive_partitioning=False)}
          WHERE target_freq = {target_freq}
            AND year = {year}
        ), old AS (
          SELECT formal.*, true AS present
          FROM {formal_relation} AS formal
          INNER JOIN scoped_pairs AS scope
            ON formal.ts_code = scope.ts_code
           AND formal.trade_date = scope.trade_date
        ), new AS (
          SELECT *, true AS present
          FROM r3_expected
        )
        SELECT DISTINCT
          coalesce(old.ts_code, new.ts_code) AS ts_code,
          coalesce(old.trade_date, new.trade_date) AS trade_date
        FROM old
        FULL OUTER JOIN new
          ON old.ts_code = new.ts_code
         AND old.trade_time = new.trade_time
        WHERE old.present IS NULL
           OR new.present IS NULL
           OR {_qfq_value_changed_sql('old', 'new')}
        """
    )


def _audit_candidate_file(connection, *, row: Mapping[str, object]) -> None:
    candidate = Path(str(row["candidate_path"]))
    target = Path(str(row["target_path"]))
    if _fingerprint(target) != row["target_fingerprint"]:
        raise BseQfqRecoveryError(f"formal target changed: {target}")
    if not candidate.is_file() or _sha256_file(candidate) != row["candidate_sha256"]:
        raise BseQfqRecoveryError(f"candidate changed: {candidate}")
    _assert_qfq_file_contract(
        connection,
        path=candidate,
        target_freq=int(row["freq"]),
        ts_code=str(row["ts_code"]),
        year=int(row["year"]),
    )
    if _qfq_hash(connection, candidate) != row["candidate_hash"]:
        raise BseQfqRecoveryError("candidate canonical hash changed")
    changed_dates = tuple(str(value) for value in row["changed_trade_dates"])
    if _qfq_hash(connection, target, excluded_dates=changed_dates) != row[
        "non_target_hash"
    ]:
        raise BseQfqRecoveryError("formal non-target rows changed")
    if _qfq_hash(connection, candidate, excluded_dates=changed_dates) != row[
        "non_target_hash"
    ]:
        raise BseQfqRecoveryError("candidate non-target rows changed")


def _assert_qfq_file_contract(
    connection, *, path: Path, target_freq: int, ts_code: str, year: int
) -> None:
    relation = read_parquet(path, hive_partitioning=False)
    observed = tuple(
        (str(row[0]), str(row[1]))
        for row in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    )
    expected = tuple((column.name, column.type) for column in GOLD_STK_MINS_QFQ_SCHEMA)
    if observed != expected:
        raise BseQfqRecoveryError(f"QFQ candidate schema mismatch: {path}")
    row = connection.execute(
        f"""
        SELECT
          count(*),
          count(*) FILTER (
            WHERE ts_code <> {duckdb_string(ts_code)}
               OR freq <> {target_freq}
               OR strftime(trade_date, '%Y') <> {duckdb_string(str(year))}
               OR ts_code IS NULL OR trade_time IS NULL
          ),
          count(*) - count(DISTINCT (ts_code, trade_time)),
          count(*) FILTER (
            WHERE NOT isfinite(open) OR NOT isfinite(high)
               OR NOT isfinite(low) OR NOT isfinite(close)
               OR NOT isfinite(vol) OR NOT isfinite(amount)
               OR high < greatest(open, close, low)
               OR low > least(open, close, high)
               OR vol < 0 OR amount < 0
          )
        FROM {relation}
        """
    ).fetchone()
    if int(row[0]) <= 0 or any(int(value) != 0 for value in row[1:]):
        raise BseQfqRecoveryError(f"QFQ candidate contract failed: {path}: {row}")


def _qfq_hash(
    connection, path: Path, *, excluded_dates: Sequence[str] = ()
) -> str:
    where = ""
    if excluded_dates:
        where = f"WHERE trade_date NOT IN ({_date_values_sql(excluded_dates)})"
    columns = ", ".join(f'"{column}"' for column in GOLD_STK_MINS_QFQ_COLUMNS)
    row = connection.execute(
        f"""
        SELECT
          count(*),
          coalesce(sum(CAST(hash({columns}) AS HUGEINT)), 0),
          coalesce(bit_xor(hash({columns})), 0)
        FROM {read_parquet(path, hive_partitioning=False)}
        {where}
        """
    ).fetchone()
    return _hash_payload(
        {"row_count": int(row[0]), "hash_sum": str(row[1]), "hash_xor": str(row[2])}
    )


def _silver_source_fingerprints(
    *, manifest, lake_root: Path, duckdb_resource: DuckDBResource
) -> tuple[dict[str, object], ...]:
    entries: list[dict[str, object]] = []
    with duckdb_resource.connect() as connection:
        for row in manifest["changed_silver_rows"]:
            path = silver_stk_mins_path(
                lake_root, int(row["freq"]), str(row["trade_date"])
            )
            fingerprint = _required_file_fingerprint(path)
            canonical_hash, row_count = _silver_canonical_hash(connection, path)
            if canonical_hash != row["new_canonical_hash"] or row_count != int(
                row["new_row_count"]
            ):
                raise BseQfqRecoveryError(f"R2 Silver source changed: {path}")
            entries.append(
                {
                    **fingerprint,
                    "canonical_hash": canonical_hash,
                    "row_count": row_count,
                }
            )
    return tuple(entries)


def _silver_canonical_hash(connection, path: Path) -> tuple[str, int]:
    relation = read_parquet(path, hive_partitioning=False)
    columns = ", ".join(f'"{column.name}"' for column in SILVER_STK_MINS_SCHEMA)
    row = connection.execute(
        f"""
        SELECT count(*),
          coalesce(sum(CAST(hash({columns}) AS HUGEINT)), 0),
          coalesce(bit_xor(hash({columns})), 0)
        FROM {relation}
        """
    ).fetchone()
    schema = tuple(
        (str(value[0]), str(value[1]).upper())
        for value in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    )
    payload = {
        "schema": schema,
        "row_count": int(row[0]),
        "hash_sum": str(row[1]),
        "hash_xor": str(row[2]),
    }
    return _hash_payload(payload), int(row[0])


def _load_changed_silver_manifest(path: Path) -> dict[str, object]:
    payload = _read_json(path)
    if payload.get("stage") != "r2_actual_changed_silver_manifest":
        raise BseQfqRecoveryError("unexpected changed Silver manifest stage")
    if payload.get("should_stop") is not False:
        raise BseQfqRecoveryError("changed Silver manifest is not green")
    frozen = {
        key: value
        for key, value in payload.items()
        if key not in {"manifest_hash", "generated_at", "should_stop"}
    }
    if _hash_payload(frozen) != payload.get("manifest_hash"):
        raise BseQfqRecoveryError("changed Silver manifest hash mismatch")
    rows = payload.get("changed_silver_rows")
    if not isinstance(rows, list) or len(rows) != int(
        payload.get("changed_silver_count", -1)
    ):
        raise BseQfqRecoveryError("changed Silver manifest rows are incomplete")
    return payload


def _load_r3_plan(path: Path) -> dict[str, object]:
    payload = _read_json(path)
    if payload.get("stage") != R3_STAGE_NAME or payload.get("should_stop") is not False:
        raise BseQfqRecoveryError("R3 plan is not green")
    frozen_keys = {
        "schema_version",
        "stage",
        "lake_root",
        "plan_root",
        "changed_silver_manifest_path",
        "changed_silver_manifest_hash",
        "source_scope_path",
        "source_scope_sha256",
        "r3_scope_sha256",
        "as_of_adj_factor_trade_date",
        "as_of_factor_fingerprint",
        "trade_factor_fingerprints",
        "silver_source_fingerprints",
        "target_fingerprints",
        "code_fingerprints",
        "batches",
        "scope_row_count",
        "target_stock_year_file_count",
        "estimated_candidate_bytes",
    }
    frozen = {key: payload[key] for key in frozen_keys}
    if _hash_payload(frozen) != payload.get("r3_plan_hash"):
        raise BseQfqRecoveryError("R3 plan hash mismatch")
    return payload


def _assert_plan_unchanged(
    plan: Mapping[str, object], *, duckdb_resource: DuckDBResource
) -> None:
    manifest = _load_changed_silver_manifest(
        Path(str(plan["changed_silver_manifest_path"]))
    )
    if manifest["manifest_hash"] != plan["changed_silver_manifest_hash"]:
        raise BseQfqRecoveryError("R2 changed manifest identity changed")
    scope_path = Path(str(plan["r3_scope_path"]))
    if _sha256_file(scope_path) != plan["r3_scope_sha256"]:
        raise BseQfqRecoveryError("R3 scope changed")
    if _sha256_file(Path(str(plan["source_scope_path"]))) != plan[
        "source_scope_sha256"
    ]:
        raise BseQfqRecoveryError("R0 scope changed")
    for entry in (
        *plan["silver_source_fingerprints"],
        *plan["trade_factor_fingerprints"],
        plan["as_of_factor_fingerprint"],
        *plan["target_fingerprints"],
        *plan["code_fingerprints"],
    ):
        if _fingerprint(Path(str(entry["path"]))) != {
            "path": str(entry["path"]),
            "exists": bool(entry["exists"]),
            "size_bytes": int(entry["size_bytes"]),
            "mtime_ns": int(entry["mtime_ns"]),
        }:
            raise BseQfqRecoveryError(f"frozen R3 file changed: {entry['path']}")
        if "sha256" in entry and _sha256_file(Path(str(entry["path"]))) != entry[
            "sha256"
        ]:
            raise BseQfqRecoveryError(f"frozen R3 content changed: {entry['path']}")
    # Recheck R2 canonical hashes; file stats alone are not the Silver contract.
    _silver_source_fingerprints(
        manifest=manifest,
        lake_root=Path(str(plan["lake_root"])),
        duckdb_resource=duckdb_resource,
    )


def _assert_non_target_plan_inputs_unchanged(plan: Mapping[str, object]) -> None:
    manifest = _load_changed_silver_manifest(
        Path(str(plan["changed_silver_manifest_path"]))
    )
    if manifest["manifest_hash"] != plan["changed_silver_manifest_hash"]:
        raise BseQfqRecoveryError("R2 changed manifest identity changed")
    for entry in (
        *plan["silver_source_fingerprints"],
        *plan["trade_factor_fingerprints"],
        plan["as_of_factor_fingerprint"],
        *plan["code_fingerprints"],
    ):
        path = Path(str(entry["path"]))
        if _fingerprint(path) != {
            "path": str(entry["path"]),
            "exists": bool(entry["exists"]),
            "size_bytes": int(entry["size_bytes"]),
            "mtime_ns": int(entry["mtime_ns"]),
        }:
            raise BseQfqRecoveryError(f"frozen R3 input changed: {path}")
        if "sha256" in entry and _sha256_file(path) != entry["sha256"]:
            raise BseQfqRecoveryError(f"frozen R3 input content changed: {path}")


def _load_candidate_report(path: Path, *, plan) -> dict[str, object]:
    payload = _read_json(path)
    if payload.get("stage") != "r3_qfq_candidate_build":
        raise BseQfqRecoveryError("unexpected R3 candidate report")
    if payload.get("r3_plan_hash") != plan["r3_plan_hash"]:
        raise BseQfqRecoveryError("R3 candidate plan mismatch")
    frozen = {
        key: value
        for key, value in payload.items()
        if key not in {"candidate_report_hash", "generated_at", "should_stop"}
    }
    if _hash_payload(frozen) != payload.get("candidate_report_hash"):
        raise BseQfqRecoveryError("R3 candidate report hash mismatch")
    return payload


def _load_audit_report(path: Path, *, plan, report) -> dict[str, object]:
    payload = _read_json(path)
    if payload.get("stage") != "r3_qfq_candidate_audit":
        raise BseQfqRecoveryError("unexpected R3 audit report")
    if payload.get("r3_plan_hash") != plan["r3_plan_hash"]:
        raise BseQfqRecoveryError("R3 audit plan mismatch")
    if payload.get("candidate_report_hash") != report["candidate_report_hash"]:
        raise BseQfqRecoveryError("R3 audit candidate mismatch")
    frozen = {
        key: value
        for key, value in payload.items()
        if key not in {"audit_hash", "elapsed_seconds", "generated_at", "should_stop", "write_counters"}
    }
    if _hash_payload(frozen) != payload.get("audit_hash"):
        raise BseQfqRecoveryError("R3 audit hash mismatch")
    return payload


def _build_changed_qfq_manifest(*, plan, audit, promoted) -> dict[str, object]:
    grouped: dict[tuple[int, str], set[str]] = defaultdict(set)
    for row in audit["audited_files"]:
        for trade_date in row["changed_trade_dates"]:
            grouped[(int(row["freq"]), str(row["ts_code"]))].add(str(trade_date))
    entries = [
        {
            "freq": freq,
            "ts_code": ts_code,
            "earliest_changed_trade_date": min(dates),
            "latest_changed_trade_date": max(dates),
            "changed_trade_dates": sorted(dates),
            "changed_trade_date_count": len(dates),
        }
        for (freq, ts_code), dates in sorted(grouped.items())
    ]
    frozen: dict[str, object] = {
        "schema_version": R3_SCHEMA_VERSION,
        "stage": "r3_actual_changed_qfq_manifest",
        "r3_plan_hash": plan["r3_plan_hash"],
        "audit_hash": audit["audit_hash"],
        "changed_file_count": len(promoted),
        "changed_code_freq_count": len(entries),
        "changed_code_date_count": sum(
            int(row["changed_trade_date_count"]) for row in entries
        ),
        "changed_qfq_rows": entries,
    }
    return {
        **frozen,
        "manifest_hash": _hash_payload(frozen),
        "generated_at": _utc_now(),
        "should_stop": False,
    }


def _recover_interrupted_promotion(in_progress, *, promoted, completed) -> None:
    target = Path(str(in_progress["target_path"]))
    candidate = Path(str(in_progress["candidate_path"]))
    expected_sha = str(in_progress["candidate_sha256"])
    if not candidate.exists() and target.is_file() and _sha256_file(target) == expected_sha:
        promoted.append(
            {
                "target_path": str(target),
                "candidate_sha256": expected_sha,
                "recovered_after_interruption": True,
            }
        )
        completed.add(str(target))
        return
    if candidate.is_file():
        return
    raise BseQfqRecoveryError("ambiguous interrupted QFQ promotion state")


def _assert_promoted_file(row: Mapping[str, object]) -> None:
    target = Path(str(row["target_path"]))
    if not target.is_file() or _sha256_file(target) != row["candidate_sha256"]:
        raise BseQfqRecoveryError(f"promoted QFQ file changed: {target}")


def _build_as_of_adj_factor_snapshot(
    *, lake_root: Path, plan_root: Path, duckdb_resource: DuckDBResource
) -> dict[str, object]:
    factor_paths = tuple(
        sorted(
            (lake_root / "silver/quote/adj_factor").glob(
                "trade_date=*/part-000.parquet"
            )
        )
    )
    if not factor_paths:
        raise BseQfqRecoveryError("no formal Silver adj factor partition exists")
    latest_trade_date = _partition_from_path(factor_paths[-1])
    output_path = plan_root / R3_AS_OF_FACTOR_FILE_NAME
    planning_path = plan_root / f".{R3_AS_OF_FACTOR_FILE_NAME}.{os.getpid()}"
    planning_path.unlink(missing_ok=True)
    as_of_sql = build_as_of_adj_factor_by_code_sql(factor_paths)
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
                planning_path,
            )
        )
        row = connection.execute(
            f"""
            SELECT
              count(*), count(DISTINCT ts_code),
              count(*) FILTER (
                WHERE ts_code IS NULL OR trim(ts_code) = ''
                   OR trade_date IS NULL OR adj_factor IS NULL
                   OR NOT isfinite(adj_factor) OR adj_factor <= 0
              ),
              min(trade_date), max(trade_date)
            FROM {read_parquet(planning_path, hive_partitioning=False)}
            """
        ).fetchone()
    if int(row[0]) <= 0 or int(row[0]) != int(row[1]) or int(row[2]) != 0:
        planning_path.unlink(missing_ok=True)
        raise BseQfqRecoveryError("R3 as-of adj factor snapshot failed contract")
    snapshot_sha = _sha256_file(planning_path)
    if output_path.exists():
        if _sha256_file(output_path) != snapshot_sha:
            raise BseQfqRecoveryError("existing R3 as-of snapshot changed")
        planning_path.unlink(missing_ok=True)
    else:
        os.replace(planning_path, output_path)
    return {
        **_fingerprint(output_path),
        "sha256": snapshot_sha,
        "row_count": int(row[0]),
        "first_factor_trade_date": row[3].isoformat(),
        "last_factor_trade_date": row[4].isoformat(),
        "as_of_trade_date": latest_trade_date,
        "source_partition_count": len(factor_paths),
    }


def _candidate_path(plan: Mapping[str, object], target_path: Path) -> Path:
    lake_root = Path(str(plan["lake_root"]))
    return (
        Path(str(plan["plan_root"]))
        / R3_CANDIDATE_ROOT_NAME
        / target_path.relative_to(lake_root)
    )


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise BseQfqRecoveryError("at least one parquet path is required")
    values = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{values}], hive_partitioning=false)"


def _date_values_sql(values: Sequence[str]) -> str:
    return ", ".join(f"DATE {duckdb_string(value)}" for value in sorted(set(values)))


def _required_file_fingerprint(path: Path) -> dict[str, object]:
    fingerprint = _fingerprint(path)
    if not fingerprint["exists"]:
        raise BseQfqRecoveryError(f"required R3 file is missing: {path}")
    return fingerprint


def _fingerprint(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "size_bytes": 0, "mtime_ns": 0}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _r3_contract_paths() -> tuple[Path, ...]:
    repository_root = Path(__file__).resolve().parents[6]
    return (
        Path(__file__).resolve(),
        repository_root
        / "lake_console/orchestrator/src/orchestrator/defs/bootstrap/"
        "stk_mins_bse_history_recovery_cli.py",
        repository_root
        / "lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq.py",
        repository_root
        / "lake_console/orchestrator/src/orchestrator/defs/run_contracts/"
        "cn_a_derived_minute_bars.py",
        repository_root
        / "lake_console/docs/design/dagster-gold-wealth-market-turnover-dataset-low-level-design.md",
    )


def _content_fingerprint(path: Path) -> dict[str, object]:
    return {**_required_file_fingerprint(path), "sha256": _sha256_file(path)}


def _partition_from_path(path: Path) -> str:
    parent = path.parent.name
    if not parent.startswith("trade_date="):
        raise BseQfqRecoveryError(f"invalid adj factor path: {path}")
    return parent.removeprefix("trade_date=")


def _assert_staging_path(path: Path, *, lake_root: Path) -> None:
    staging_root = Path("/Volumes/datasource/data_lake_staging").resolve()
    if not path.is_relative_to(staging_root):
        raise BseQfqRecoveryError("R3 plan root must remain in formal staging")
    if path.is_relative_to(lake_root):
        raise BseQfqRecoveryError("R3 staging cannot be inside formal lake")


def _load_checkpoint(path: Path, *, plan_hash: str, row_field: str) -> dict[str, object]:
    if not path.exists():
        return {
            "r3_plan_hash": plan_hash,
            "completed_batches": [],
            row_field: [],
            "in_progress": None,
        }
    payload = _read_json(path)
    if payload.get("r3_plan_hash") != plan_hash:
        raise BseQfqRecoveryError(f"checkpoint identity mismatch: {path}")
    rows = payload.get(row_field)
    if not isinstance(rows, list):
        raise BseQfqRecoveryError(f"checkpoint rows are invalid: {path}")
    return payload


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BseQfqRecoveryError(f"JSON is unreadable: {path}") from error
    if not isinstance(payload, dict):
        raise BseQfqRecoveryError(f"JSON payload must be an object: {path}")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zero_control_plane_writes() -> dict[str, int]:
    return {
        "dagster_events": 0,
        "dagster_runs": 0,
        "dynamic_partitions": 0,
    }


__all__ = [
    "BseQfqRecoveryError",
    "audit_bse_qfq_recovery_candidates",
    "build_bse_qfq_recovery_candidates",
    "plan_bse_qfq_recovery",
    "promote_bse_qfq_recovery_candidates",
]
