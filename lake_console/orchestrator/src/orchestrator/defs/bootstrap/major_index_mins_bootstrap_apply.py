"""Build and promote major-index minute Bootstrap files from retained source staging."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from time import perf_counter
from uuid import uuid4

from orchestrator.defs.bootstrap.major_index_mins_bootstrap_plan import (
    MajorIndexMinsDatePlan,
    MajorIndexMinsSourcePlan,
    MajorIndexMinsTargetAudit,
    audit_bootstrap_targets,
)
from orchestrator.defs.bootstrap.major_index_mins_bootstrap_stage import (
    MajorIndexMinsSourceStagingAudit,
    audit_source_staging,
    source_window_parquet_path,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.io.major_index_mins_quality import (
    prepare_major_index_mins_expected_tables,
    validate_major_index_mins_relation,
)
from orchestrator.defs.io.major_index_mins_silver_writer import (
    write_major_index_mins_silver_partition,
)
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_SILVER_FREQS,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
    effective_codes_for_date,
)


_REPORT_CHECKPOINT_SIZE = 20
_SAMPLE_LIMIT = 20


class MajorIndexMinsBootstrapApplyError(RuntimeError):
    """Raised when staged source cannot be safely built or promoted."""


@dataclass(frozen=True, slots=True)
class MajorIndexMinsBootstrapBuildReport:
    generated_at: str
    staging_root: str
    date_plan_fingerprint: str
    source_plan_fingerprint: str
    expected_raw_file_count: int
    expected_silver_file_count: int
    raw_written_count: int
    raw_reused_count: int
    silver_written_count: int
    silver_reused_count: int
    raw_row_count: int
    silver_row_count: int
    should_stop: bool
    stop_reason_codes: tuple[str, ...]
    elapsed_ms: float
    failure_samples: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "failure_samples": [dict(value) for value in self.failure_samples],
            "writes": {
                "temporary_raw": self.raw_written_count,
                "temporary_silver": self.silver_written_count,
                "formal_lake": 0,
                "dagster_db": 0,
                "dagster_events": 0,
            },
        }


@dataclass(frozen=True, slots=True)
class MajorIndexMinsBootstrapPromoteReport:
    generated_at: str
    staging_root: str
    formal_lake_root: str
    date_plan_fingerprint: str
    raw_promoted_count: int
    raw_reused_count: int
    silver_promoted_count: int
    silver_reused_count: int
    should_stop: bool
    stop_reason_codes: tuple[str, ...]
    elapsed_ms: float
    failure_samples: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "failure_samples": [dict(value) for value in self.failure_samples],
            "writes": {
                "formal_raw": self.raw_promoted_count,
                "formal_silver": self.silver_promoted_count,
                "dagster_db": 0,
                "dagster_events": 0,
            },
        }


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_paths_by_partition(
    *,
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
) -> Mapping[tuple[str, str], tuple[Path, ...]]:
    grouped: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for window in source_plan.windows:
        path = source_window_parquet_path(staging_root, date_plan, window)
        if not path.is_file():
            raise MajorIndexMinsBootstrapApplyError(
                f"source staging file is missing: {window.window_id}"
            )
        for trade_date in window.trade_dates:
            grouped[(window.source_freq, trade_date)].append(path)
    return {key: tuple(sorted(set(paths))) for key, paths in grouped.items()}


def _parquet_list(paths: tuple[Path, ...]) -> str:
    if not paths:
        raise MajorIndexMinsBootstrapApplyError("source path list is empty")
    return "[" + ", ".join(duckdb_string(path) for path in paths) + "]"


def _write_temporary_raw_partition(
    *,
    staging_root: Path,
    duckdb_resource: DuckDBResource,
    frequency: str,
    trade_date: str,
    source_paths: tuple[Path, ...],
) -> tuple[str, int]:
    target_path = raw_major_index_mins_path(staging_root, frequency, trade_date)
    expected_codes = effective_codes_for_date(trade_date)
    source_sql = (
        "SELECT "
        + ", ".join(f'"{column}"' for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS)
        + f" FROM read_parquet({_parquet_list(source_paths)}, hive_partitioning=false)"
        + f" WHERE CAST(trade_time AS DATE) = DATE {duckdb_string(trade_date)}"
        + " ORDER BY ts_code, trade_time"
    )
    with duckdb_resource.connect() as connection:
        prepare_major_index_mins_expected_tables(
            connection,
            expected_codes=expected_codes,
            frequency=frequency,
        )
        if target_path.exists():
            validation = validate_major_index_mins_relation(
                connection,
                relation_sql=read_parquet(target_path, hive_partitioning=False),
                expected_codes=expected_codes,
                frequency=frequency,
                partition_key=trade_date,
            )
            if validation.errors:
                raise MajorIndexMinsBootstrapApplyError(
                    f"invalid temporary Raw target cannot be overwritten: {target_path}"
                )
            return "reuse_existing", validation.row_count
        source_validation = validate_major_index_mins_relation(
            connection,
            relation_sql=source_sql,
            expected_codes=expected_codes,
            frequency=frequency,
            partition_key=trade_date,
        )
        if source_validation.errors:
            raise MajorIndexMinsBootstrapApplyError(
                "source staging cannot produce a valid Raw partition: "
                f"freq={frequency}, date={trade_date}, errors={source_validation.errors!r}"
            )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = target_path.with_name(f".{target_path.name}.{uuid4().hex}.tmp")
        try:
            connection.execute(copy_query_to_parquet(source_sql, temporary))
            staged_validation = validate_major_index_mins_relation(
                connection,
                relation_sql=read_parquet(temporary, hive_partitioning=False),
                expected_codes=expected_codes,
                frequency=frequency,
                partition_key=trade_date,
            )
            if (
                staged_validation.errors
                or staged_validation.row_count != source_validation.row_count
            ):
                raise MajorIndexMinsBootstrapApplyError(
                    f"temporary Raw readback failed: freq={frequency}, date={trade_date}"
                )
            if target_path.exists():
                raise MajorIndexMinsBootstrapApplyError(
                    f"temporary Raw target appeared during write: {target_path}"
                )
            os.replace(temporary, target_path)
        finally:
            temporary.unlink(missing_ok=True)
    return "staged_atomic_replace", source_validation.row_count


def build_temporary_lake_from_staging(
    *,
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
    duckdb_resource: DuckDBResource,
    output_path: Path,
) -> MajorIndexMinsBootstrapBuildReport:
    """Build Raw/Silver under staging_root without any source request."""

    started_at = perf_counter()
    source_audit = audit_source_staging(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=duckdb_resource,
    )
    if not source_audit.ready:
        raise MajorIndexMinsBootstrapApplyError(
            "source staging audit is not ready: "
            f"reasons={source_audit.stop_reason_codes!r}"
        )
    paths_by_partition = _source_paths_by_partition(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
    )
    raw_written = 0
    raw_reused = 0
    silver_written = 0
    silver_reused = 0
    raw_rows = 0
    silver_rows = 0
    failure_samples: list[Mapping[str, object]] = []

    def report(*, stopped: bool) -> MajorIndexMinsBootstrapBuildReport:
        return MajorIndexMinsBootstrapBuildReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            staging_root=str(staging_root),
            date_plan_fingerprint=date_plan.fingerprint,
            source_plan_fingerprint=source_plan.fingerprint,
            expected_raw_file_count=len(date_plan.expected_trade_dates)
            * len(MAJOR_INDEX_MINS_SOURCE_FREQS),
            expected_silver_file_count=len(date_plan.expected_trade_dates)
            * len(MAJOR_INDEX_MINS_SILVER_FREQS),
            raw_written_count=raw_written,
            raw_reused_count=raw_reused,
            silver_written_count=silver_written,
            silver_reused_count=silver_reused,
            raw_row_count=raw_rows,
            silver_row_count=silver_rows,
            should_stop=stopped,
            stop_reason_codes=("temporary_lake_build_failed",) if stopped else (),
            elapsed_ms=(perf_counter() - started_at) * 1000,
            failure_samples=tuple(failure_samples[:_SAMPLE_LIMIT]),
        )

    completed = 0
    try:
        for trade_date in date_plan.expected_trade_dates:
            for frequency in MAJOR_INDEX_MINS_SOURCE_FREQS:
                mode, row_count = _write_temporary_raw_partition(
                    staging_root=staging_root,
                    duckdb_resource=duckdb_resource,
                    frequency=frequency,
                    trade_date=trade_date,
                    source_paths=paths_by_partition.get((frequency, trade_date), ()),
                )
                raw_written += int(mode != "reuse_existing")
                raw_reused += int(mode == "reuse_existing")
                raw_rows += row_count
                completed += 1
                if completed % _REPORT_CHECKPOINT_SIZE == 0:
                    _atomic_write_json(output_path, report(stopped=False).to_dict())
        for trade_date in date_plan.expected_trade_dates:
            for frequency in MAJOR_INDEX_MINS_SILVER_FREQS:
                result = write_major_index_mins_silver_partition(
                    lake_root_path=staging_root,
                    duckdb_resource=duckdb_resource,
                    freq=frequency,
                    partition_key=trade_date,
                    run_id=f"bootstrap-{uuid4().hex}",
                )
                silver_written += int(result.write_mode != "reuse_existing")
                silver_reused += int(result.write_mode == "reuse_existing")
                silver_rows += result.output_row_count
                completed += 1
                if completed % _REPORT_CHECKPOINT_SIZE == 0:
                    _atomic_write_json(output_path, report(stopped=False).to_dict())
    except Exception as error:  # noqa: BLE001 - checkpoint and stop bounded build.
        failure_samples.append({"error_type": type(error).__name__})
        failed = report(stopped=True)
        _atomic_write_json(output_path, failed.to_dict())
        return failed
    completed_report = report(stopped=False)
    _atomic_write_json(output_path, completed_report.to_dict())
    return completed_report


def audit_temporary_lake(
    *,
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    duckdb_resource: DuckDBResource,
) -> tuple[MajorIndexMinsTargetAudit, ...]:
    with duckdb_resource.connect() as connection:
        return audit_bootstrap_targets(
            connection=connection,
            lake_root=staging_root,
            date_plan=date_plan,
        )


def write_target_audit(
    audits: tuple[MajorIndexMinsTargetAudit, ...],
    output_path: Path,
) -> None:
    _atomic_write_json(
        output_path,
        {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target_audits": [audit.to_dict() for audit in audits],
            "ready": all(
                audit.missing_count == 0 and audit.invalid_existing_count == 0
                for audit in audits
            ),
            "writes": {"formal_lake": 0, "dagster_db": 0, "dagster_events": 0},
        },
    )


def _copy_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        if source.stat().st_size != temporary.stat().st_size or _sha256_file(
            source
        ) != _sha256_file(temporary):
            raise MajorIndexMinsBootstrapApplyError(
                f"destination staging copy mismatch: {target}"
            )
        if target.exists():
            raise MajorIndexMinsBootstrapApplyError(
                f"formal target appeared during promote: {target}"
            )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def promote_temporary_lake(
    *,
    staging_root: Path,
    formal_lake_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
    duckdb_resource: DuckDBResource,
    output_path: Path,
) -> MajorIndexMinsBootstrapPromoteReport:
    """Copy validated temporary files to formal lake via destination-local replace."""

    started_at = perf_counter()
    source_audit: MajorIndexMinsSourceStagingAudit = audit_source_staging(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=duckdb_resource,
    )
    if not source_audit.ready:
        raise MajorIndexMinsBootstrapApplyError("source staging audit is not ready")
    temporary_audits = audit_temporary_lake(
        staging_root=staging_root,
        date_plan=date_plan,
        duckdb_resource=duckdb_resource,
    )
    if any(
        audit.missing_count or audit.invalid_existing_count
        for audit in temporary_audits
    ):
        raise MajorIndexMinsBootstrapApplyError("temporary lake audit is not ready")
    with duckdb_resource.connect() as connection:
        formal_audits = audit_bootstrap_targets(
            connection=connection,
            lake_root=formal_lake_root,
            date_plan=date_plan,
        )
    if any(audit.invalid_existing_count for audit in formal_audits):
        raise MajorIndexMinsBootstrapApplyError(
            "formal lake contains invalid targets; refusing overwrite"
        )

    raw_promoted = 0
    raw_reused = 0
    silver_promoted = 0
    silver_reused = 0
    failure_samples: list[Mapping[str, object]] = []
    try:
        for trade_date in date_plan.expected_trade_dates:
            for frequency in MAJOR_INDEX_MINS_SOURCE_FREQS:
                source = raw_major_index_mins_path(staging_root, frequency, trade_date)
                target = raw_major_index_mins_path(
                    formal_lake_root, frequency, trade_date
                )
                if target.exists():
                    if _sha256_file(source) != _sha256_file(target):
                        raise MajorIndexMinsBootstrapApplyError(
                            f"formal Raw target differs from staging: {target}"
                        )
                    raw_reused += 1
                else:
                    _copy_atomic(source, target)
                    raw_promoted += 1
            for frequency in MAJOR_INDEX_MINS_SILVER_FREQS:
                source = silver_major_index_mins_path(
                    staging_root, frequency, trade_date
                )
                target = silver_major_index_mins_path(
                    formal_lake_root, frequency, trade_date
                )
                if target.exists():
                    if _sha256_file(source) != _sha256_file(target):
                        raise MajorIndexMinsBootstrapApplyError(
                            f"formal Silver target differs from staging: {target}"
                        )
                    silver_reused += 1
                else:
                    _copy_atomic(source, target)
                    silver_promoted += 1
    except Exception as error:  # noqa: BLE001 - retain prior atomic files and stop.
        failure_samples.append({"error_type": type(error).__name__})
        stopped = True
    else:
        stopped = False
    if not stopped:
        with duckdb_resource.connect() as connection:
            post_audits = audit_bootstrap_targets(
                connection=connection,
                lake_root=formal_lake_root,
                date_plan=date_plan,
            )
        if any(
            audit.missing_count or audit.invalid_existing_count for audit in post_audits
        ):
            stopped = True
            failure_samples.append({"error_type": "post_promote_audit_failed"})
    report = MajorIndexMinsBootstrapPromoteReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        staging_root=str(staging_root),
        formal_lake_root=str(formal_lake_root),
        date_plan_fingerprint=date_plan.fingerprint,
        raw_promoted_count=raw_promoted,
        raw_reused_count=raw_reused,
        silver_promoted_count=silver_promoted,
        silver_reused_count=silver_reused,
        should_stop=stopped,
        stop_reason_codes=("formal_lake_promote_failed",) if stopped else (),
        elapsed_ms=(perf_counter() - started_at) * 1000,
        failure_samples=tuple(failure_samples),
    )
    _atomic_write_json(output_path, report.to_dict())
    return report


__all__ = [
    "MajorIndexMinsBootstrapApplyError",
    "MajorIndexMinsBootstrapBuildReport",
    "MajorIndexMinsBootstrapPromoteReport",
    "audit_temporary_lake",
    "build_temporary_lake_from_staging",
    "promote_temporary_lake",
    "write_target_audit",
]
