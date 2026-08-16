"""Controlled projection migration for stock daily QFQ nine-turn history."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.column_schema import ColumnContract

SCHEMA_VERSION = 1
PLAN_PHASE = "stock_daily_qfq_nineturn_no_price_plan"
AUDIT_PHASE = "stock_daily_qfq_nineturn_no_price_candidate_audit"
FORMAL_AUDIT_PHASE = "stock_daily_qfq_nineturn_no_price_formal_audit"
CHECKPOINT_PHASE = "stock_daily_qfq_nineturn_no_price_promotion_checkpoint"
CONTRACT = "stock_daily_qfq_nineturn_v2_no_price"
DATASET_RELATIVE_ROOT = Path("gold/indicator/stock_daily_qfq_nineturn")
DUCKDB_MEMORY_LIMIT = "2GB"
DUCKDB_THREADS = 1
MAX_BATCH_SECONDS = 300.0
MAX_RSS_BYTES = 16 * 1024**3
MAX_SAMPLE_PARTITIONS = 3
MIN_FREE_HEADROOM_BYTES = 1024**3
MAX_FAILURE_SAMPLES = 20
FORBIDDEN_LEGACY_LAKE_ROOT = Path(
    "/Volumes/datasource/goldenshare-tushare-lake"
)

LEGACY_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "标准股票代码"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("close_qfq", "DOUBLE", "已废止的冗余前复权收盘价"),
    ColumnContract("up_count", "INTEGER", "连续上九转计数"),
    ColumnContract("down_count", "INTEGER", "连续下九转计数"),
    ColumnContract("nine_up_turn", "VARCHAR", "上九转信号，+9 或空"),
    ColumnContract("nine_down_turn", "VARCHAR", "下九转信号，-9 或空"),
)
BUSINESS_COLUMNS = tuple(
    column.name for column in GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA
)


class StockDailyQfqNineTurnNoPriceError(RuntimeError):
    """Raised when a projection-migration gate fails."""


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnNoPricePartition:
    partition_key: str
    year: int
    relative_path: str
    source_size: int
    source_mtime_ns: int
    source_sha256: str
    row_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnNoPricePlan:
    report_path: Path
    lake_root: Path
    staging_root: Path
    phase_root: Path
    candidate_lake_root: Path
    plan_hash: str
    partitions: tuple[StockDailyQfqNineTurnNoPricePartition, ...]
    stop_reasons: tuple[str, ...]
    report: Mapping[str, object]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    def to_summary_dict(self) -> dict[str, object]:
        return {
            "phase": PLAN_PHASE,
            "read_only": True,
            "report_path": str(self.report_path),
            "plan_hash": self.plan_hash,
            "partition_count": len(self.partitions),
            "row_count": sum(item.row_count for item in self.partitions),
            "first_partition_key": (
                self.partitions[0].partition_key if self.partitions else None
            ),
            "last_partition_key": (
                self.partitions[-1].partition_key if self.partitions else None
            ),
            "should_stop": self.should_stop,
            "stop_reasons": list(self.stop_reasons),
        }


def plan_stock_daily_qfq_nineturn_no_price_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
    duckdb_resource: DuckDBResource,
    writer_stopped: bool,
    output_dir: Path = Path("/private/tmp"),
) -> StockDailyQfqNineTurnNoPricePlan:
    """Read and freeze the legacy seven-column scope without writing candidates."""

    started = time.perf_counter()
    normalized_lake_root, normalized_staging_root = _validate_roots(
        lake_root=lake_root,
        staging_root=staging_root,
    )
    source_root = normalized_lake_root / DATASET_RELATIVE_ROOT
    source_paths = tuple(sorted(source_root.glob("trade_date=*/part-000.parquet")))
    parquet_paths = tuple(sorted(source_root.glob("trade_date=*/*.parquet")))
    stop_reasons: list[str] = []
    if not writer_stopped:
        stop_reasons.append("writer_not_stopped")
    if not source_paths:
        stop_reasons.append("empty_formal_scope")
    if any(path.is_symlink() for path in source_paths):
        stop_reasons.append("symlinked_formal_file")
    unexpected_paths = tuple(path for path in parquet_paths if path not in source_paths)
    if unexpected_paths:
        stop_reasons.append("unexpected_formal_file")

    grouped: dict[int, list[tuple[str, Path]]] = {}
    for path in source_paths:
        partition_key = path.parent.name.removeprefix("trade_date=")
        try:
            normalized_date = date.fromisoformat(partition_key).isoformat()
        except ValueError:
            stop_reasons.append(f"invalid_partition_path:{partition_key}")
            continue
        grouped.setdefault(int(normalized_date[:4]), []).append(
            (normalized_date, path)
        )

    partitions: list[StockDailyQfqNineTurnNoPricePartition] = []
    annual_audits: list[dict[str, object]] = []
    for year, entries in sorted(grouped.items()):
        batch_started = time.perf_counter()
        with duckdb_resource.connect() as connection:
            _configure_duckdb(connection)
            audit = _audit_paths(
                connection,
                entries=entries,
                expected_schema=LEGACY_SCHEMA,
            )
        batch_seconds = time.perf_counter() - batch_started
        audit["year"] = year
        audit["elapsed_seconds"] = round(batch_seconds, 3)
        annual_audits.append(audit)
        if audit["ready"] is not True:
            stop_reasons.append(f"year={year}:legacy_contract_failed")
        if batch_seconds > MAX_BATCH_SECONDS:
            stop_reasons.append(f"year={year}:audit_timeout")
        for partition_key, path in entries:
            stat = path.stat()
            partitions.append(
                StockDailyQfqNineTurnNoPricePartition(
                    partition_key=partition_key,
                    year=year,
                    relative_path=_relative_path(path, normalized_lake_root),
                    source_size=stat.st_size,
                    source_mtime_ns=stat.st_mtime_ns,
                    source_sha256=_sha256_path(path),
                    row_count=int(audit["row_counts"].get(partition_key, 0)),
                )
            )

    normalized_partitions = tuple(
        sorted(partitions, key=lambda item: item.partition_key)
    )
    if any(item.row_count <= 0 for item in normalized_partitions):
        stop_reasons.append("empty_partition")
    peak_rss_bytes = _peak_rss_bytes()
    if peak_rss_bytes > MAX_RSS_BYTES:
        stop_reasons.append("rss_limit_exceeded")
    source_bytes = sum(item.source_size for item in normalized_partitions)
    available_bytes = shutil.disk_usage(normalized_staging_root).free
    required_bytes = source_bytes + MIN_FREE_HEADROOM_BYTES
    if available_bytes < required_bytes:
        stop_reasons.append("insufficient_staging_space")
    if normalized_lake_root.stat().st_dev != normalized_staging_root.stat().st_dev:
        stop_reasons.append("lake_and_staging_not_same_filesystem")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT,
        "lake_root": str(normalized_lake_root),
        "staging_root": str(normalized_staging_root),
        "partitions": [item.to_dict() for item in normalized_partitions],
        "stop_reasons": sorted(set(stop_reasons)),
    }
    plan_hash = _hash_payload(payload)
    phase_root = normalized_staging_root / "stock_daily_qfq_nineturn_no_price" / plan_hash
    candidate_lake_root = phase_root / "candidate_lake"
    report = {
        **payload,
        "phase": PLAN_PHASE,
        "read_only": True,
        "planned_at": datetime.now(UTC).isoformat(),
        "plan_hash": plan_hash,
        "phase_root": str(phase_root),
        "candidate_lake_root": str(candidate_lake_root),
        "partition_count": len(normalized_partitions),
        "unexpected_file_count": len(unexpected_paths),
        "unexpected_file_samples": [
            _relative_path(path, normalized_lake_root)
            for path in unexpected_paths[:MAX_FAILURE_SAMPLES]
        ],
        "year_count": len(grouped),
        "row_count": sum(item.row_count for item in normalized_partitions),
        "source_bytes": source_bytes,
        "available_bytes": available_bytes,
        "required_bytes": required_bytes,
        "annual_audits": annual_audits,
        "duckdb_memory_limit": DUCKDB_MEMORY_LIMIT,
        "duckdb_threads": DUCKDB_THREADS,
        "max_batch_seconds": MAX_BATCH_SECONDS,
        "max_rss_bytes": MAX_RSS_BYTES,
        "observed_peak_rss_bytes": peak_rss_bytes,
        "should_stop": bool(stop_reasons),
        "write_counters": {
            "candidate_files": 0,
            "formal_lake": 0,
            "dagster_events": 0,
            "prod_rows": 0,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"stock_daily_qfq_nineturn_no_price_plan_{plan_hash}.json"
    _write_json_atomic(report_path, report)
    return StockDailyQfqNineTurnNoPricePlan(
        report_path=report_path,
        lake_root=normalized_lake_root,
        staging_root=normalized_staging_root,
        phase_root=phase_root,
        candidate_lake_root=candidate_lake_root,
        plan_hash=plan_hash,
        partitions=normalized_partitions,
        stop_reasons=tuple(sorted(set(stop_reasons))),
        report=report,
    )


def load_stock_daily_qfq_nineturn_no_price_plan(
    report_path: Path,
) -> StockDailyQfqNineTurnNoPricePlan:
    payload = _load_json(report_path)
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("phase") != PLAN_PHASE
        or payload.get("read_only") is not True
    ):
        raise StockDailyQfqNineTurnNoPriceError("Unsupported migration plan.")
    plan = StockDailyQfqNineTurnNoPricePlan(
        report_path=Path(report_path),
        lake_root=Path(str(payload["lake_root"])),
        staging_root=Path(str(payload["staging_root"])),
        phase_root=Path(str(payload["phase_root"])),
        candidate_lake_root=Path(str(payload["candidate_lake_root"])),
        plan_hash=str(payload["plan_hash"]),
        partitions=tuple(
            StockDailyQfqNineTurnNoPricePartition(**dict(item))
            for item in payload["partitions"]
        ),
        stop_reasons=tuple(str(item) for item in payload["stop_reasons"]),
        report=payload,
    )
    if _plan_hash(plan) != plan.plan_hash:
        raise StockDailyQfqNineTurnNoPriceError("Migration plan fingerprint changed.")
    return plan


def build_stock_daily_qfq_nineturn_no_price_candidates(
    *,
    plan: StockDailyQfqNineTurnNoPricePlan,
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource,
    mode: str,
    sample_partition_keys: Sequence[str] = (),
    confirm_build: bool,
) -> dict[str, object]:
    """Build six-column candidates by annual set-based projection."""

    if not confirm_build:
        raise StockDailyQfqNineTurnNoPriceError(
            "Candidate build requires explicit confirmation."
        )
    _assert_plan_ready(plan, expected_plan_hash)
    selected = _selected_partitions(
        plan,
        mode=mode,
        sample_partition_keys=sample_partition_keys,
    )
    _assert_source_preimages(plan, selected)
    started = time.perf_counter()
    results: list[dict[str, object]] = []
    for year in sorted({item.year for item in selected}):
        batch = tuple(item for item in selected if item.year == year)
        batch_started = time.perf_counter()
        export_root = plan.phase_root / "exports" / mode / f"year={year}"
        if export_root.exists():
            shutil.rmtree(export_root)
        export_root.parent.mkdir(parents=True, exist_ok=True)
        with duckdb_resource.connect() as connection:
            _configure_duckdb(connection)
            relation = _read_paths(
                tuple(plan.lake_root / item.relative_path for item in batch),
                union_by_name=False,
            )
            connection.execute(
                f"""
                COPY (
                  SELECT
                    ts_code,
                    trade_date,
                    up_count,
                    down_count,
                    nine_up_turn,
                    nine_down_turn,
                    strftime(trade_date, '%Y-%m-%d') AS __partition_trade_date
                  FROM {relation}
                  ORDER BY trade_date, ts_code
                ) TO {duckdb_string(export_root)} (
                  FORMAT PARQUET,
                  PARTITION_BY (__partition_trade_date),
                  FILENAME_PATTERN 'part-{{i}}',
                  OVERWRITE_OR_IGNORE
                )
                """
            )
        promoted = 0
        reused = 0
        for item in batch:
            exported = (
                export_root
                / f"__partition_trade_date={item.partition_key}"
                / "part-0.parquet"
            )
            candidate = _candidate_path(plan, item.partition_key)
            if not exported.is_file():
                raise StockDailyQfqNineTurnNoPriceError(
                    f"Missing projected candidate: {item.partition_key}."
                )
            candidate.parent.mkdir(parents=True, exist_ok=True)
            if candidate.is_file():
                if _sha256_path(candidate) != _sha256_path(exported):
                    raise StockDailyQfqNineTurnNoPriceError(
                        f"Existing candidate conflicts: {item.partition_key}."
                    )
                exported.unlink()
                reused += 1
            else:
                os.replace(exported, candidate)
                promoted += 1
        shutil.rmtree(export_root, ignore_errors=True)
        elapsed = time.perf_counter() - batch_started
        if elapsed > MAX_BATCH_SECONDS:
            raise StockDailyQfqNineTurnNoPriceError(
                f"Candidate batch exceeded five minutes: {year}."
            )
        _assert_rss_limit()
        results.append(
            {
                "year": year,
                "partition_count": len(batch),
                "row_count": sum(item.row_count for item in batch),
                "promoted_candidate_file_count": promoted,
                "reused_candidate_file_count": reused,
                "elapsed_seconds": round(elapsed, 3),
            }
        )
    report = {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT,
        "report_type": "stock_daily_qfq_nineturn_no_price_candidate_build",
        "plan_hash": plan.plan_hash,
        "mode": mode,
        "partition_keys": [item.partition_key for item in selected],
        "partition_count": len(selected),
        "row_count": sum(item.row_count for item in selected),
        "batches": results,
        "formal_lake_write_count": 0,
        "dagster_event_write_count": 0,
        "prod_write_count": 0,
        "observed_peak_rss_bytes": _peak_rss_bytes(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "should_stop": False,
    }
    report_path = plan.phase_root / f"candidate-build-{mode}.json"
    _write_json_atomic(report_path, report)
    return {**report, "report_path": str(report_path)}


def audit_stock_daily_qfq_nineturn_no_price_candidates(
    *,
    plan: StockDailyQfqNineTurnNoPricePlan,
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource,
    mode: str,
    sample_partition_keys: Sequence[str] = (),
) -> dict[str, object]:
    """Prove candidate keys, counts and signals equal the frozen legacy files."""

    _assert_plan_ready(plan, expected_plan_hash)
    selected = _selected_partitions(
        plan,
        mode=mode,
        sample_partition_keys=sample_partition_keys,
    )
    _assert_source_preimages(plan, selected)
    missing = tuple(
        item.partition_key
        for item in selected
        if not _candidate_path(plan, item.partition_key).is_file()
    )
    if missing:
        raise StockDailyQfqNineTurnNoPriceError(
            f"Candidate scope is incomplete: {missing[:MAX_FAILURE_SAMPLES]}."
        )
    started = time.perf_counter()
    annual_audits: list[dict[str, object]] = []
    manifest: list[dict[str, object]] = []
    stop_reasons: list[str] = []
    for year in sorted({item.year for item in selected}):
        batch = tuple(item for item in selected if item.year == year)
        source_entries = tuple(
            (item.partition_key, plan.lake_root / item.relative_path) for item in batch
        )
        candidate_entries = tuple(
            (item.partition_key, _candidate_path(plan, item.partition_key))
            for item in batch
        )
        batch_started = time.perf_counter()
        with duckdb_resource.connect() as connection:
            _configure_duckdb(connection)
            candidate_audit = _audit_paths(
                connection,
                entries=candidate_entries,
                expected_schema=GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
            )
            source_relation = _read_paths(
                tuple(path for _partition_key, path in source_entries),
                union_by_name=False,
            )
            candidate_relation = _read_paths(
                tuple(path for _partition_key, path in candidate_entries),
                union_by_name=False,
            )
            projection = ", ".join(BUSINESS_COLUMNS)
            source_minus_candidate, candidate_minus_source = (
                int(value or 0)
                for value in connection.execute(
                    f"""
                    SELECT
                      (SELECT count(*) FROM (
                        SELECT {projection} FROM {source_relation}
                        EXCEPT ALL
                        SELECT {projection} FROM {candidate_relation}
                      )),
                      (SELECT count(*) FROM (
                        SELECT {projection} FROM {candidate_relation}
                        EXCEPT ALL
                        SELECT {projection} FROM {source_relation}
                      ))
                    """
                ).fetchone()
            )
        elapsed = time.perf_counter() - batch_started
        ready = (
            candidate_audit["ready"] is True
            and source_minus_candidate == 0
            and candidate_minus_source == 0
            and elapsed <= MAX_BATCH_SECONDS
        )
        if not ready:
            stop_reasons.append(f"year={year}:candidate_audit_failed")
        annual_audits.append(
            {
                **candidate_audit,
                "year": year,
                "source_minus_candidate_count": source_minus_candidate,
                "candidate_minus_source_count": candidate_minus_source,
                "elapsed_seconds": round(elapsed, 3),
                "ready": ready,
            }
        )
        _assert_rss_limit()
        for item in batch:
            candidate = _candidate_path(plan, item.partition_key)
            manifest.append(
                {
                    "partition_key": item.partition_key,
                    "year": item.year,
                    "relative_path": item.relative_path,
                    "formal_path": str(plan.lake_root / item.relative_path),
                    "candidate_path": str(candidate),
                    "source_size": item.source_size,
                    "source_mtime_ns": item.source_mtime_ns,
                    "source_sha256": item.source_sha256,
                    "candidate_size": candidate.stat().st_size,
                    "candidate_sha256": _sha256_path(candidate),
                    "row_count": item.row_count,
                }
            )
    manifest_path = plan.phase_root / f"candidate-manifest-{mode}.json"
    _write_json_atomic(
        manifest_path,
        {
            "schema_version": SCHEMA_VERSION,
            "contract": CONTRACT,
            "plan_hash": plan.plan_hash,
            "mode": mode,
            "files": manifest,
        },
    )
    if _peak_rss_bytes() > MAX_RSS_BYTES:
        stop_reasons.append("rss_limit_exceeded")
    report = {
        "schema_version": SCHEMA_VERSION,
        "phase": AUDIT_PHASE,
        "contract": CONTRACT,
        "plan_hash": plan.plan_hash,
        "mode": mode,
        "partition_count": len(selected),
        "row_count": sum(item.row_count for item in selected),
        "annual_audits": annual_audits,
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256_path(manifest_path),
        "observed_peak_rss_bytes": _peak_rss_bytes(),
        "should_stop": bool(stop_reasons),
        "stop_reasons": sorted(set(stop_reasons)),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    report_path = plan.phase_root / f"candidate-audit-{mode}.json"
    _write_json_atomic(report_path, report)
    return {**report, "report_path": str(report_path)}


def promote_stock_daily_qfq_nineturn_no_price_candidates(
    *,
    plan: StockDailyQfqNineTurnNoPricePlan,
    expected_plan_hash: str,
    audit_report_path: Path,
    writer_stopped: bool,
    reader_stopped: bool,
    confirm_promote: bool,
) -> dict[str, object]:
    """Atomically replace formal files after a complete green candidate audit."""

    if not confirm_promote or not writer_stopped or not reader_stopped:
        raise StockDailyQfqNineTurnNoPriceError(
            "Promotion requires explicit confirmation and stopped writer/reader."
        )
    _assert_plan_ready(plan, expected_plan_hash)
    audit = _load_json(audit_report_path)
    if (
        audit.get("phase") != AUDIT_PHASE
        or audit.get("plan_hash") != plan.plan_hash
        or audit.get("mode") != "full"
        or audit.get("should_stop") is not False
    ):
        raise StockDailyQfqNineTurnNoPriceError(
            "A complete green full-scope candidate audit is required."
        )
    manifest_path = Path(str(audit["manifest_path"]))
    if _sha256_path(manifest_path) != str(audit["manifest_sha256"]):
        raise StockDailyQfqNineTurnNoPriceError("Candidate manifest changed.")
    manifest = _load_json(manifest_path)
    entries = tuple(dict(item) for item in manifest["files"])
    if len(entries) != len(plan.partitions):
        raise StockDailyQfqNineTurnNoPriceError("Promotion manifest is incomplete.")
    checkpoint_path = plan.phase_root / "promotion-checkpoint.json"
    checkpoint = _load_checkpoint(checkpoint_path, plan_hash=plan.plan_hash)
    completed = {str(item) for item in checkpoint["completed_relative_paths"]}
    started = time.perf_counter()
    promoted = 0
    for entry in entries:
        relative_path = str(entry["relative_path"])
        formal = Path(str(entry["formal_path"]))
        candidate = Path(str(entry["candidate_path"]))
        candidate_sha256 = str(entry["candidate_sha256"])
        if relative_path in completed:
            _assert_sha256(formal, candidate_sha256, label="promoted formal")
            continue
        _assert_source_entry_unchanged(formal, entry)
        _assert_sha256(candidate, candidate_sha256, label="candidate")
        formal.parent.mkdir(parents=True, exist_ok=True)
        os.replace(candidate, formal)
        _assert_sha256(formal, candidate_sha256, label="promoted formal")
        completed.add(relative_path)
        promoted += 1
        _write_json_atomic(
            checkpoint_path,
            {
                "schema_version": SCHEMA_VERSION,
                "phase": CHECKPOINT_PHASE,
                "plan_hash": plan.plan_hash,
                "completed_relative_paths": sorted(completed),
            },
        )
        _assert_rss_limit()
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_type": "stock_daily_qfq_nineturn_no_price_promotion",
        "plan_hash": plan.plan_hash,
        "promoted_file_count": promoted,
        "completed_file_count": len(completed),
        "remaining_file_count": len(entries) - len(completed),
        "checkpoint_path": str(checkpoint_path),
        "dagster_event_write_count": 0,
        "prod_write_count": 0,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "should_stop": False,
    }
    report_path = plan.phase_root / "promotion-report.json"
    _write_json_atomic(report_path, report)
    return {**report, "report_path": str(report_path)}


def audit_stock_daily_qfq_nineturn_no_price_formal(
    *,
    plan: StockDailyQfqNineTurnNoPricePlan,
    expected_plan_hash: str,
    candidate_audit_report_path: Path,
    duckdb_resource: DuckDBResource,
) -> dict[str, object]:
    """Verify all promoted files match the audited six-column candidates."""

    _assert_plan_ready(plan, expected_plan_hash)
    candidate_audit = _load_json(candidate_audit_report_path)
    if (
        candidate_audit.get("phase") != AUDIT_PHASE
        or candidate_audit.get("plan_hash") != plan.plan_hash
        or candidate_audit.get("mode") != "full"
        or candidate_audit.get("should_stop") is not False
    ):
        raise StockDailyQfqNineTurnNoPriceError("Formal audit requires full audit.")
    manifest_path = Path(str(candidate_audit["manifest_path"]))
    if _sha256_path(manifest_path) != str(candidate_audit["manifest_sha256"]):
        raise StockDailyQfqNineTurnNoPriceError("Candidate manifest changed.")
    entries = tuple(dict(item) for item in _load_json(manifest_path)["files"])
    hash_mismatches: list[str] = []
    candidate_residuals: list[str] = []
    for entry in entries:
        formal = Path(str(entry["formal_path"]))
        candidate = Path(str(entry["candidate_path"]))
        if not formal.is_file() or _sha256_path(formal) != str(
            entry["candidate_sha256"]
        ):
            hash_mismatches.append(str(entry["partition_key"]))
        if candidate.exists():
            candidate_residuals.append(str(entry["partition_key"]))
    annual_audits: list[dict[str, object]] = []
    for year in sorted({item.year for item in plan.partitions}):
        batch = tuple(item for item in plan.partitions if item.year == year)
        with duckdb_resource.connect() as connection:
            _configure_duckdb(connection)
            audit = _audit_paths(
                connection,
                entries=tuple(
                    (item.partition_key, plan.lake_root / item.relative_path)
                    for item in batch
                ),
                expected_schema=GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
            )
        annual_audits.append({**audit, "year": year})
    stop_reasons = []
    if hash_mismatches:
        stop_reasons.append("formal_hash_mismatch")
    if candidate_residuals:
        stop_reasons.append("candidate_residual")
    if any(item["ready"] is not True for item in annual_audits):
        stop_reasons.append("formal_contract_failed")
    report = {
        "schema_version": SCHEMA_VERSION,
        "phase": FORMAL_AUDIT_PHASE,
        "contract": CONTRACT,
        "plan_hash": plan.plan_hash,
        "partition_count": len(plan.partitions),
        "row_count": sum(item.row_count for item in plan.partitions),
        "hash_mismatch_count": len(hash_mismatches),
        "hash_mismatch_samples": hash_mismatches[:MAX_FAILURE_SAMPLES],
        "candidate_residual_count": len(candidate_residuals),
        "candidate_residual_samples": candidate_residuals[:MAX_FAILURE_SAMPLES],
        "annual_audits": annual_audits,
        "should_stop": bool(stop_reasons),
        "stop_reasons": stop_reasons,
    }
    report_path = plan.phase_root / "formal-audit.json"
    _write_json_atomic(report_path, report)
    return {**report, "report_path": str(report_path)}


def _audit_paths(
    connection: duckdb.DuckDBPyConnection,
    *,
    entries: Sequence[tuple[str, Path]],
    expected_schema: Sequence[ColumnContract],
) -> dict[str, Any]:
    if not entries:
        return {
            "ready": False,
            "row_count": 0,
            "row_counts": {},
            "schema_matches": False,
            "schema_mismatch_file_count": 0,
            "schema_mismatch_file_samples": [],
            "duplicate_key_count": 0,
            "null_key_count": 0,
            "partition_mismatch_count": 0,
            "invalid_value_count": 0,
        }
    paths = tuple(path for _partition_key, path in entries)
    relation = _read_paths(paths, union_by_name=True, filename=True)
    observed_schema = tuple(
        (str(row[0]), str(row[1]).upper())
        for row in connection.execute(
            f"DESCRIBE SELECT * EXCLUDE (filename) FROM {relation}"
        ).fetchall()
    )
    expected = tuple((column.name, column.type.upper()) for column in expected_schema)
    path_values = ", ".join(duckdb_string(path.resolve()) for path in paths)
    per_file_schemas = connection.execute(
        f"""
        SELECT
          file_name,
          list(name ORDER BY column_id),
          list(upper(duckdb_type) ORDER BY column_id)
        FROM parquet_schema([{path_values}])
        WHERE name != 'duckdb_schema'
        GROUP BY file_name
        ORDER BY file_name
        """
    ).fetchall()
    schema_mismatch_files = tuple(
        str(file_name)
        for file_name, names, types in per_file_schemas
        if tuple(zip(names, types, strict=True)) != expected
    )
    expected_values = ", ".join(
        f"({duckdb_string(path.resolve())}, DATE {duckdb_string(partition_key)})"
        for partition_key, path in entries
    )
    metrics = connection.execute(
        f"""
        WITH expected(filename, expected_trade_date) AS (
          VALUES {expected_values}
        ), rows AS (
          SELECT source.*, expected.expected_trade_date
          FROM {relation} source
          INNER JOIN expected USING (filename)
        )
        SELECT
          count(*),
          count(*) - count(DISTINCT (ts_code, trade_date)),
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''
              OR trade_date IS NULL
          ),
          count(*) FILTER (WHERE trade_date != expected_trade_date),
          count(*) FILTER (
            WHERE up_count IS NULL OR down_count IS NULL
              OR up_count < 0 OR down_count < 0
              OR (up_count > 0 AND down_count > 0)
              OR (nine_up_turn IS NOT NULL AND nine_up_turn != '+9')
              OR (nine_down_turn IS NOT NULL AND nine_down_turn != '-9')
              OR (nine_up_turn = '+9' AND up_count < 9)
              OR (nine_down_turn = '-9' AND down_count < 9)
              OR (nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL)
          )
        FROM rows
        """
    ).fetchone()
    row_counts = {
        str(partition_key): int(row_count)
        for partition_key, row_count in connection.execute(
            f"""
            SELECT strftime(trade_date, '%Y-%m-%d'), count(*)
            FROM {relation}
            GROUP BY trade_date
            ORDER BY trade_date
            """
        ).fetchall()
    }
    row_count, duplicates, nulls, partition_mismatches, invalids = (
        int(value or 0) for value in metrics
    )
    schema_matches = observed_schema == expected
    ready = (
        schema_matches
        and not schema_mismatch_files
        and row_count > 0
        and duplicates == 0
        and nulls == 0
        and partition_mismatches == 0
        and invalids == 0
        and set(row_counts) == {partition_key for partition_key, _path in entries}
    )
    return {
        "ready": ready,
        "row_count": row_count,
        "row_counts": row_counts,
        "schema_matches": schema_matches,
        "schema_mismatch_file_count": len(schema_mismatch_files),
        "schema_mismatch_file_samples": list(
            schema_mismatch_files[:MAX_FAILURE_SAMPLES]
        ),
        "observed_schema": observed_schema,
        "expected_schema": expected,
        "duplicate_key_count": duplicates,
        "null_key_count": nulls,
        "partition_mismatch_count": partition_mismatches,
        "invalid_value_count": invalids,
    }


def _selected_partitions(
    plan: StockDailyQfqNineTurnNoPricePlan,
    *,
    mode: str,
    sample_partition_keys: Sequence[str],
) -> tuple[StockDailyQfqNineTurnNoPricePartition, ...]:
    if mode == "full":
        if sample_partition_keys:
            raise StockDailyQfqNineTurnNoPriceError(
                "Full mode does not accept sample partitions."
            )
        return plan.partitions
    if mode != "sample":
        raise StockDailyQfqNineTurnNoPriceError("Mode must be sample or full.")
    normalized = tuple(dict.fromkeys(str(value) for value in sample_partition_keys))
    if not 1 <= len(normalized) <= MAX_SAMPLE_PARTITIONS:
        raise StockDailyQfqNineTurnNoPriceError(
            "Sample mode requires one to three explicit partitions."
        )
    by_key = {item.partition_key: item for item in plan.partitions}
    unknown = tuple(value for value in normalized if value not in by_key)
    if unknown:
        raise StockDailyQfqNineTurnNoPriceError(
            f"Sample partitions are outside the plan: {unknown}."
        )
    return tuple(by_key[value] for value in normalized)


def _assert_plan_ready(
    plan: StockDailyQfqNineTurnNoPricePlan,
    expected_plan_hash: str,
) -> None:
    if plan.plan_hash != expected_plan_hash or _plan_hash(plan) != plan.plan_hash:
        raise StockDailyQfqNineTurnNoPriceError("Reviewed plan hash mismatch.")
    if plan.should_stop:
        raise StockDailyQfqNineTurnNoPriceError(
            f"Plan has stop reasons: {plan.stop_reasons}."
        )


def _assert_source_preimages(
    plan: StockDailyQfqNineTurnNoPricePlan,
    partitions: Sequence[StockDailyQfqNineTurnNoPricePartition],
) -> None:
    for item in partitions:
        path = plan.lake_root / item.relative_path
        _assert_source_entry_unchanged(path, item.to_dict())


def _assert_source_entry_unchanged(
    path: Path,
    entry: Mapping[str, object],
) -> None:
    if not path.is_file() or path.is_symlink():
        raise StockDailyQfqNineTurnNoPriceError(f"Formal source is missing: {path}.")
    stat = path.stat()
    if (
        stat.st_size != int(entry["source_size"])
        or stat.st_mtime_ns != int(entry["source_mtime_ns"])
        or _sha256_path(path) != str(entry["source_sha256"])
    ):
        raise StockDailyQfqNineTurnNoPriceError(f"Formal source changed: {path}.")


def _candidate_path(
    plan: StockDailyQfqNineTurnNoPricePlan,
    partition_key: str,
) -> Path:
    return (
        plan.candidate_lake_root
        / DATASET_RELATIVE_ROOT
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )


def _validate_roots(*, lake_root: Path, staging_root: Path) -> tuple[Path, Path]:
    normalized_lake_root = Path(lake_root).resolve()
    normalized_staging_root = Path(staging_root).resolve()
    if not normalized_lake_root.is_dir() or not normalized_staging_root.is_dir():
        raise StockDailyQfqNineTurnNoPriceError(
            "Lake and staging roots must already exist."
        )
    forbidden_root = FORBIDDEN_LEGACY_LAKE_ROOT.resolve()
    if normalized_lake_root == forbidden_root or normalized_lake_root.is_relative_to(
        forbidden_root
    ):
        raise StockDailyQfqNineTurnNoPriceError(
            "The legacy Lake root is forbidden for this migration."
        )
    if normalized_lake_root == normalized_staging_root:
        raise StockDailyQfqNineTurnNoPriceError("Staging must be outside formal Lake.")
    if normalized_staging_root.is_relative_to(normalized_lake_root):
        raise StockDailyQfqNineTurnNoPriceError("Staging must be outside formal Lake.")
    if normalized_lake_root == Path(DEFAULT_LAKE_ROOT).resolve() and (
        normalized_staging_root != Path(DEFAULT_LAKE_STAGING_ROOT).resolve()
    ):
        raise StockDailyQfqNineTurnNoPriceError(
            "Formal Lake requires the fixed data_lake_staging root."
        )
    return normalized_lake_root, normalized_staging_root


def _configure_duckdb(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(f"SET memory_limit = '{DUCKDB_MEMORY_LIMIT}'")
    connection.execute(f"SET threads = {DUCKDB_THREADS}")
    connection.execute("SET preserve_insertion_order = false")


def _read_paths(
    paths: Sequence[Path],
    *,
    union_by_name: bool,
    filename: bool = False,
) -> str:
    if not paths:
        raise StockDailyQfqNineTurnNoPriceError("Parquet scope is empty.")
    values = ", ".join(duckdb_string(path.resolve()) for path in paths)
    return (
        f"read_parquet([{values}], hive_partitioning=false, "
        f"union_by_name={'true' if union_by_name else 'false'}, "
        f"filename={'true' if filename else 'false'})"
    )


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise StockDailyQfqNineTurnNoPriceError(
            f"Path is outside formal Lake: {path}."
        ) from error


def _plan_hash(plan: StockDailyQfqNineTurnNoPricePlan) -> str:
    return _hash_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "contract": CONTRACT,
            "lake_root": str(plan.lake_root.resolve()),
            "staging_root": str(plan.staging_root.resolve()),
            "partitions": [item.to_dict() for item in plan.partitions],
            "stop_reasons": list(plan.stop_reasons),
        }
    )


def _load_checkpoint(path: Path, *, plan_hash: str) -> dict[str, object]:
    if not path.exists():
        return {"completed_relative_paths": []}
    payload = _load_json(path)
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("phase") != CHECKPOINT_PHASE
        or payload.get("plan_hash") != plan_hash
    ):
        raise StockDailyQfqNineTurnNoPriceError(
            "Promotion checkpoint does not belong to the reviewed plan."
        )
    return payload


def _assert_sha256(path: Path, expected: str, *, label: str) -> None:
    if not path.is_file() or _sha256_path(path) != expected:
        raise StockDailyQfqNineTurnNoPriceError(f"{label} SHA-256 mismatch: {path}.")


def _assert_rss_limit() -> None:
    if _peak_rss_bytes() > MAX_RSS_BYTES:
        raise StockDailyQfqNineTurnNoPriceError("Process RSS exceeded 16GiB.")


def _peak_rss_bytes() -> int:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StockDailyQfqNineTurnNoPriceError(f"Expected JSON object: {path}.")
    return value


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


__all__ = [
    "AUDIT_PHASE",
    "BUSINESS_COLUMNS",
    "CONTRACT",
    "FORMAL_AUDIT_PHASE",
    "LEGACY_SCHEMA",
    "StockDailyQfqNineTurnNoPriceError",
    "StockDailyQfqNineTurnNoPricePartition",
    "StockDailyQfqNineTurnNoPricePlan",
    "audit_stock_daily_qfq_nineturn_no_price_candidates",
    "audit_stock_daily_qfq_nineturn_no_price_formal",
    "build_stock_daily_qfq_nineturn_no_price_candidates",
    "load_stock_daily_qfq_nineturn_no_price_plan",
    "plan_stock_daily_qfq_nineturn_no_price_history",
    "promote_stock_daily_qfq_nineturn_no_price_candidates",
]
