"""Offline, five-frequency replacement for one incomplete stk_mins Silver day.

This module is deliberately not registered in Dagster definitions. It is a
guarded recovery tool for one explicitly approved historical partition, not a
replacement for the normal Silver job or sensor path.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter

from orchestrator.defs.assets.stk_mins import write_silver_stk_mins_partition
from orchestrator.defs.checks.stk_mins_checks import (
    SilverStkMinsPartitionDiagnostics,
    evaluate_silver_stk_mins_partition_diagnostics,
)
from orchestrator.defs.paths import (
    raw_stk_mins_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS


SCHEMA_VERSION = 1
STK_MINS_SILVER_RECOVERY_FREQS = STK_MINS_FREQS


class StkMinsSilverReplaceFromRawError(RuntimeError):
    """Raised when an offline Silver replacement cannot prove its safety."""


@dataclass(frozen=True, slots=True)
class StkMinsSilverRecoveryFileFingerprint:
    logical_name: str
    path: str
    exists: bool
    size_bytes: int | None
    sha256: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StkMinsSilverStageRecord:
    freq: int
    file: StkMinsSilverRecoveryFileFingerprint
    row_count: int
    observed_columns: tuple[str, ...]
    diagnostics: SilverStkMinsPartitionDiagnostics

    def to_dict(self) -> dict[str, object]:
        return {
            "freq": self.freq,
            "file": self.file.to_dict(),
            "row_count": self.row_count,
            "observed_columns": list(self.observed_columns),
            "diagnostics": self.diagnostics.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class StkMinsSilverReplaceFromRawPlan:
    trade_date: str
    input_files: tuple[StkMinsSilverRecoveryFileFingerprint, ...]
    target_files: tuple[StkMinsSilverRecoveryFileFingerprint, ...]
    plan_fingerprint: str
    elapsed_ms: int
    stop_reasons: tuple[str, ...]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "recovery_kind": "stk_mins_silver_replace_from_raw",
            "read_only": True,
            "trade_date": self.trade_date,
            "input_files": [file.to_dict() for file in self.input_files],
            "target_files": [file.to_dict() for file in self.target_files],
            "plan_fingerprint": self.plan_fingerprint,
            "elapsed_ms": self.elapsed_ms,
            "should_stop": self.should_stop,
            "stop_reasons": list(self.stop_reasons),
        }


@dataclass(frozen=True, slots=True)
class StkMinsSilverReplaceFromRawApplyReport:
    trade_date: str
    plan_fingerprint: str
    recovery_run_id: str
    staged_files: tuple[StkMinsSilverStageRecord, ...]
    quarantine_manifest_path: str
    promoted_frequency_count: int
    elapsed_ms: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "recovery_kind": "stk_mins_silver_replace_from_raw",
            "trade_date": self.trade_date,
            "plan_fingerprint": self.plan_fingerprint,
            "recovery_run_id": self.recovery_run_id,
            "staged_files": [record.to_dict() for record in self.staged_files],
            "quarantine_manifest_path": self.quarantine_manifest_path,
            "promoted_frequency_count": self.promoted_frequency_count,
            "elapsed_ms": self.elapsed_ms,
        }


def plan_stk_mins_silver_replace_from_raw(
    *,
    lake_root: Path,
    trade_date: str,
) -> StkMinsSilverReplaceFromRawPlan:
    """Build a read-only, source-and-target-frozen Silver recovery plan."""

    _validate_trade_date(trade_date)
    started = perf_counter()
    input_files = _input_fingerprints(lake_root=lake_root, trade_date=trade_date)
    target_files = _target_fingerprints(lake_root=lake_root, trade_date=trade_date)
    stop_reasons = _plan_stop_reasons(
        input_files=input_files,
        target_files=target_files,
    )
    fingerprint_payload = {
        "schema_version": SCHEMA_VERSION,
        "trade_date": trade_date,
        "input_files": [file.to_dict() for file in input_files],
        "target_files": [file.to_dict() for file in target_files],
        "stop_reasons": list(stop_reasons),
    }
    return StkMinsSilverReplaceFromRawPlan(
        trade_date=trade_date,
        input_files=input_files,
        target_files=target_files,
        plan_fingerprint=_payload_hash(fingerprint_payload),
        elapsed_ms=int((perf_counter() - started) * 1000),
        stop_reasons=stop_reasons,
    )


def load_stk_mins_silver_replace_from_raw_plan(
    plan_report: Path,
) -> StkMinsSilverReplaceFromRawPlan:
    """Load a reviewed plan report without trusting an arbitrary apply payload."""

    try:
        payload = json.loads(plan_report.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StkMinsSilverReplaceFromRawError(
            f"Recovery plan report does not exist: {plan_report}"
        ) from error
    except json.JSONDecodeError as error:
        raise StkMinsSilverReplaceFromRawError(
            f"Recovery plan report is not valid JSON: {plan_report}"
        ) from error
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise StkMinsSilverReplaceFromRawError(
            "Unsupported recovery plan schema version."
        )
    if payload.get("recovery_kind") != "stk_mins_silver_replace_from_raw":
        raise StkMinsSilverReplaceFromRawError(
            "Plan report has the wrong recovery kind."
        )
    if payload.get("read_only") is not True:
        raise StkMinsSilverReplaceFromRawError(
            "Apply requires a read-only recovery plan."
        )
    if payload.get("should_stop"):
        raise StkMinsSilverReplaceFromRawError(
            f"Recovery plan has stop reasons: {payload.get('stop_reasons', [])}."
        )
    input_payload = payload.get("input_files")
    target_payload = payload.get("target_files")
    if not isinstance(input_payload, list) or not isinstance(target_payload, list):
        raise StkMinsSilverReplaceFromRawError(
            "Recovery plan has invalid file evidence."
        )
    return StkMinsSilverReplaceFromRawPlan(
        trade_date=str(payload["trade_date"]),
        input_files=_parse_file_fingerprints(input_payload),
        target_files=_parse_file_fingerprints(target_payload),
        plan_fingerprint=str(payload["plan_fingerprint"]),
        elapsed_ms=int(payload.get("elapsed_ms", 0)),
        stop_reasons=tuple(str(item) for item in payload.get("stop_reasons", ())),
    )


def apply_stk_mins_silver_replace_from_raw(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    plan: StkMinsSilverReplaceFromRawPlan,
    expected_plan_fingerprint: str,
    confirm_apply: bool,
    recovery_run_id: str | None = None,
) -> StkMinsSilverReplaceFromRawApplyReport:
    """Stage, quarantine and replace all five Silver files as one operation."""

    if not confirm_apply:
        raise StkMinsSilverReplaceFromRawError(
            "Apply requires explicit confirm_apply=True."
        )
    if plan.should_stop:
        raise StkMinsSilverReplaceFromRawError("Apply refuses a stopped recovery plan.")
    if plan.plan_fingerprint != expected_plan_fingerprint:
        raise StkMinsSilverReplaceFromRawError(
            "Approved recovery plan fingerprint mismatch."
        )

    started = perf_counter()
    fresh_plan = plan_stk_mins_silver_replace_from_raw(
        lake_root=lake_root,
        trade_date=plan.trade_date,
    )
    if fresh_plan.should_stop:
        raise StkMinsSilverReplaceFromRawError(
            f"Fresh recovery plan has stop reasons: {list(fresh_plan.stop_reasons)}."
        )
    if fresh_plan.plan_fingerprint != expected_plan_fingerprint:
        raise StkMinsSilverReplaceFromRawError(
            "Recovery plan is stale; regenerate and review a new plan before apply."
        )

    run_id = recovery_run_id or str(uuid.uuid4())
    staging_root = _staging_root(
        lake_root=lake_root,
        run_id=run_id,
    )
    quarantine_root = _quarantine_root(
        lake_root=lake_root,
        trade_date=plan.trade_date,
        run_id=run_id,
    )
    target_paths = {
        freq: silver_stk_mins_path(lake_root, freq, plan.trade_date)
        for freq in STK_MINS_SILVER_RECOVERY_FREQS
    }
    stage_paths = {
        freq: staging_root
        / f"freq={freq}"
        / f"trade_date={plan.trade_date}"
        / "part-000.parquet"
        for freq in STK_MINS_SILVER_RECOVERY_FREQS
    }
    _assert_same_volume(lake_root=lake_root, target_paths=target_paths.values())
    if staging_root.exists() or quarantine_root.exists():
        raise StkMinsSilverReplaceFromRawError(
            f"Recovery run id already has staging or quarantine state: {run_id}."
        )

    stage_records: list[StkMinsSilverStageRecord] = []
    try:
        for freq in STK_MINS_SILVER_RECOVERY_FREQS:
            write_result = write_silver_stk_mins_partition(
                lake_root=lake_root,
                duckdb=duckdb,
                freq=freq,
                partition_key=plan.trade_date,
                output_path_override=stage_paths[freq],
            )
            diagnostics = evaluate_silver_stk_mins_partition_diagnostics(
                lake_root=lake_root,
                duckdb=duckdb,
                freq=freq,
                partition_key=plan.trade_date,
                silver_path=stage_paths[freq],
            )
            if not diagnostics.passed:
                raise StkMinsSilverReplaceFromRawError(
                    "Staged Silver file failed current rule diagnostics: "
                    f"freq={freq}, failed_rules={list(diagnostics.failed_rule_names)}."
                )
            stage_records.append(
                StkMinsSilverStageRecord(
                    freq=freq,
                    file=_file_fingerprint(
                        logical_name=f"silver_stage:{freq}",
                        path=stage_paths[freq],
                    ),
                    row_count=write_result.row_count,
                    observed_columns=write_result.observed_columns,
                    diagnostics=diagnostics,
                )
            )

        post_stage_plan = plan_stk_mins_silver_replace_from_raw(
            lake_root=lake_root,
            trade_date=plan.trade_date,
        )
        if post_stage_plan.should_stop:
            raise StkMinsSilverReplaceFromRawError(
                "Inputs or targets changed while staging: "
                f"{list(post_stage_plan.stop_reasons)}."
            )
        if post_stage_plan.plan_fingerprint != expected_plan_fingerprint:
            raise StkMinsSilverReplaceFromRawError(
                "Inputs or targets changed while staging; regenerate the recovery plan."
            )
    except Exception:
        _remove_tree(staging_root)
        raise

    manifest_path = quarantine_root / "manifest.json"
    quarantine_root.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "recovery_kind": "stk_mins_silver_replace_from_raw",
        "trade_date": plan.trade_date,
        "recovery_run_id": run_id,
        "plan_fingerprint": expected_plan_fingerprint,
        "status": "staged",
        "input_files": [file.to_dict() for file in fresh_plan.input_files],
        "target_files_before": [file.to_dict() for file in fresh_plan.target_files],
        "staged_files": [record.to_dict() for record in stage_records],
        "backup_paths": {
            str(freq): str(_backup_path(quarantine_root, freq, plan.trade_date))
            for freq in STK_MINS_SILVER_RECOVERY_FREQS
        },
    }
    _write_json(manifest_path, manifest)

    backed_up: list[int] = []
    promoted: list[int] = []
    try:
        for freq in STK_MINS_SILVER_RECOVERY_FREQS:
            backup_path = _backup_path(quarantine_root, freq, plan.trade_date)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target_paths[freq], backup_path)
            backed_up.append(freq)
        manifest["status"] = "backed_up"
        _write_json(manifest_path, manifest)

        for freq in STK_MINS_SILVER_RECOVERY_FREQS:
            os.replace(stage_paths[freq], target_paths[freq])
            promoted.append(freq)
        _assert_promoted_files(target_paths=target_paths, stage_records=stage_records)
        manifest["status"] = "promoted"
        manifest["promoted_frequencies"] = promoted
        _write_json(manifest_path, manifest)
    except Exception as error:
        rollback_errors = _restore_backups(
            target_paths=target_paths,
            quarantine_root=quarantine_root,
            backed_up=backed_up,
            trade_date=plan.trade_date,
        )
        manifest["status"] = "rolled_back" if not rollback_errors else "rollback_failed"
        manifest["promoted_frequencies"] = promoted
        manifest["rollback_errors"] = rollback_errors
        manifest["apply_error"] = type(error).__name__
        _write_json(manifest_path, manifest)
        _remove_tree(staging_root)
        if rollback_errors:
            raise StkMinsSilverReplaceFromRawError(
                "Recovery promote failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from error
        raise StkMinsSilverReplaceFromRawError(
            "Recovery promote failed; all previously moved Silver files were restored."
        ) from error

    _remove_tree(staging_root)
    return StkMinsSilverReplaceFromRawApplyReport(
        trade_date=plan.trade_date,
        plan_fingerprint=expected_plan_fingerprint,
        recovery_run_id=run_id,
        staged_files=tuple(stage_records),
        quarantine_manifest_path=str(manifest_path),
        promoted_frequency_count=len(promoted),
        elapsed_ms=int((perf_counter() - started) * 1000),
    )


def _input_fingerprints(
    *,
    lake_root: Path,
    trade_date: str,
) -> tuple[StkMinsSilverRecoveryFileFingerprint, ...]:
    raw_files = tuple(
        _file_fingerprint(
            logical_name=f"raw_stk_mins:{freq}",
            path=raw_stk_mins_path(lake_root, freq, trade_date),
        )
        for freq in STK_MINS_SILVER_RECOVERY_FREQS
    )
    reference_files = (
        _file_fingerprint(
            logical_name="silver_stock_identity_map",
            path=silver_stock_identity_map_path(lake_root),
        ),
        _file_fingerprint(
            logical_name="silver_stock_daily",
            path=silver_stock_daily_path(lake_root, trade_date),
        ),
        _file_fingerprint(
            logical_name="silver_stock_suspend_daily",
            path=silver_stock_suspend_daily_path(lake_root, trade_date),
        ),
        _file_fingerprint(
            logical_name="silver_stock_lifecycle",
            path=silver_stock_lifecycle_path(lake_root),
        ),
    )
    return (*raw_files, *reference_files)


def _target_fingerprints(
    *,
    lake_root: Path,
    trade_date: str,
) -> tuple[StkMinsSilverRecoveryFileFingerprint, ...]:
    return tuple(
        _file_fingerprint(
            logical_name=f"silver_target:{freq}",
            path=silver_stk_mins_path(lake_root, freq, trade_date),
        )
        for freq in STK_MINS_SILVER_RECOVERY_FREQS
    )


def _plan_stop_reasons(
    *,
    input_files: Sequence[StkMinsSilverRecoveryFileFingerprint],
    target_files: Sequence[StkMinsSilverRecoveryFileFingerprint],
) -> tuple[str, ...]:
    reasons: list[str] = []
    for file in (*input_files, *target_files):
        if not file.exists:
            reasons.append(f"missing_file:{file.logical_name}")
        elif file.size_bytes is None or file.size_bytes <= 0:
            reasons.append(f"empty_file:{file.logical_name}")
        elif not file.sha256:
            reasons.append(f"file_fingerprint_missing:{file.logical_name}")
    return tuple(reasons)


def _file_fingerprint(
    *,
    logical_name: str,
    path: Path,
) -> StkMinsSilverRecoveryFileFingerprint:
    if not path.exists() or not path.is_file():
        return StkMinsSilverRecoveryFileFingerprint(
            logical_name=logical_name,
            path=str(path),
            exists=False,
            size_bytes=None,
            sha256=None,
        )
    return StkMinsSilverRecoveryFileFingerprint(
        logical_name=logical_name,
        path=str(path),
        exists=True,
        size_bytes=path.stat().st_size,
        sha256=_sha256_path(path),
    )


def _parse_file_fingerprints(
    values: Sequence[object],
) -> tuple[StkMinsSilverRecoveryFileFingerprint, ...]:
    fingerprints: list[StkMinsSilverRecoveryFileFingerprint] = []
    for item in values:
        if not isinstance(item, Mapping):
            raise StkMinsSilverReplaceFromRawError(
                "Recovery plan contains an invalid file entry."
            )
        fingerprints.append(
            StkMinsSilverRecoveryFileFingerprint(
                logical_name=str(item["logical_name"]),
                path=str(item["path"]),
                exists=bool(item["exists"]),
                size_bytes=(
                    int(item["size_bytes"])
                    if item.get("size_bytes") is not None
                    else None
                ),
                sha256=str(item["sha256"]) if item.get("sha256") is not None else None,
            )
        )
    return tuple(fingerprints)


def _assert_same_volume(*, lake_root: Path, target_paths: Sequence[Path]) -> None:
    lake_device = lake_root.stat().st_dev
    for target_path in target_paths:
        if target_path.parent.stat().st_dev != lake_device:
            raise StkMinsSilverReplaceFromRawError(
                f"Target path is not on the lake volume: {target_path}"
            )


def _assert_promoted_files(
    *,
    target_paths: Mapping[int, Path],
    stage_records: Sequence[StkMinsSilverStageRecord],
) -> None:
    staged_by_freq = {record.freq: record for record in stage_records}
    for freq in STK_MINS_SILVER_RECOVERY_FREQS:
        record = staged_by_freq.get(freq)
        if record is None:
            raise StkMinsSilverReplaceFromRawError(
                f"Staging record missing for frequency {freq}."
            )
        target_fingerprint = _file_fingerprint(
            logical_name=f"silver_target:{freq}",
            path=target_paths[freq],
        )
        if (
            not target_fingerprint.exists
            or target_fingerprint.sha256 != record.file.sha256
            or target_fingerprint.size_bytes != record.file.size_bytes
        ):
            raise StkMinsSilverReplaceFromRawError(
                f"Promoted Silver file does not match validated staging output: freq={freq}."
            )


def _staging_root(*, lake_root: Path, run_id: str) -> Path:
    return (
        lake_root
        / "silver"
        / "quote"
        / "stk_mins"
        / "_staging"
        / f"recovery_run_id={run_id}"
    )


def _quarantine_root(*, lake_root: Path, trade_date: str, run_id: str) -> Path:
    return (
        lake_root
        / "_quarantine"
        / "stk_mins_silver_replace_from_raw"
        / f"trade_date={trade_date}"
        / f"recovery_run_id={run_id}"
    )


def _backup_path(quarantine_root: Path, freq: int, trade_date: str) -> Path:
    return (
        quarantine_root
        / f"freq={freq}"
        / f"trade_date={trade_date}"
        / "part-000.parquet"
    )


def _restore_backups(
    *,
    target_paths: Mapping[int, Path],
    quarantine_root: Path,
    backed_up: Sequence[int],
    trade_date: str,
) -> list[str]:
    errors: list[str] = []
    for freq in reversed(tuple(backed_up)):
        backup_path = _backup_path(quarantine_root, freq, trade_date)
        try:
            if not backup_path.exists():
                raise FileNotFoundError(f"Missing backup file: {backup_path}")
            os.replace(backup_path, target_paths[freq])
        except Exception as error:  # pragma: no cover - defensive rollback path
            errors.append(f"freq={freq}:{type(error).__name__}:{error}")
    return errors


def _validate_trade_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise StkMinsSilverReplaceFromRawError(
            "trade_date must use YYYY-MM-DD format."
        ) from error


def _payload_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
