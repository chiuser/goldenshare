"""Frozen plan, candidate build, and promotion for minute technical history."""

from __future__ import annotations

import hashlib
import json
import os
import resource as process_resource
import shutil
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import dagster as dg

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.major_index_mins_technical_writer import (
    MajorIndexMinsTechnicalValidationError,
    audit_major_index_mins_technical_relation,
    audit_major_index_mins_technical_state_relation,
    write_major_index_mins_technical_partition,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import (
    gold_major_index_mins_path,
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_state_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMN_TYPES,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMN_TYPES,
    INDICATOR_VERSION,
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    PARAMS_KEY,
    expected_major_index_mins_technical_codes,
)

FORMAL_LAKE_ROOT = Path("/Volumes/datasource/data_lake")
BOOTSTRAP_STAGING_ROOT = Path("/Volumes/datasource/data_lake_staging")
BOOTSTRAP_REPORT_ROOT = Path(
    "/private/tmp/goldenshare-bootstrap/major_index_mins_technical"
)
BOOTSTRAP_PRODUCT = "major_index_mins_technical"
BOOTSTRAP_BATCH_DATE_COUNT = 20
BOOTSTRAP_DISK_SAFETY_MULTIPLIER = 2.0
BOOTSTRAP_RECENT_CHECK_DATE_COUNT = 20
BOOTSTRAP_SAMPLE_DATE_COUNTS = (20, 60)
_ESTIMATED_OUTPUT_BYTES_PER_INPUT_BYTE = 0.45


class MajorIndexMinsTechnicalBootstrapError(RuntimeError):
    """Raised when minute history cannot proceed without a gap or overwrite."""


def _hash_payload(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _load_json(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MajorIndexMinsTechnicalBootstrapError(
            f"{label} is unreadable: {path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise MajorIndexMinsTechnicalBootstrapError(f"{label} must be a JSON object")
    return payload


@dataclass(frozen=True, slots=True)
class MinuteTechnicalInputFile:
    trade_date: str
    freq: int
    path: str
    row_count: int
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MinuteTechnicalBootstrapPlan:
    generated_at: str
    end_date: str
    source_lake_root: Path
    staging_root: Path
    report_root: Path
    trade_dates: tuple[str, ...]
    ignored_incomplete_tail_dates: tuple[str, ...]
    input_files: tuple[MinuteTechnicalInputFile, ...]
    source_manifest_hash: str
    object_pool_hash: str
    schema_contract_hash: str
    estimated_output_bytes: int
    disk_free_bytes: int
    plan_hash: str
    report_path: Path | None = None

    @property
    def candidate_root(self) -> Path:
        return (
            self.staging_root
            / "bootstrap"
            / BOOTSTRAP_PRODUCT
            / f"plan_hash={self.plan_hash}"
        )

    @property
    def performance_sample_root(self) -> Path:
        return (
            self.staging_root
            / "bootstrap"
            / BOOTSTRAP_PRODUCT
            / "performance_samples"
            / f"plan_hash={self.plan_hash}"
        )

    @property
    def disk_budget_passed(self) -> bool:
        return self.disk_free_bytes >= int(
            self.estimated_output_bytes * BOOTSTRAP_DISK_SAFETY_MULTIPLIER
        )

    def hash_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "product": BOOTSTRAP_PRODUCT,
            "end_date": self.end_date,
            "source_lake_root": str(self.source_lake_root),
            "staging_root": str(self.staging_root),
            "trade_dates": self.trade_dates,
            "input_files": [value.to_dict() for value in self.input_files],
            "source_manifest_hash": self.source_manifest_hash,
            "object_pool_hash": self.object_pool_hash,
            "schema_contract_hash": self.schema_contract_hash,
            "params_key": PARAMS_KEY,
            "indicator_version": INDICATOR_VERSION,
            "batch_date_count": BOOTSTRAP_BATCH_DATE_COUNT,
            "estimated_output_bytes": self.estimated_output_bytes,
            "disk_safety_multiplier": BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
            "recent_check_date_count": BOOTSTRAP_RECENT_CHECK_DATE_COUNT,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.hash_payload(),
            "generated_at": self.generated_at,
            "plan_hash": self.plan_hash,
            "report_path": str(self.report_path) if self.report_path else None,
            "candidate_root": str(self.candidate_root),
            "candidate_lake_root": str(self.candidate_root / "candidate_lake"),
            "candidate_run_staging_root": str(
                self.candidate_root / "candidate_run_staging"
            ),
            "performance_sample_root": str(self.performance_sample_root),
            "date_count": len(self.trade_dates),
            "ignored_incomplete_tail_dates": list(self.ignored_incomplete_tail_dates),
            "expected_candidate_file_count": len(self.trade_dates)
            * len(MAJOR_INDEX_MINS_TECHNICAL_FREQS)
            * 2,
            "disk_free_bytes": self.disk_free_bytes,
            "disk_budget_passed": self.disk_budget_passed,
            "writes": {
                "candidate_files": 0,
                "formal_lake": 0,
                "dagster_events": 0,
            },
        }


def _normalize_dates(values: Sequence[str], *, end_date: str) -> tuple[str, ...]:
    dates: set[str] = set()
    for value in values:
        try:
            normalized = date.fromisoformat(str(value).strip()).isoformat()
        except ValueError as error:
            raise MajorIndexMinsTechnicalBootstrapError(
                f"invalid minute partition date: {value!r}"
            ) from error
        if normalized <= end_date:
            dates.add(normalized)
    if not dates:
        raise MajorIndexMinsTechnicalBootstrapError(
            "no registered minute dates are at or before the explicit end date"
        )
    return tuple(sorted(dates))


def _complete_source_date(lake_root: Path, trade_date: str) -> bool:
    return all(
        gold_major_index_mins_path(lake_root, freq, trade_date).is_file()
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
    )


def _parquet_row_counts(
    *,
    paths_by_freq: Mapping[int, Sequence[Path]],
    duckdb_resource: DuckDBResource,
) -> dict[Path, int]:
    row_counts: dict[Path, int] = {}
    with duckdb_resource.connect() as connection:
        for paths in paths_by_freq.values():
            rows = connection.execute(
                """
                SELECT file_name, CAST(sum(num_rows) AS BIGINT) AS row_count
                FROM parquet_file_metadata(?)
                GROUP BY file_name
                """,
                [[str(path) for path in paths]],
            ).fetchall()
            row_counts.update(
                (Path(str(file_name)), int(row_count)) for file_name, row_count in rows
            )
    expected_paths = {path for paths in paths_by_freq.values() for path in paths}
    if set(row_counts) != expected_paths:
        missing = tuple(sorted(str(path) for path in expected_paths - set(row_counts)))
        extra = tuple(sorted(str(path) for path in set(row_counts) - expected_paths))
        raise MajorIndexMinsTechnicalBootstrapError(
            "Gold business-bar Parquet footer manifest does not match frozen inputs: "
            f"missing={missing[:20]!r}, extra={extra[:20]!r}"
        )
    return row_counts


def build_major_index_mins_technical_bootstrap_plan(
    *,
    end_date: str,
    instance: dg.DagsterInstance | None = None,
    registered_dates: Sequence[str] | None = None,
    source_lake_root: Path = FORMAL_LAKE_ROOT,
    staging_root: Path = BOOTSTRAP_STAGING_ROOT,
    report_root: Path = BOOTSTRAP_REPORT_ROOT,
    disk_free_bytes: int | None = None,
    duckdb_resource: DuckDBResource | None = None,
    write_report: bool = True,
) -> MinuteTechnicalBootstrapPlan:
    """Freeze the complete contiguous Gold business-bar history."""

    try:
        normalized_end = date.fromisoformat(str(end_date).strip()).isoformat()
    except ValueError as error:
        raise MajorIndexMinsTechnicalBootstrapError(
            f"invalid explicit end date: {end_date!r}"
        ) from error
    if date.fromisoformat(normalized_end) > datetime.now(timezone.utc).date():
        raise MajorIndexMinsTechnicalBootstrapError(
            "Bootstrap end date is in the future"
        )
    values = (
        tuple(registered_dates)
        if registered_dates is not None
        else tuple(
            (instance or dg.DagsterInstance.get()).get_dynamic_partitions(
                cn_major_index_mins_trade_days.name
            )
        )
    )
    registered = _normalize_dates(values, end_date=normalized_end)
    complete_flags = tuple(
        _complete_source_date(Path(source_lake_root), value) for value in registered
    )
    complete_indexes = tuple(
        index for index, complete in enumerate(complete_flags) if complete
    )
    if not complete_indexes:
        raise MajorIndexMinsTechnicalBootstrapError(
            "registered partitions contain no complete 7-frequency Gold date"
        )
    latest_complete_index = complete_indexes[-1]
    missing_middle = tuple(
        registered[index]
        for index in range(latest_complete_index + 1)
        if not complete_flags[index]
    )
    if missing_middle:
        raise MajorIndexMinsTechnicalBootstrapError(
            "Gold business-bar history contains an intermediate incomplete date: "
            f"samples={missing_middle[:20]!r}"
        )
    trade_dates = registered[: latest_complete_index + 1]
    ignored_tail = registered[latest_complete_index + 1 :]
    paths_by_freq = {
        freq: tuple(
            gold_major_index_mins_path(
                source_lake_root,
                freq,
                trade_date,
            )
            for trade_date in trade_dates
        )
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
    }
    row_counts = _parquet_row_counts(
        paths_by_freq=paths_by_freq,
        duckdb_resource=duckdb_resource or DuckDBResource(),
    )
    input_files: list[MinuteTechnicalInputFile] = []
    for trade_date in trade_dates:
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
            path = gold_major_index_mins_path(
                source_lake_root,
                freq,
                trade_date,
            )
            input_files.append(
                MinuteTechnicalInputFile(
                    trade_date=trade_date,
                    freq=freq,
                    path=str(path),
                    row_count=row_counts[path],
                    size_bytes=path.stat().st_size,
                    sha256=_file_sha256(path),
                )
            )
    source_manifest_hash = _hash_payload([value.to_dict() for value in input_files])
    object_pool_hash = _hash_payload(
        {
            trade_date: expected_major_index_mins_technical_codes(trade_date)
            for trade_date in trade_dates
        }
    )
    schema_contract_hash = _hash_payload(
        {
            "freqs": MAJOR_INDEX_MINS_TECHNICAL_FREQS,
            "params_key": PARAMS_KEY,
            "indicator_version": INDICATOR_VERSION,
            "technical_types": GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMN_TYPES,
            "state_types": GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMN_TYPES,
        }
    )
    estimated_output = int(
        sum(value.size_bytes for value in input_files)
        * _ESTIMATED_OUTPUT_BYTES_PER_INPUT_BYTE
    )
    free_bytes = (
        int(disk_free_bytes)
        if disk_free_bytes is not None
        else int(shutil.disk_usage(staging_root).free)
    )
    draft = MinuteTechnicalBootstrapPlan(
        generated_at=datetime.now(timezone.utc).isoformat(),
        end_date=trade_dates[-1],
        source_lake_root=Path(source_lake_root),
        staging_root=Path(staging_root),
        report_root=Path(report_root),
        trade_dates=trade_dates,
        ignored_incomplete_tail_dates=ignored_tail,
        input_files=tuple(input_files),
        source_manifest_hash=source_manifest_hash,
        object_pool_hash=object_pool_hash,
        schema_contract_hash=schema_contract_hash,
        estimated_output_bytes=estimated_output,
        disk_free_bytes=free_bytes,
        plan_hash="",
    )
    plan_hash = _hash_payload(draft.hash_payload())
    report_path = Path(report_root) / (
        f"major_index_mins_technical_bootstrap_plan_{plan_hash}.json"
    )
    plan = MinuteTechnicalBootstrapPlan(
        **{
            **asdict(draft),
            "source_lake_root": Path(source_lake_root),
            "staging_root": Path(staging_root),
            "report_root": Path(report_root),
            "input_files": tuple(input_files),
            "plan_hash": plan_hash,
            "report_path": report_path,
        }
    )
    if write_report:
        if report_path.exists():
            return load_major_index_mins_technical_bootstrap_plan(
                report_path, expected_plan_hash=plan_hash
            )
        _atomic_write_json(report_path, plan.to_dict())
    return plan


def load_major_index_mins_technical_bootstrap_plan(
    report_path: Path, *, expected_plan_hash: str
) -> MinuteTechnicalBootstrapPlan:
    payload = _load_json(report_path, label="minute technical plan")
    if payload.get("plan_hash") != expected_plan_hash:
        raise MajorIndexMinsTechnicalBootstrapError("expected plan hash mismatch")
    if payload.get("schema_version") != 2:
        raise MajorIndexMinsTechnicalBootstrapError(
            "minute technical plan must be regenerated with schema_version=2"
        )
    inputs = payload.get("input_files")
    trade_dates = payload.get("trade_dates")
    if not isinstance(inputs, list) or not isinstance(trade_dates, list):
        raise MajorIndexMinsTechnicalBootstrapError(
            "minute technical plan is incomplete"
        )
    plan = MinuteTechnicalBootstrapPlan(
        generated_at=str(payload["generated_at"]),
        end_date=str(payload["end_date"]),
        source_lake_root=Path(str(payload["source_lake_root"])),
        staging_root=Path(str(payload["staging_root"])),
        report_root=report_path.parent,
        trade_dates=tuple(str(value) for value in trade_dates),
        ignored_incomplete_tail_dates=tuple(
            str(value) for value in payload.get("ignored_incomplete_tail_dates", ())
        ),
        input_files=tuple(
            MinuteTechnicalInputFile(**dict(value))
            for value in inputs
            if isinstance(value, Mapping)
        ),
        source_manifest_hash=str(payload["source_manifest_hash"]),
        object_pool_hash=str(payload["object_pool_hash"]),
        schema_contract_hash=str(payload["schema_contract_hash"]),
        estimated_output_bytes=int(payload["estimated_output_bytes"]),
        disk_free_bytes=int(payload["disk_free_bytes"]),
        plan_hash=str(payload["plan_hash"]),
        report_path=Path(report_path),
    )
    if _hash_payload(plan.hash_payload()) != expected_plan_hash:
        raise MajorIndexMinsTechnicalBootstrapError("frozen plan payload has drifted")
    for value in plan.input_files:
        path = Path(value.path)
        if not path.is_file() or path.stat().st_size != value.size_bytes:
            raise MajorIndexMinsTechnicalBootstrapError(
                f"frozen Gold business-bar input is missing or changed size: {path}"
            )
        if _file_sha256(path) != value.sha256:
            raise MajorIndexMinsTechnicalBootstrapError(
                f"frozen Gold business-bar input hash changed: {path}"
            )
    return plan


def _candidate_manifest_entry(
    *, layer: str, freq: int, trade_date: str, path: Path, row_count: int
) -> dict[str, object]:
    return {
        "layer": layer,
        "freq": freq,
        "trade_date": trade_date,
        "path": str(path),
        "row_count": row_count,
        "size_bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _peak_rss_bytes() -> int:
    value = int(process_resource.getrusage(process_resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _validate_write_result(
    *,
    frozen_row_counts: Mapping[tuple[str, int], int],
    trade_date: str,
    freq: int,
    input_row_count: int,
    technical_row_count: int,
    state_row_count: int,
) -> None:
    frozen_row_count = frozen_row_counts.get((trade_date, freq))
    if frozen_row_count is None:
        raise MajorIndexMinsTechnicalBootstrapError(
            f"frozen Gold business-bar input is missing: date={trade_date}, freq={freq}"
        )
    if input_row_count != frozen_row_count:
        raise MajorIndexMinsTechnicalBootstrapError(
            "writer input row count differs from the frozen manifest: "
            f"date={trade_date}, freq={freq}, frozen={frozen_row_count}, "
            f"observed={input_row_count}"
        )
    if technical_row_count != input_row_count:
        raise MajorIndexMinsTechnicalBootstrapError(
            "technical output row count differs from Gold business-bar input: "
            f"date={trade_date}, freq={freq}, input={input_row_count}, "
            f"technical={technical_row_count}"
        )
    expected_state_rows = len(expected_major_index_mins_technical_codes(trade_date))
    if state_row_count != expected_state_rows:
        raise MajorIndexMinsTechnicalBootstrapError(
            "state row count differs from the effective index pool: "
            f"date={trade_date}, freq={freq}, expected={expected_state_rows}, "
            f"observed={state_row_count}"
        )


def _load_candidate_checkpoint(
    *,
    plan: MinuteTechnicalBootstrapPlan,
    checkpoint_path: Path,
) -> tuple[tuple[str, ...], list[dict[str, object]]]:
    if not checkpoint_path.exists():
        return (), []
    payload = _load_json(checkpoint_path, label="minute technical checkpoint")
    if payload.get("plan_hash") != plan.plan_hash:
        raise MajorIndexMinsTechnicalBootstrapError(
            "candidate checkpoint belongs to another frozen plan"
        )
    completed_value = payload.get("completed_dates")
    files_value = payload.get("files")
    if not isinstance(completed_value, list) or not isinstance(files_value, list):
        raise MajorIndexMinsTechnicalBootstrapError(
            "candidate checkpoint is missing completed dates or file manifest"
        )
    completed = tuple(str(value) for value in completed_value)
    if completed != plan.trade_dates[: len(completed)]:
        raise MajorIndexMinsTechnicalBootstrapError(
            "candidate checkpoint dates are not a contiguous frozen-plan prefix"
        )
    files = [dict(value) for value in files_value if isinstance(value, Mapping)]
    if len(files) != len(completed) * len(MAJOR_INDEX_MINS_TECHNICAL_FREQS) * 2:
        raise MajorIndexMinsTechnicalBootstrapError(
            "candidate checkpoint file count does not match completed dates"
        )
    for entry in files:
        path = Path(str(entry.get("path")))
        if not path.is_file() or _file_sha256(path) != str(entry.get("sha256")):
            raise MajorIndexMinsTechnicalBootstrapError(
                f"checkpoint candidate is missing or changed: {path}"
            )
    return completed, files


def _write_candidate_checkpoint(
    *,
    checkpoint_path: Path,
    plan_hash: str,
    completed_dates: Sequence[str],
    files: Sequence[Mapping[str, object]],
    complete: bool = False,
) -> None:
    _atomic_write_json(
        checkpoint_path,
        {
            "plan_hash": plan_hash,
            "completed_dates": list(completed_dates),
            "completed_file_count": len(files),
            "files": [dict(value) for value in files],
            "complete": complete,
        },
    )


def _load_sample_checkpoint(
    *,
    plan: MinuteTechnicalBootstrapPlan,
    checkpoint_path: Path,
    sample_lake: Path,
) -> tuple[
    tuple[str, ...],
    list[dict[str, object]],
    list[dict[str, object]],
    int,
]:
    if not checkpoint_path.exists():
        return (), [], [], 0
    payload = _load_json(checkpoint_path, label="minute technical sample checkpoint")
    if payload.get("report_type") != "performance_sample":
        raise MajorIndexMinsTechnicalBootstrapError(
            "sample checkpoint has an unsupported report type"
        )
    if payload.get("plan_hash") != plan.plan_hash:
        raise MajorIndexMinsTechnicalBootstrapError(
            "sample checkpoint belongs to another frozen plan"
        )
    completed_value = payload.get("completed_dates")
    files_value = payload.get("files")
    measurements_value = payload.get("measurements")
    if not all(
        isinstance(value, list)
        for value in (completed_value, files_value, measurements_value)
    ):
        raise MajorIndexMinsTechnicalBootstrapError(
            "sample checkpoint is missing dates, files, or measurements"
        )
    completed = tuple(str(value) for value in completed_value)
    if completed != plan.trade_dates[: len(completed)]:
        raise MajorIndexMinsTechnicalBootstrapError(
            "sample checkpoint dates are not a contiguous frozen-plan prefix"
        )
    files = [dict(value) for value in files_value if isinstance(value, Mapping)]
    measurements = [
        dict(value) for value in measurements_value if isinstance(value, Mapping)
    ]
    expected_files = len(completed) * len(MAJOR_INDEX_MINS_TECHNICAL_FREQS) * 2
    expected_measurements = len(completed) * len(MAJOR_INDEX_MINS_TECHNICAL_FREQS)
    if len(files) != expected_files or len(measurements) != expected_measurements:
        raise MajorIndexMinsTechnicalBootstrapError(
            "sample checkpoint counts do not match completed dates"
        )
    resolved_sample_lake = sample_lake.resolve()
    for entry in files:
        path = Path(str(entry.get("path")))
        if not path.resolve().is_relative_to(resolved_sample_lake):
            raise MajorIndexMinsTechnicalBootstrapError(
                f"sample checkpoint references a path outside sample staging: {path}"
            )
        if not path.is_file() or _file_sha256(path) != str(entry.get("sha256")):
            raise MajorIndexMinsTechnicalBootstrapError(
                f"checkpoint sample file is missing or changed: {path}"
            )
    return (
        completed,
        files,
        measurements,
        int(payload.get("peak_rss_bytes", 0)),
    )


def _write_sample_checkpoint(
    *,
    checkpoint_path: Path,
    plan_hash: str,
    completed_dates: Sequence[str],
    files: Sequence[Mapping[str, object]],
    measurements: Sequence[Mapping[str, object]],
    peak_rss_bytes: int,
) -> None:
    _atomic_write_json(
        checkpoint_path,
        {
            "schema_version": 1,
            "report_type": "performance_sample",
            "plan_hash": plan_hash,
            "completed_dates": list(completed_dates),
            "completed_file_count": len(files),
            "files": [dict(value) for value in files],
            "measurements": [dict(value) for value in measurements],
            "peak_rss_bytes": peak_rss_bytes,
        },
    )


def build_major_index_mins_technical_performance_sample(
    *,
    plan_report_path: Path,
    expected_plan_hash: str,
    sample_date_count: int,
    duckdb_resource: DuckDBResource | None = None,
    apply: bool = False,
) -> Path:
    """Build an isolated 20/60-day performance sample, never a promotable candidate."""

    if sample_date_count not in BOOTSTRAP_SAMPLE_DATE_COUNTS:
        raise MajorIndexMinsTechnicalBootstrapError(
            "sample date count must be exactly 20 or 60"
        )
    if not apply:
        raise MajorIndexMinsTechnicalBootstrapError(
            "performance sample requires apply=True"
        )
    plan = load_major_index_mins_technical_bootstrap_plan(
        plan_report_path, expected_plan_hash=expected_plan_hash
    )
    if not plan.disk_budget_passed:
        raise MajorIndexMinsTechnicalBootstrapError("frozen disk budget did not pass")
    if len(plan.trade_dates) < sample_date_count:
        raise MajorIndexMinsTechnicalBootstrapError(
            f"frozen plan has fewer than {sample_date_count} dates"
        )

    sample_root = plan.performance_sample_root
    sample_lake = sample_root / "sample_lake"
    run_staging = sample_root / "sample_run_staging"
    checkpoint_path = sample_root / "performance-sample-checkpoint.json"
    selected_dates = plan.trade_dates[:sample_date_count]
    frozen_row_counts = {
        (value.trade_date, value.freq): value.row_count for value in plan.input_files
    }
    resource = duckdb_resource or DuckDBResource()
    completed_prefix, manifest, measurements, checkpoint_peak_rss = (
        _load_sample_checkpoint(
            plan=plan,
            checkpoint_path=checkpoint_path,
            sample_lake=sample_lake,
        )
    )
    if len(completed_prefix) > sample_date_count:
        raise MajorIndexMinsTechnicalBootstrapError(
            "sample checkpoint is already beyond the requested date count"
        )

    completed_dates = list(completed_prefix)
    invocation_started_at = perf_counter()
    invocation_output_bytes = 0
    peak_rss_bytes = max(checkpoint_peak_rss, _peak_rss_bytes())
    for trade_date in selected_dates:
        if trade_date in completed_prefix:
            continue
        day_entries: list[dict[str, object]] = []
        day_measurements: list[dict[str, object]] = []
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
            technical = gold_major_index_mins_technical_path(
                sample_lake, freq, trade_date
            )
            state = gold_major_index_mins_technical_state_path(
                sample_lake, freq, trade_date
            )
            if technical.exists() != state.exists():
                raise MajorIndexMinsTechnicalBootstrapError(
                    "partial performance-sample pair requires an explicit repair plan: "
                    f"freq={freq}, trade_date={trade_date}"
                )
            if technical.exists():
                raise MajorIndexMinsTechnicalBootstrapError(
                    "sample files exist outside the verified checkpoint: "
                    f"freq={freq}, trade_date={trade_date}"
                )
            try:
                result = write_major_index_mins_technical_partition(
                    source_lake_root_path=plan.source_lake_root,
                    target_lake_root_path=sample_lake,
                    staging_root_path=run_staging,
                    duckdb_resource=resource,
                    freq=freq,
                    partition_key=trade_date,
                    run_id=(
                        f"bootstrap-sample-{plan.plan_hash[:12]}-{trade_date}-{freq}"
                    ),
                    expected_trade_dates=plan.trade_dates,
                )
            except MajorIndexMinsTechnicalValidationError as error:
                raise MajorIndexMinsTechnicalBootstrapError(
                    "performance sample writer failed: "
                    f"date={trade_date}, freq={freq}: {error}"
                ) from error
            _validate_write_result(
                frozen_row_counts=frozen_row_counts,
                trade_date=trade_date,
                freq=freq,
                input_row_count=result.input_row_count,
                technical_row_count=result.technical_row_count,
                state_row_count=result.state_row_count,
            )
            technical_entry = _candidate_manifest_entry(
                layer="technical",
                freq=freq,
                trade_date=trade_date,
                path=result.technical_path,
                row_count=result.technical_row_count,
            )
            state_entry = _candidate_manifest_entry(
                layer="state",
                freq=freq,
                trade_date=trade_date,
                path=result.state_path,
                row_count=result.state_row_count,
            )
            day_entries.extend((technical_entry, state_entry))
            output_bytes = int(technical_entry["size_bytes"]) + int(
                state_entry["size_bytes"]
            )
            invocation_output_bytes += output_bytes
            day_measurements.append(
                {
                    "trade_date": trade_date,
                    "freq": freq,
                    "input_row_count": result.input_row_count,
                    "technical_row_count": result.technical_row_count,
                    "state_row_count": result.state_row_count,
                    "technical_size_bytes": technical_entry["size_bytes"],
                    "state_size_bytes": state_entry["size_bytes"],
                    "output_bytes": output_bytes,
                    "elapsed_ms": result.elapsed_ms,
                }
            )
            peak_rss_bytes = max(peak_rss_bytes, _peak_rss_bytes())
        if len(day_entries) != len(MAJOR_INDEX_MINS_TECHNICAL_FREQS) * 2 or len(
            day_measurements
        ) != len(MAJOR_INDEX_MINS_TECHNICAL_FREQS):
            raise MajorIndexMinsTechnicalBootstrapError(
                f"sample date checkpoint is incomplete: {trade_date}"
            )
        manifest.extend(day_entries)
        measurements.extend(day_measurements)
        completed_dates.append(trade_date)
        _write_sample_checkpoint(
            checkpoint_path=checkpoint_path,
            plan_hash=plan.plan_hash,
            completed_dates=completed_dates,
            files=manifest,
            measurements=measurements,
            peak_rss_bytes=peak_rss_bytes,
        )

    total_elapsed_ms = sum(float(value["elapsed_ms"]) for value in measurements)
    total_input_rows = sum(int(value["input_row_count"]) for value in measurements)
    total_technical_rows = sum(
        int(value["technical_row_count"]) for value in measurements
    )
    total_state_rows = sum(int(value["state_row_count"]) for value in measurements)
    total_output_bytes = sum(int(value["output_bytes"]) for value in measurements)
    report_path = plan.report_root / (
        "major_index_mins_technical_performance_sample_"
        f"{sample_date_count}d_{plan.plan_hash}.json"
    )
    _atomic_write_json(
        report_path,
        {
            "schema_version": 1,
            "report_type": "performance_sample",
            "promotion_eligible": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "plan_hash": plan.plan_hash,
            "sample_date_count": sample_date_count,
            "selected_dates": list(selected_dates),
            "completed_dates": completed_dates,
            "sample_root": str(sample_root),
            "sample_lake_root": str(sample_lake),
            "checkpoint_path": str(checkpoint_path),
            "files": manifest,
            "measurements": measurements,
            "summary": {
                "measurement_count": len(measurements),
                "total_input_rows": total_input_rows,
                "total_technical_rows": total_technical_rows,
                "total_state_rows": total_state_rows,
                "total_output_bytes": total_output_bytes,
                "calculation_elapsed_ms": total_elapsed_ms,
                "average_elapsed_ms_per_date": (
                    total_elapsed_ms / len(completed_dates)
                ),
                "input_rows_per_second": (
                    total_input_rows / (total_elapsed_ms / 1000)
                    if total_elapsed_ms > 0
                    else None
                ),
                "peak_rss_bytes": peak_rss_bytes,
                "invocation_elapsed_ms": (perf_counter() - invocation_started_at)
                * 1000,
                "invocation_output_bytes": invocation_output_bytes,
            },
            "should_stop": False,
            "writes": {
                "sample_files": len(manifest),
                "candidate_files": 0,
                "formal_lake": 0,
                "dagster_events": 0,
            },
        },
    )
    return report_path


def build_major_index_mins_technical_candidates(
    *,
    plan_report_path: Path,
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource | None = None,
    apply: bool = False,
) -> Path:
    if not apply:
        raise MajorIndexMinsTechnicalBootstrapError(
            "candidate build requires apply=True"
        )
    plan = load_major_index_mins_technical_bootstrap_plan(
        plan_report_path, expected_plan_hash=expected_plan_hash
    )
    if not plan.disk_budget_passed:
        raise MajorIndexMinsTechnicalBootstrapError("frozen disk budget did not pass")
    candidate_lake = plan.candidate_root / "candidate_lake"
    run_staging = plan.candidate_root / "candidate_run_staging"
    checkpoint_path = plan.candidate_root / "candidate-checkpoint.json"
    resource = duckdb_resource or DuckDBResource()
    frozen_row_counts = {
        (value.trade_date, value.freq): value.row_count for value in plan.input_files
    }
    completed_prefix, manifest = _load_candidate_checkpoint(
        plan=plan,
        checkpoint_path=checkpoint_path,
    )
    completed_dates = list(completed_prefix)
    for date_index, trade_date in enumerate(plan.trade_dates, start=1):
        if trade_date in completed_prefix:
            continue
        day_entries: list[dict[str, object]] = []
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
            technical = gold_major_index_mins_technical_path(
                candidate_lake, freq, trade_date
            )
            state = gold_major_index_mins_technical_state_path(
                candidate_lake, freq, trade_date
            )
            if technical.exists() != state.exists():
                raise MajorIndexMinsTechnicalBootstrapError(
                    "partial candidate pair requires an explicit repair plan: "
                    f"freq={freq}, trade_date={trade_date}"
                )
            if technical.exists():
                raise MajorIndexMinsTechnicalBootstrapError(
                    "candidate files exist outside the verified checkpoint: "
                    f"freq={freq}, trade_date={trade_date}"
                )
            try:
                result = write_major_index_mins_technical_partition(
                    source_lake_root_path=plan.source_lake_root,
                    target_lake_root_path=candidate_lake,
                    staging_root_path=run_staging,
                    duckdb_resource=resource,
                    freq=freq,
                    partition_key=trade_date,
                    run_id=f"bootstrap-{plan.plan_hash[:12]}-{trade_date}-{freq}",
                    expected_trade_dates=plan.trade_dates,
                )
            except MajorIndexMinsTechnicalValidationError as error:
                raise MajorIndexMinsTechnicalBootstrapError(
                    f"candidate writer failed: date={trade_date}, freq={freq}: {error}"
                ) from error
            _validate_write_result(
                frozen_row_counts=frozen_row_counts,
                trade_date=trade_date,
                freq=freq,
                input_row_count=result.input_row_count,
                technical_row_count=result.technical_row_count,
                state_row_count=result.state_row_count,
            )
            day_entries.extend(
                (
                    _candidate_manifest_entry(
                        layer="technical",
                        freq=freq,
                        trade_date=trade_date,
                        path=result.technical_path,
                        row_count=result.technical_row_count,
                    ),
                    _candidate_manifest_entry(
                        layer="state",
                        freq=freq,
                        trade_date=trade_date,
                        path=result.state_path,
                        row_count=result.state_row_count,
                    ),
                )
            )
        if len(day_entries) != len(MAJOR_INDEX_MINS_TECHNICAL_FREQS) * 2:
            raise MajorIndexMinsTechnicalBootstrapError(
                f"date checkpoint has fewer than 14 files: {trade_date}"
            )
        manifest.extend(day_entries)
        completed_dates.append(trade_date)
        if date_index % BOOTSTRAP_BATCH_DATE_COUNT == 0:
            _write_candidate_checkpoint(
                checkpoint_path=checkpoint_path,
                plan_hash=plan.plan_hash,
                completed_dates=completed_dates,
                files=manifest,
            )
    report_path = plan.report_root / (
        f"major_index_mins_technical_candidate_{plan.plan_hash}.json"
    )
    _atomic_write_json(
        report_path,
        {
            "schema_version": 1,
            "report_type": "full_candidate",
            "promotion_eligible": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "plan_hash": plan.plan_hash,
            "candidate_lake_root": str(candidate_lake),
            "date_count": len(completed_dates),
            "files": manifest,
            "should_stop": False,
            "writes": {
                "candidate_files": len(manifest),
                "formal_lake": 0,
                "dagster_events": 0,
            },
        },
    )
    _write_candidate_checkpoint(
        checkpoint_path=checkpoint_path,
        plan_hash=plan.plan_hash,
        completed_dates=completed_dates,
        files=manifest,
        complete=True,
    )
    return report_path


def _audit_formal_pair(
    *,
    connection,
    plan: MinuteTechnicalBootstrapPlan,
    freq: int,
    trade_date: str,
) -> None:
    expected_codes = expected_major_index_mins_technical_codes(trade_date)
    technical_path = gold_major_index_mins_technical_path(
        plan.source_lake_root, freq, trade_date
    )
    state_path = gold_major_index_mins_technical_state_path(
        plan.source_lake_root, freq, trade_date
    )
    technical_relation_sql = read_parquet(
        technical_path,
        hive_partitioning=False,
    )
    state_relation_sql = read_parquet(
        state_path,
        hive_partitioning=False,
    )
    technical = audit_major_index_mins_technical_relation(
        connection,
        relation_sql=technical_relation_sql,
        expected_codes=expected_codes,
        trade_date=trade_date,
        freq=freq,
    )
    state = audit_major_index_mins_technical_state_relation(
        connection,
        relation_sql=state_relation_sql,
        expected_codes=expected_codes,
        trade_date=trade_date,
        freq=freq,
        technical_relation_sql=technical_relation_sql,
    )
    if technical.errors or state.errors:
        raise MajorIndexMinsTechnicalBootstrapError(
            "formal technical/state physical audit failed: "
            f"date={trade_date}, freq={freq}, technical={technical.errors!r}, "
            f"state={state.errors!r}"
        )


def promote_major_index_mins_technical_candidates(
    *,
    plan_report_path: Path,
    candidate_report_path: Path,
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource | None = None,
    apply: bool = False,
) -> Path:
    if not apply:
        raise MajorIndexMinsTechnicalBootstrapError(
            "formal promotion requires apply=True"
        )
    plan = load_major_index_mins_technical_bootstrap_plan(
        plan_report_path, expected_plan_hash=expected_plan_hash
    )
    candidate_report = _load_json(candidate_report_path, label="candidate report")
    if (
        candidate_report.get("report_type") != "full_candidate"
        or candidate_report.get("promotion_eligible") is not True
    ):
        raise MajorIndexMinsTechnicalBootstrapError(
            "formal promotion only accepts a full candidate report"
        )
    if (
        candidate_report.get("plan_hash") != plan.plan_hash
        or candidate_report.get("should_stop") is not False
    ):
        raise MajorIndexMinsTechnicalBootstrapError(
            "candidate report is not green for the frozen plan"
        )
    files = candidate_report.get("files")
    if not isinstance(files, list):
        raise MajorIndexMinsTechnicalBootstrapError("candidate report has no manifest")
    expected_count = len(plan.trade_dates) * len(MAJOR_INDEX_MINS_TECHNICAL_FREQS) * 2
    if len(files) != expected_count:
        raise MajorIndexMinsTechnicalBootstrapError("candidate manifest count mismatch")
    by_key = {
        (str(value["layer"]), int(value["freq"]), str(value["trade_date"])): value
        for value in files
        if isinstance(value, Mapping)
    }
    actions: list[dict[str, object]] = []
    for trade_date in plan.trade_dates:
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
            pair_entries = tuple(
                by_key[(layer, freq, trade_date)] for layer in ("technical", "state")
            )
            formal_paths = (
                gold_major_index_mins_technical_path(
                    plan.source_lake_root, freq, trade_date
                ),
                gold_major_index_mins_technical_state_path(
                    plan.source_lake_root, freq, trade_date
                ),
            )
            if formal_paths[0].exists() != formal_paths[1].exists():
                raise MajorIndexMinsTechnicalBootstrapError(
                    f"formal target has a partial pair: date={trade_date}, freq={freq}"
                )
            for entry, formal in zip(pair_entries, formal_paths, strict=True):
                candidate = Path(str(entry["path"]))
                expected_hash = str(entry["sha256"])
                if formal.exists():
                    if _file_sha256(formal) != expected_hash:
                        raise MajorIndexMinsTechnicalBootstrapError(
                            f"formal target conflicts with manifest: {formal}"
                        )
                    action = "reused_identical_formal"
                else:
                    if (
                        not candidate.is_file()
                        or _file_sha256(candidate) != expected_hash
                    ):
                        raise MajorIndexMinsTechnicalBootstrapError(
                            f"candidate is missing or changed: {candidate}"
                        )
                    formal.parent.mkdir(parents=True, exist_ok=True)
                    if candidate.parent.stat().st_dev != formal.parent.stat().st_dev:
                        raise MajorIndexMinsTechnicalBootstrapError(
                            "candidate and formal target must share one filesystem"
                        )
                    os.replace(candidate, formal)
                    action = "promoted"
                actions.append(
                    {
                        "layer": entry["layer"],
                        "freq": freq,
                        "trade_date": trade_date,
                        "formal_path": str(formal),
                        "sha256": expected_hash,
                        "row_count": int(entry["row_count"]),
                        "action": action,
                    }
                )
    resource = duckdb_resource or DuckDBResource()
    with resource.connect() as connection:
        for trade_date in plan.trade_dates:
            for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
                _audit_formal_pair(
                    connection=connection, plan=plan, freq=freq, trade_date=trade_date
                )
    report_path = plan.report_root / (
        f"major_index_mins_technical_promote_{plan.plan_hash}.json"
    )
    _atomic_write_json(
        report_path,
        {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "plan_hash": plan.plan_hash,
            "candidate_report_path": str(candidate_report_path),
            "formal_lake_root": str(plan.source_lake_root),
            "results": actions,
            "promoted_count": sum(value["action"] == "promoted" for value in actions),
            "reused_count": sum(
                value["action"] == "reused_identical_formal" for value in actions
            ),
            "should_stop": False,
            "writes": {
                "formal_lake": sum(value["action"] == "promoted" for value in actions),
                "dagster_events": 0,
            },
        },
    )
    return report_path


__all__ = [
    "MajorIndexMinsTechnicalBootstrapError",
    "MinuteTechnicalBootstrapPlan",
    "build_major_index_mins_technical_bootstrap_plan",
    "build_major_index_mins_technical_candidates",
    "build_major_index_mins_technical_performance_sample",
    "load_major_index_mins_technical_bootstrap_plan",
    "promote_major_index_mins_technical_candidates",
]
