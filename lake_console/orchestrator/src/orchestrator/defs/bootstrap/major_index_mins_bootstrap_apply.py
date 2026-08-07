"""Build and promote major-index minute Bootstrap files from retained source staging."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from contextlib import contextmanager
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
    source_window_sidecar_path,
)
from orchestrator.defs.bootstrap.major_index_mins_silver_fallback import (
    major_index_mins_fallback_sample_path,
    write_major_index_mins_fallback_samples,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.io.major_index_mins_quality import (
    prepare_major_index_mins_raw_expected_tables,
    validate_major_index_mins_raw_relation,
)
from orchestrator.defs.io.major_index_mins_silver_writer import (
    write_major_index_mins_silver_partition,
    write_major_index_mins_silver_partition_with_historical_fallback,
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
    effective_raw_request_codes_for_date,
    major_index_mins_historical_fallback_fingerprint,
    major_index_mins_historical_fallback_rule,
)


_REPORT_CHECKPOINT_SIZE = 20
_SAMPLE_LIMIT = 20


class MajorIndexMinsBootstrapApplyError(RuntimeError):
    """Raised when staged source cannot be safely built or promoted."""


class _BorrowedDuckDBResource:
    """Expose one owned connection to serial Bootstrap partition writers."""

    def __init__(self, connection) -> None:
        self._connection = connection

    @contextmanager
    def connect(self):
        yield self._connection


@dataclass(frozen=True, slots=True)
class MajorIndexMinsBootstrapBuildReport:
    generated_at: str
    staging_root: str
    date_plan_fingerprint: str
    source_plan_fingerprint: str
    source_transport_ready: bool
    source_business_contract_ready: bool
    source_business_contract_reason_codes: tuple[str, ...]
    expected_raw_file_count: int
    expected_silver_file_count: int
    raw_written_count: int
    raw_reused_count: int
    silver_written_count: int
    silver_reused_count: int
    raw_row_count: int
    silver_row_count: int
    fallback_rule_fingerprint: str
    fallback_written_count: int
    fallback_reused_count: int
    fallback_output_row_count: int
    fallback_report_path: str
    checkpoint_resumed_raw_count: int
    checkpoint_resumed_silver_count: int
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
                "temporary_fallback_samples": self.fallback_written_count,
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
    source_audit_mode: str
    temporary_audit_mode: str
    validated_build_report_path: str | None
    validated_target_audit_report_path: str | None
    post_raw_valid_count: int
    post_raw_row_count: int
    post_raw_bytes: int
    post_silver_valid_count: int
    post_silver_row_count: int
    post_silver_bytes: int
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


def _load_json_report(path: Path, *, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MajorIndexMinsBootstrapApplyError(
            f"{label} is unreadable: {path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise MajorIndexMinsBootstrapApplyError(
            f"{label} must contain a JSON object: {path}"
        )
    return payload


def _report_has_zero_formal_writes(payload: Mapping[str, object]) -> bool:
    writes = payload.get("writes")
    if not isinstance(writes, Mapping):
        return False
    return all(
        int(writes.get(key, -1)) == 0
        for key in ("formal_lake", "dagster_db", "dagster_events")
    )


def _validate_reusable_temporary_audit(
    *,
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
    build_report_path: Path,
    target_audit_report_path: Path,
) -> None:
    build = _load_json_report(build_report_path, label="temporary build report")
    expected_raw_count = len(date_plan.expected_trade_dates) * len(
        MAJOR_INDEX_MINS_SOURCE_FREQS
    )
    expected_silver_count = len(date_plan.expected_trade_dates) * len(
        MAJOR_INDEX_MINS_SILVER_FREQS
    )
    if (
        bool(build.get("should_stop"))
        or not bool(build.get("source_transport_ready"))
        or str(build.get("staging_root")) != str(staging_root)
        or build.get("date_plan_fingerprint") != date_plan.fingerprint
        or build.get("source_plan_fingerprint") != source_plan.fingerprint
        or build.get("fallback_rule_fingerprint")
        != major_index_mins_historical_fallback_fingerprint()
        or int(build.get("expected_raw_file_count", -1)) != expected_raw_count
        or int(build.get("expected_silver_file_count", -1))
        != expected_silver_count
        or int(build.get("raw_written_count", -1))
        + int(build.get("raw_reused_count", -1))
        != expected_raw_count
        or int(build.get("silver_written_count", -1))
        + int(build.get("silver_reused_count", -1))
        != expected_silver_count
        or not _report_has_zero_formal_writes(build)
    ):
        raise MajorIndexMinsBootstrapApplyError(
            "temporary build report does not match the frozen Bootstrap plan"
        )

    build_report_mtime_ns = build_report_path.stat().st_mtime_ns
    for window in source_plan.windows:
        source_path = source_window_parquet_path(staging_root, date_plan, window)
        sidecar_path = source_window_sidecar_path(staging_root, date_plan, window)
        for path in (source_path, sidecar_path):
            if not path.is_file() or path.stat().st_mtime_ns > build_report_mtime_ns:
                raise MajorIndexMinsBootstrapApplyError(
                    f"source staging changed after temporary build: {path}"
                )

    audit = _load_json_report(
        target_audit_report_path,
        label="temporary target audit report",
    )
    target_audits = audit.get("target_audits")
    if not isinstance(target_audits, list):
        raise MajorIndexMinsBootstrapApplyError(
            "temporary target audit report has no target_audits"
        )
    audits_by_layer = {
        str(value.get("layer")): value
        for value in target_audits
        if isinstance(value, Mapping)
    }
    for layer, expected_count in (
        ("raw", expected_raw_count),
        ("silver", expected_silver_count),
    ):
        layer_audit = audits_by_layer.get(layer)
        if (
            layer_audit is None
            or int(layer_audit.get("expected_file_count", -1)) != expected_count
            or int(layer_audit.get("valid_existing_count", -1)) != expected_count
            or int(layer_audit.get("missing_count", -1)) != 0
            or int(layer_audit.get("invalid_existing_count", -1)) != 0
        ):
            raise MajorIndexMinsBootstrapApplyError(
                f"temporary target audit is not ready for layer={layer}"
            )
    if not bool(audit.get("ready")) or not _report_has_zero_formal_writes(audit):
        raise MajorIndexMinsBootstrapApplyError(
            "temporary target audit report is not a zero-write ready report"
        )

    audit_report_mtime_ns = target_audit_report_path.stat().st_mtime_ns
    for trade_date in date_plan.expected_trade_dates:
        for frequency in MAJOR_INDEX_MINS_SOURCE_FREQS:
            path = raw_major_index_mins_path(staging_root, frequency, trade_date)
            if not path.is_file() or path.stat().st_mtime_ns > audit_report_mtime_ns:
                raise MajorIndexMinsBootstrapApplyError(
                    f"temporary Raw target changed after audit: {path}"
                )
        for frequency in MAJOR_INDEX_MINS_SILVER_FREQS:
            path = silver_major_index_mins_path(staging_root, frequency, trade_date)
            if not path.is_file() or path.stat().st_mtime_ns > audit_report_mtime_ns:
                raise MajorIndexMinsBootstrapApplyError(
                    f"temporary Silver target changed after audit: {path}"
                )


def _load_build_checkpoint(
    *,
    output_path: Path,
    staging_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
) -> Mapping[str, object] | None:
    if not output_path.is_file():
        return None
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MajorIndexMinsBootstrapApplyError(
            f"temporary build checkpoint is unreadable: {output_path}"
        ) from error
    if (
        str(payload.get("staging_root")) != str(staging_root)
        or payload.get("date_plan_fingerprint") != date_plan.fingerprint
        or payload.get("source_plan_fingerprint") != source_plan.fingerprint
    ):
        raise MajorIndexMinsBootstrapApplyError(
            "temporary build checkpoint does not match the frozen plan."
        )
    return payload


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
    expected_codes = effective_raw_request_codes_for_date(trade_date)
    source_sql = (
        "SELECT "
        + ", ".join(f'"{column}"' for column in MAJOR_INDEX_MINS_SOURCE_COLUMNS)
        + f" FROM read_parquet({_parquet_list(source_paths)}, hive_partitioning=false)"
        + f" WHERE CAST(trade_time AS DATE) = DATE {duckdb_string(trade_date)}"
        + " ORDER BY ts_code, trade_time"
    )
    with duckdb_resource.connect() as connection:
        prepare_major_index_mins_raw_expected_tables(
            connection,
            expected_codes=expected_codes,
            frequency=frequency,
            partition_key=trade_date,
        )
        if target_path.exists():
            validation = validate_major_index_mins_raw_relation(
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
        source_validation = validate_major_index_mins_raw_relation(
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
            staged_validation = validate_major_index_mins_raw_relation(
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
    if not source_audit.transport_ready:
        raise MajorIndexMinsBootstrapApplyError(
            "source staging transport audit is not ready: "
            f"reasons={source_audit.transport_stop_reason_codes!r}"
        )
    paths_by_partition = _source_paths_by_partition(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
    )
    checkpoint = _load_build_checkpoint(
        output_path=output_path,
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
    )
    expected_raw_file_count = len(date_plan.expected_trade_dates) * len(
        MAJOR_INDEX_MINS_SOURCE_FREQS
    )
    expected_silver_file_count = len(date_plan.expected_trade_dates) * len(
        MAJOR_INDEX_MINS_SILVER_FREQS
    )
    resumed_raw = (
        int(checkpoint.get("raw_written_count", 0))
        + int(checkpoint.get("raw_reused_count", 0))
        if checkpoint is not None
        else 0
    )
    resumed_silver = (
        int(checkpoint.get("silver_written_count", 0))
        + int(checkpoint.get("silver_reused_count", 0))
        if checkpoint is not None
        else 0
    )
    if not 0 <= resumed_raw <= expected_raw_file_count:
        raise MajorIndexMinsBootstrapApplyError(
            "temporary build Raw checkpoint count is outside the frozen plan."
        )
    if resumed_raw < expected_raw_file_count and resumed_silver:
        raise MajorIndexMinsBootstrapApplyError(
            "temporary build checkpoint contains Silver before Raw completion."
        )
    if not 0 <= resumed_silver <= expected_silver_file_count:
        raise MajorIndexMinsBootstrapApplyError(
            "temporary build Silver checkpoint count is outside the frozen plan."
        )
    raw_written = 0
    raw_reused = resumed_raw
    silver_written = 0
    silver_reused = resumed_silver
    raw_rows = int(checkpoint.get("raw_row_count", 0)) if checkpoint else 0
    silver_rows = int(checkpoint.get("silver_row_count", 0)) if checkpoint else 0
    fallback_written = 0
    fallback_reused = 0
    fallback_rows = 0
    fallback_report_path = output_path.with_name(
        f"{output_path.stem}_fallback.json"
    )
    failure_samples: list[Mapping[str, object]] = []

    def report(*, stopped: bool) -> MajorIndexMinsBootstrapBuildReport:
        return MajorIndexMinsBootstrapBuildReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            staging_root=str(staging_root),
            date_plan_fingerprint=date_plan.fingerprint,
            source_plan_fingerprint=source_plan.fingerprint,
            source_transport_ready=source_audit.transport_ready,
            source_business_contract_ready=source_audit.business_contract_ready,
            source_business_contract_reason_codes=(
                source_audit.business_contract_reason_codes
            ),
            expected_raw_file_count=expected_raw_file_count,
            expected_silver_file_count=expected_silver_file_count,
            raw_written_count=raw_written,
            raw_reused_count=raw_reused,
            silver_written_count=silver_written,
            silver_reused_count=silver_reused,
            raw_row_count=raw_rows,
            silver_row_count=silver_rows,
            fallback_rule_fingerprint=(
                major_index_mins_historical_fallback_fingerprint()
            ),
            fallback_written_count=fallback_written,
            fallback_reused_count=fallback_reused,
            fallback_output_row_count=fallback_rows,
            fallback_report_path=str(fallback_report_path),
            checkpoint_resumed_raw_count=resumed_raw,
            checkpoint_resumed_silver_count=resumed_silver,
            should_stop=stopped,
            stop_reason_codes=("temporary_lake_build_failed",) if stopped else (),
            elapsed_ms=(perf_counter() - started_at) * 1000,
            failure_samples=tuple(failure_samples[:_SAMPLE_LIMIT]),
        )

    completed = resumed_raw + resumed_silver

    def execute_build(build_resource) -> None:
        nonlocal completed
        nonlocal fallback_reused, fallback_rows, fallback_written
        nonlocal raw_reused, raw_rows, raw_written
        nonlocal silver_reused, silver_rows, silver_written

        raw_partition_index = 0
        for trade_date in date_plan.expected_trade_dates:
            for frequency in MAJOR_INDEX_MINS_SOURCE_FREQS:
                if raw_partition_index < resumed_raw:
                    target_path = raw_major_index_mins_path(
                        staging_root,
                        frequency,
                        trade_date,
                    )
                    if not target_path.is_file():
                        raise MajorIndexMinsBootstrapApplyError(
                            "checkpointed temporary Raw file is missing: "
                            f"{target_path}"
                        )
                    raw_partition_index += 1
                    continue
                mode, row_count = _write_temporary_raw_partition(
                    staging_root=staging_root,
                    duckdb_resource=build_resource,
                    frequency=frequency,
                    trade_date=trade_date,
                    source_paths=paths_by_partition.get((frequency, trade_date), ()),
                )
                raw_written += int(mode != "reuse_existing")
                raw_reused += int(mode == "reuse_existing")
                raw_rows += row_count
                raw_partition_index += 1
                completed += 1
                if completed % _REPORT_CHECKPOINT_SIZE == 0:
                    _atomic_write_json(output_path, report(stopped=False).to_dict())

        fallback_report = write_major_index_mins_fallback_samples(
            staging_root=staging_root,
            output_root=staging_root,
            date_plan=date_plan,
            source_plan=source_plan,
            duckdb_resource=build_resource,
            output_path=fallback_report_path,
            run_id=f"bootstrap-{uuid4().hex}",
        )
        if fallback_report.should_stop:
            raise MajorIndexMinsBootstrapApplyError(
                "historical fallback sample build failed: "
                f"reasons={fallback_report.stop_reason_codes!r}"
            )
        fallback_written = fallback_report.written_count
        fallback_reused = fallback_report.reused_count
        fallback_rows = fallback_report.output_row_count

        silver_partition_index = 0
        for trade_date in date_plan.expected_trade_dates:
            for frequency in MAJOR_INDEX_MINS_SOURCE_FREQS:
                if silver_partition_index < resumed_silver:
                    target_path = silver_major_index_mins_path(
                        staging_root,
                        frequency,
                        trade_date,
                    )
                    if not target_path.is_file():
                        raise MajorIndexMinsBootstrapApplyError(
                            "checkpointed temporary Silver file is missing: "
                            f"{target_path}"
                        )
                    silver_partition_index += 1
                    continue
                fallback_rule = major_index_mins_historical_fallback_rule(
                    trade_date=trade_date,
                    target_freq=frequency,
                )
                if fallback_rule is None:
                    result = write_major_index_mins_silver_partition(
                        lake_root_path=staging_root,
                        duckdb_resource=build_resource,
                        freq=frequency,
                        partition_key=trade_date,
                        run_id=f"bootstrap-{uuid4().hex}",
                    )
                else:
                    result = (
                        write_major_index_mins_silver_partition_with_historical_fallback(
                            lake_root_path=staging_root,
                            duckdb_resource=build_resource,
                            freq=frequency,
                            partition_key=trade_date,
                            run_id=f"bootstrap-{uuid4().hex}",
                            historical_fallback_path=(
                                major_index_mins_fallback_sample_path(
                                    staging_root,
                                    target_freq=frequency,
                                    trade_date=trade_date,
                                )
                            ),
                            historical_fallback_codes=fallback_rule.target_codes,
                        )
                    )
                silver_written += int(result.write_mode != "reuse_existing")
                silver_reused += int(result.write_mode == "reuse_existing")
                silver_rows += result.output_row_count
                silver_partition_index += 1
                completed += 1
                if completed % _REPORT_CHECKPOINT_SIZE == 0:
                    _atomic_write_json(output_path, report(stopped=False).to_dict())
        for trade_date in date_plan.expected_trade_dates:
            for frequency in (
                value
                for value in MAJOR_INDEX_MINS_SILVER_FREQS
                if value not in MAJOR_INDEX_MINS_SOURCE_FREQS
            ):
                if silver_partition_index < resumed_silver:
                    target_path = silver_major_index_mins_path(
                        staging_root,
                        frequency,
                        trade_date,
                    )
                    if not target_path.is_file():
                        raise MajorIndexMinsBootstrapApplyError(
                            "checkpointed temporary Silver file is missing: "
                            f"{target_path}"
                        )
                    silver_partition_index += 1
                    continue
                result = write_major_index_mins_silver_partition(
                    lake_root_path=staging_root,
                    duckdb_resource=build_resource,
                    freq=frequency,
                    partition_key=trade_date,
                    run_id=f"bootstrap-{uuid4().hex}",
                )
                silver_written += int(result.write_mode != "reuse_existing")
                silver_reused += int(result.write_mode == "reuse_existing")
                silver_rows += result.output_row_count
                silver_partition_index += 1
                completed += 1
                if completed % _REPORT_CHECKPOINT_SIZE == 0:
                    _atomic_write_json(output_path, report(stopped=False).to_dict())

    try:
        with duckdb_resource.connect() as build_connection:
            execute_build(_BorrowedDuckDBResource(build_connection))
    except Exception as error:  # noqa: BLE001 - checkpoint and stop bounded build.
        failure_samples.append(
            {
                "error_type": type(error).__name__,
                "message": str(error)[:500],
            }
        )
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
    validated_build_report_path: Path | None = None,
    validated_target_audit_report_path: Path | None = None,
) -> MajorIndexMinsBootstrapPromoteReport:
    """Copy validated temporary files to formal lake via destination-local replace."""

    started_at = perf_counter()
    if (validated_build_report_path is None) != (
        validated_target_audit_report_path is None
    ):
        raise MajorIndexMinsBootstrapApplyError(
            "validated build and target audit reports must be provided together"
        )
    if validated_build_report_path is not None:
        assert validated_target_audit_report_path is not None
        _validate_reusable_temporary_audit(
            staging_root=staging_root,
            date_plan=date_plan,
            source_plan=source_plan,
            build_report_path=validated_build_report_path,
            target_audit_report_path=validated_target_audit_report_path,
        )
        source_audit_mode = "validated_build_report_reuse"
        temporary_audit_mode = "validated_report_reuse"
    else:
        source_audit: MajorIndexMinsSourceStagingAudit = audit_source_staging(
            staging_root=staging_root,
            date_plan=date_plan,
            source_plan=source_plan,
            duckdb_resource=duckdb_resource,
        )
        if not source_audit.transport_ready:
            raise MajorIndexMinsBootstrapApplyError(
                "source staging transport audit is not ready"
            )
        source_audit_mode = "live_deep_audit"
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
        temporary_audit_mode = "live_deep_audit"
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
    post_audits: tuple[MajorIndexMinsTargetAudit, ...] = ()
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
        source_audit_mode=source_audit_mode,
        temporary_audit_mode=temporary_audit_mode,
        validated_build_report_path=(
            str(validated_build_report_path)
            if validated_build_report_path is not None
            else None
        ),
        validated_target_audit_report_path=(
            str(validated_target_audit_report_path)
            if validated_target_audit_report_path is not None
            else None
        ),
        post_raw_valid_count=next(
            (
                audit.valid_existing_count
                for audit in post_audits
                if audit.layer == "raw"
            ),
            0,
        ),
        post_raw_row_count=next(
            (audit.existing_row_count for audit in post_audits if audit.layer == "raw"),
            0,
        ),
        post_raw_bytes=next(
            (audit.existing_bytes for audit in post_audits if audit.layer == "raw"),
            0,
        ),
        post_silver_valid_count=next(
            (
                audit.valid_existing_count
                for audit in post_audits
                if audit.layer == "silver"
            ),
            0,
        ),
        post_silver_row_count=next(
            (
                audit.existing_row_count
                for audit in post_audits
                if audit.layer == "silver"
            ),
            0,
        ),
        post_silver_bytes=next(
            (audit.existing_bytes for audit in post_audits if audit.layer == "silver"),
            0,
        ),
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
