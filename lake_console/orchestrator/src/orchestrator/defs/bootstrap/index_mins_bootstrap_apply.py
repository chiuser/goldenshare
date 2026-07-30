"""Bounded, resumable Raw/Silver Bootstrap writer for ``index_mins``.

The read-only P6 source probe remains in ``index_mins_bootstrap_plan``.  This
module is a separate write entry point: it consumes the frozen P6 report and
the approved source-empty fallback report, derives historical code scopes from
the lake's ``silver_index_basic`` snapshot, and then invokes the existing
atomic partition writers.  It never talks to Dagster or writes Dagster events.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from time import perf_counter
from typing import Any

from orchestrator.defs.assets.index_mins import (
    write_raw_index_mins_partition_from_prod_db,
)
from orchestrator.defs.assets.index_mins_silver import (
    write_silver_index_mins_partition,
)
from orchestrator.defs.bootstrap.index_mins_bootstrap_plan import (
    IndexMinsDatePlan,
    IndexMinsTargetAudit,
    audit_index_mins_targets,
    build_date_plan,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import (
    raw_index_mins_path,
    silver_index_basic_path,
    silver_index_mins_path,
)
from orchestrator.defs.prod_db.index_mins import IndexMinsActivePool
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
    INDEX_MINS_SOURCE_FREQS,
    INDEX_MINS_SILVER_FREQS,
    index_mins_code_set_hash,
    normalize_index_mins_codes,
)


class IndexMinsBootstrapApplyError(RuntimeError):
    """Raised when the approved index_mins Bootstrap cannot continue safely."""


# This is the only source-empty exception that the full Bootstrap may consume.
# Keeping it explicit prevents a stale or incomplete probe report from silently
# widening the fallback scope.
INDEX_MINS_APPROVED_SOURCE_EMPTY_FALLBACK_SCOPE: dict[str, tuple[int, ...]] = {
    "2025-07-04": (30, 60),
    "2025-07-11": (15, 30, 60),
    "2025-07-18": (30, 60),
    "2025-07-25": (60,),
    "2025-08-01": (30, 60),
}

_REPORT_SCHEMA_VERSION = 1
_MAX_BATCH_SIZE = 20


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _report_paths(output_dir: Path, apply_id: str) -> dict[str, Path]:
    return {
        "raw_batch": output_dir / f"index_mins_bootstrap_raw_batch_{apply_id}.json",
        "raw_audit": output_dir / f"index_mins_bootstrap_raw_audit_{apply_id}.json",
        "silver_batch": output_dir / f"index_mins_bootstrap_silver_batch_{apply_id}.json",
        "silver_audit": output_dir / f"index_mins_bootstrap_silver_audit_{apply_id}.json",
        "final": output_dir / f"index_mins_bootstrap_final_{apply_id}.json",
        "failure": output_dir / f"index_mins_bootstrap_failure_{apply_id}.json",
    }


def _audit_by_layer(
    audits: Sequence[IndexMinsTargetAudit],
    layer: str,
) -> IndexMinsTargetAudit:
    for audit in audits:
        if audit.layer == layer:
            return audit
    raise IndexMinsBootstrapApplyError(f"missing {layer} target audit")


def _audit_summary(audit: IndexMinsTargetAudit) -> dict[str, object]:
    return audit.to_dict()


def _target_audits_pass(audits: Sequence[IndexMinsTargetAudit], layer: str) -> bool:
    audit = _audit_by_layer(audits, layer)
    return audit.missing_count == 0 and audit.invalid_existing_count == 0


def load_historical_index_mins_code_scopes(
    *,
    connection: Any,
    lake_root: Path,
    trade_dates: Sequence[str],
) -> dict[str, IndexMinsActivePool]:
    """Derive one valid index code set per date from ``silver_index_basic``.

    The snapshot is small (the current index universe, not minute history), so
    returning the grouped code sets is bounded.  The minute rows themselves
    remain in Prod and are streamed by each existing Raw writer.
    """

    source_path = silver_index_basic_path(lake_root)
    if not source_path.is_file():
        raise IndexMinsBootstrapApplyError(
            f"missing historical index scope source: {source_path}"
        )
    try:
        normalized_dates = tuple(
            datetime.fromisoformat(str(value)).date().isoformat()
            for value in trade_dates
        )
    except ValueError as error:
        raise IndexMinsBootstrapApplyError(
            "historical index scope dates must be ISO dates"
        ) from error
    if not normalized_dates:
        raise IndexMinsBootstrapApplyError("historical index scope date set is empty")
    if len(set(normalized_dates)) != len(normalized_dates):
        raise IndexMinsBootstrapApplyError("historical index scope dates are duplicated")
    values_sql = ", ".join(
        f"(DATE '{value}')" for value in normalized_dates
    )
    rows = connection.execute(
        f"""
        WITH expected(trade_date) AS (
          VALUES {values_sql}
        )
        SELECT
          CAST(expected.trade_date AS VARCHAR) AS trade_date,
          CAST(index_basic.ts_code AS VARCHAR) AS ts_code
        FROM expected
        CROSS JOIN {read_parquet(source_path, hive_partitioning=False)} AS index_basic
        WHERE try_cast(index_basic.ts_code AS VARCHAR) IS NOT NULL
          AND trim(CAST(index_basic.ts_code AS VARCHAR)) != ''
          AND try_cast(index_basic.list_date AS DATE) IS NOT NULL
          AND try_cast(index_basic.list_date AS DATE) <= expected.trade_date
          AND (
            index_basic.exp_date IS NULL
            OR try_cast(index_basic.exp_date AS DATE) > expected.trade_date
          )
        GROUP BY expected.trade_date, index_basic.ts_code
        ORDER BY expected.trade_date, index_basic.ts_code
        """
    ).fetchall()
    codes_by_date: dict[str, list[str]] = {trade_date: [] for trade_date in normalized_dates}
    for trade_date, code in rows:
        codes_by_date[str(trade_date)].append(str(code))
    scopes: dict[str, IndexMinsActivePool] = {}
    for trade_date in normalized_dates:
        try:
            codes = normalize_index_mins_codes(
                codes_by_date[trade_date],
                reject_duplicates=True,
            )
        except ValueError as error:
            raise IndexMinsBootstrapApplyError(
                f"historical index scope is empty or invalid: {trade_date}"
            ) from error
        scopes[trade_date] = IndexMinsActivePool(
            codes=codes,
            code_set_hash=index_mins_code_set_hash(codes),
        )
    return scopes


def _source_empty_scope_from_report(
    source_report: Mapping[str, Any],
    date_plan: IndexMinsDatePlan,
) -> dict[str, tuple[int, ...]]:
    readiness_rows = source_report.get("source_readiness")
    if not isinstance(readiness_rows, Sequence) or isinstance(readiness_rows, (str, bytes)):
        raise IndexMinsBootstrapApplyError("P6 source report has no source_readiness rows")
    seen_dates: set[str] = set()
    observed: dict[str, tuple[int, ...]] = {}
    for readiness in readiness_rows:
        if not isinstance(readiness, Mapping):
            raise IndexMinsBootstrapApplyError("P6 source readiness row is invalid")
        trade_date = str(readiness.get("trade_date", ""))
        if trade_date in seen_dates:
            raise IndexMinsBootstrapApplyError(
                f"P6 source report has duplicate readiness date: {trade_date}"
            )
        seen_dates.add(trade_date)
        coverages = readiness.get("frequency_coverages")
        if not isinstance(coverages, Sequence) or isinstance(coverages, (str, bytes)):
            raise IndexMinsBootstrapApplyError(
                f"P6 source readiness has no frequency coverages: {trade_date}"
            )
        empty: list[int] = []
        seen_frequencies: set[str] = set()
        for coverage in coverages:
            if not isinstance(coverage, Mapping):
                raise IndexMinsBootstrapApplyError("P6 frequency coverage row is invalid")
            source_freq = str(coverage.get("source_freq", ""))
            if source_freq in seen_frequencies:
                raise IndexMinsBootstrapApplyError(
                    f"duplicate source frequency in P6 report: {trade_date}/{source_freq}"
                )
            seen_frequencies.add(source_freq)
            if not source_freq.endswith("min"):
                raise IndexMinsBootstrapApplyError(
                    f"invalid source frequency in P6 report: {source_freq}"
                )
            try:
                frequency = int(source_freq[:-3])
            except ValueError as error:
                raise IndexMinsBootstrapApplyError(
                    f"invalid source frequency in P6 report: {source_freq}"
                ) from error
            if int(coverage.get("source_row_count") or 0) <= 0:
                empty.append(frequency)
        if seen_frequencies != {f"{frequency}min" for frequency in (1, 5, 15, 30, 60)}:
            raise IndexMinsBootstrapApplyError(
                f"P6 source frequency coverage is incomplete: {trade_date}"
            )
        observed[trade_date] = tuple(sorted(empty))
    if tuple(sorted(seen_dates)) != tuple(sorted(date_plan.expected_trade_dates)):
        raise IndexMinsBootstrapApplyError("P6 source report date coverage is incomplete")
    return {trade_date: frequencies for trade_date, frequencies in observed.items() if frequencies}


def _validate_source_reports(
    *,
    source_report: Mapping[str, Any],
    fallback_report: Mapping[str, Any],
    date_plan: IndexMinsDatePlan,
    lake_root: Path,
) -> dict[str, tuple[int, ...]]:
    if source_report.get("schema_version") != _REPORT_SCHEMA_VERSION:
        raise IndexMinsBootstrapApplyError("P6 source report schema version is unsupported")
    if source_report.get("should_stop") is not True:
        raise IndexMinsBootstrapApplyError(
            "P6 source report does not record the expected source-coverage blocker"
        )
    if Path(str(source_report.get("lake_root", ""))).expanduser().resolve() != lake_root:
        raise IndexMinsBootstrapApplyError("P6 source report lake_root does not match apply lake")
    report_plan = source_report.get("date_plan")
    if not isinstance(report_plan, Mapping):
        raise IndexMinsBootstrapApplyError("P6 source report has no date_plan")
    if report_plan.get("fingerprint") != date_plan.fingerprint:
        raise IndexMinsBootstrapApplyError("P6 source report fingerprint does not match date plan")
    if tuple(report_plan.get("expected_trade_dates", ())) != date_plan.expected_trade_dates:
        raise IndexMinsBootstrapApplyError("P6 source report dates do not match date plan")
    stop_reasons = set(str(value) for value in source_report.get("stop_reason_codes", ()))
    if stop_reasons != {"source_coverage_not_ready"}:
        raise IndexMinsBootstrapApplyError(
            "P6 source report has blockers beyond the approved source-empty fallback"
        )
    source_probe = source_report.get("source_probe")
    if not isinstance(source_probe, Mapping) or source_probe.get("probe_mode") != "coverage_only":
        raise IndexMinsBootstrapApplyError("P6 source report is not the frozen coverage-only probe")
    if (
        not isinstance(source_report.get("disk_budget"), Mapping)
        or not source_report["disk_budget"].get("passed")
    ):
        raise IndexMinsBootstrapApplyError("P6 source report disk budget did not pass")
    for audit in source_report.get("target_audits", ()):
        if isinstance(audit, Mapping) and int(audit.get("invalid_existing_count") or 0):
            raise IndexMinsBootstrapApplyError("P6 source report contains invalid existing targets")

    observed_empty = _source_empty_scope_from_report(source_report, date_plan)
    if observed_empty != INDEX_MINS_APPROVED_SOURCE_EMPTY_FALLBACK_SCOPE:
        raise IndexMinsBootstrapApplyError(
            "P6 source-empty scope does not match the approved bounded fallback scope"
        )
    for readiness in source_report["source_readiness"]:
        trade_date = str(readiness["trade_date"])
        expected_reason = (
            "prod_index_mins_source_empty"
            if trade_date in INDEX_MINS_APPROVED_SOURCE_EMPTY_FALLBACK_SCOPE
            else "prod_index_mins_source_ready"
        )
        if readiness.get("reason_code") != expected_reason:
            raise IndexMinsBootstrapApplyError(
                f"P6 source readiness reason is inconsistent: {trade_date}"
            )

    if fallback_report.get("schema_version") != _REPORT_SCHEMA_VERSION:
        raise IndexMinsBootstrapApplyError("fallback report schema version is unsupported")
    if fallback_report.get("status") != "completed":
        raise IndexMinsBootstrapApplyError("fallback report is not completed")
    if fallback_report.get("full_dry_run_reexecuted", False) is not False:
        raise IndexMinsBootstrapApplyError("fallback report unexpectedly re-ran full dry-run")
    if fallback_report.get("full_bootstrap_started", False) is not False:
        raise IndexMinsBootstrapApplyError("fallback report unexpectedly started full Bootstrap")
    if fallback_report.get("dagster_event_write", False) is not False:
        raise IndexMinsBootstrapApplyError("fallback report contains Dagster event writes")
    fallback_dates = tuple(str(value) for value in fallback_report.get("dates", ()))
    if fallback_dates != tuple(INDEX_MINS_APPROVED_SOURCE_EMPTY_FALLBACK_SCOPE):
        raise IndexMinsBootstrapApplyError("fallback report dates do not match approved scope")
    fallback_targets = fallback_report.get("target_frequencies")
    if not isinstance(fallback_targets, Mapping):
        raise IndexMinsBootstrapApplyError("fallback report target_frequencies is invalid")
    try:
        normalized_targets = {
            str(trade_date): tuple(sorted(int(value) for value in values))
            for trade_date, values in fallback_targets.items()
        }
    except (TypeError, ValueError) as error:
        raise IndexMinsBootstrapApplyError(
            "fallback report target frequencies are invalid"
        ) from error
    if normalized_targets != INDEX_MINS_APPROVED_SOURCE_EMPTY_FALLBACK_SCOPE:
        raise IndexMinsBootstrapApplyError(
            "fallback report target frequencies do not match approved scope"
        )
    return observed_empty


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IndexMinsBootstrapApplyError(f"cannot read Bootstrap report: {path}") from error
    if not isinstance(payload, Mapping):
        raise IndexMinsBootstrapApplyError(f"Bootstrap report must be an object: {path}")
    return payload


def _result_metadata(result: Any) -> dict[str, object]:
    if hasattr(result, "to_metadata"):
        value = result.to_metadata()
        if isinstance(value, Mapping):
            return {str(key): item for key, item in value.items()}
    if isinstance(result, Mapping):
        return {str(key): item for key, item in result.items()}
    raise IndexMinsBootstrapApplyError("Bootstrap writer returned no metadata")


def _base_report(
    *,
    apply_id: str,
    lake_root: Path,
    date_plan: IndexMinsDatePlan,
    source_report_path: Path,
    fallback_report_path: Path,
    disk_free_bytes: int,
    required_free_bytes: int,
) -> dict[str, object]:
    return {
        "schema_version": _REPORT_SCHEMA_VERSION,
        "apply_id": apply_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lake_root": str(lake_root),
        "source_report_path": str(source_report_path),
        "fallback_report_path": str(fallback_report_path),
        "date_plan": date_plan.to_dict(),
        "disk_free_bytes_at_preflight": disk_free_bytes,
        "required_free_bytes": required_free_bytes,
        "disk_safety_multiplier": INDEX_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
        "source_method": "prod_db_raw_index_mins_bootstrap_apply",
        "dagster_event_write": False,
    }


def _temporary_target_files(lake_root: Path) -> tuple[str, ...]:
    paths: list[str] = []
    for base in (
        lake_root / "raw/tushare/index_mins",
        lake_root / "silver/quote/index_mins",
    ):
        if base.is_dir():
            paths.extend(str(path) for path in base.rglob("*.tmp"))
    return tuple(paths)


def _validate_preflight_targets(
    audits: Sequence[IndexMinsTargetAudit],
    temporary_files: Sequence[str],
) -> None:
    if temporary_files:
        raise IndexMinsBootstrapApplyError(
            "index_mins target staging files already exist; refusing to continue"
        )
    for layer in ("raw", "silver"):
        audit = _audit_by_layer(audits, layer)
        if audit.invalid_existing_count:
            raise IndexMinsBootstrapApplyError(
                f"{layer} has invalid existing targets; formal apply is stopped"
            )


def _validate_fallback_targets_present(
    *,
    lake_root: Path,
    source_empty_scope: Mapping[str, Sequence[int]],
) -> None:
    """Require the separately audited Silver fallback files before apply.

    The native Raw frequencies are intentionally absent for source-empty dates;
    the corresponding Silver partitions must already have passed the bounded
    fallback audit and therefore must be present before the full Bootstrap can
    continue.
    """

    missing: list[str] = []
    for trade_date, frequencies in source_empty_scope.items():
        for frequency in frequencies:
            target_path = silver_index_mins_path(lake_root, frequency, trade_date)
            if not target_path.is_file():
                missing.append(str(target_path))
    if missing:
        raise IndexMinsBootstrapApplyError(
            "approved Silver fallback targets are missing: "
            + ", ".join(missing[:10])
        )


def _write_stage_report(
    path: Path,
    base: Mapping[str, object],
    *,
    stage: str,
    batch_size: int,
    completed_batch_end: str,
    records: Sequence[Mapping[str, object]],
) -> None:
    _write_json(
        path,
        dict(base)
        | {
            "stage": stage,
            "batch_size": batch_size,
            "completed_batch_end": completed_batch_end,
            "records": [dict(record) for record in records],
        },
    )


def run_bootstrap_apply(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    source_report_path: Path,
    fallback_report_path: Path,
    output_dir: Path,
    end_date: str,
    batch_size: int = 20,
    apply_id: str | None = None,
    raw_writer: Callable[..., Any] = write_raw_index_mins_partition_from_prod_db,
    silver_writer: Callable[..., Any] = write_silver_index_mins_partition,
    source_scope_loader: Callable[..., dict[str, IndexMinsActivePool]] = (
        load_historical_index_mins_code_scopes
    ),
) -> dict[str, object]:
    """Generate all missing index_mins Raw/Silver files after strict gates."""

    if batch_size <= 0 or batch_size > _MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {_MAX_BATCH_SIZE}")
    lake_root = lake_root.expanduser().resolve()
    if not lake_root.is_dir():
        raise IndexMinsBootstrapApplyError(f"lake root is not a directory: {lake_root}")
    apply_id = apply_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = _report_paths(output_dir, apply_id)
    started_at = perf_counter()
    stage = "preflight"
    raw_records: list[dict[str, object]] = []
    silver_records: list[dict[str, object]] = []

    source_report = _load_json(source_report_path)
    fallback_report = _load_json(fallback_report_path)
    with duckdb_resource.connect() as connection:
        date_plan = build_date_plan(
            connection=connection,
            lake_root=lake_root,
            end_date=end_date,
        )
        source_empty_scope = _validate_source_reports(
            source_report=source_report,
            fallback_report=fallback_report,
            date_plan=date_plan,
            lake_root=lake_root,
        )
        disk_budget = source_report["disk_budget"]
        required_free_bytes = int(disk_budget["estimated_required_bytes"])
        disk_free_bytes = shutil.disk_usage(lake_root).free
        if disk_free_bytes < required_free_bytes:
            raise IndexMinsBootstrapApplyError(
                "insufficient lake disk space: "
                f"free={disk_free_bytes}, required={required_free_bytes}"
            )
        preflight_audits = audit_index_mins_targets(
            connection=connection,
            lake_root=lake_root,
            expected_trade_dates=date_plan.expected_trade_dates,
        )
        _validate_preflight_targets(
            preflight_audits,
            _temporary_target_files(lake_root),
        )
        _validate_fallback_targets_present(
            lake_root=lake_root,
            source_empty_scope=source_empty_scope,
        )
        scopes = source_scope_loader(
            connection=connection,
            lake_root=lake_root,
            trade_dates=date_plan.expected_trade_dates,
        )

    if tuple(sorted(scopes)) != tuple(sorted(date_plan.expected_trade_dates)):
        raise IndexMinsBootstrapApplyError("historical source scope does not cover every date")
    base = _base_report(
        apply_id=apply_id,
        lake_root=lake_root,
        date_plan=date_plan,
        source_report_path=source_report_path,
        fallback_report_path=fallback_report_path,
        disk_free_bytes=disk_free_bytes,
        required_free_bytes=required_free_bytes,
    )

    try:
        stage = "raw"
        for batch_start in range(0, len(date_plan.expected_trade_dates), batch_size):
            batch_dates = date_plan.expected_trade_dates[batch_start : batch_start + batch_size]
            for trade_date in batch_dates:
                active_pool = scopes[trade_date]
                for source_freq in INDEX_MINS_SOURCE_FREQS:
                    frequency = int(source_freq[:-3])
                    if frequency in source_empty_scope.get(trade_date, ()):
                        raw_records.append(
                            {
                                "partition_key": trade_date,
                                "trade_date": trade_date,
                                "source_freq": source_freq,
                                "source_method": "prod_db_raw_index_mins",
                                "write_mode": "source_empty_exempt",
                                "source_empty_reason": "source_probe_target_frequency_empty",
                                "target_path": str(
                                    raw_index_mins_path(
                                        lake_root,
                                        source_freq,
                                        trade_date,
                                    )
                                ),
                                "source_scope_count": active_pool.code_count,
                                "source_scope_hash": active_pool.code_set_hash,
                                "source_row_count": 0,
                                "written_row_count": 0,
                                "skipped": True,
                            }
                        )
                        continue
                    result = raw_writer(
                        lake_root=lake_root,
                        duckdb=duckdb_resource,
                        prod_postgres=prod_postgres,
                        source_freq=source_freq,
                        partition_key=trade_date,
                        active_pool=active_pool,
                    )
                    metadata = _result_metadata(result)
                    metadata.update(
                        {
                            "trade_date": trade_date,
                            "source_scope_count": active_pool.code_count,
                            "source_scope_hash": active_pool.code_set_hash,
                        }
                    )
                    raw_records.append(metadata)
            _write_stage_report(
                paths["raw_batch"],
                base,
                stage="raw",
                batch_size=batch_size,
                completed_batch_end=batch_dates[-1],
                records=raw_records,
            )

        stage = "raw_audit"
        with duckdb_resource.connect() as connection:
            raw_audits = audit_index_mins_targets(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=date_plan.expected_trade_dates,
                raw_source_empty_scope=source_empty_scope,
            )
        raw_audit = _audit_by_layer(raw_audits, "raw")
        _write_json(
            paths["raw_audit"],
            {**base, "stage": stage, "audit": _audit_summary(raw_audit)},
        )
        if not _target_audits_pass(raw_audits, "raw"):
            raise IndexMinsBootstrapApplyError("Raw full reconciliation failed")

        stage = "silver"
        for batch_start in range(0, len(date_plan.expected_trade_dates), batch_size):
            batch_dates = date_plan.expected_trade_dates[batch_start : batch_start + batch_size]
            for trade_date in batch_dates:
                for silver_freq in INDEX_MINS_SILVER_FREQS:
                    if silver_freq in source_empty_scope.get(trade_date, ()):
                        silver_records.append(
                            {
                                "trade_date": trade_date,
                                "silver_freq": f"{silver_freq}min",
                                "source_freq": "5min",
                                "source_mode": "derived_fallback",
                                "source_empty_reason": "source_probe_target_frequency_empty",
                                "write_mode": "reuse_existing_fallback",
                                "silver_file_path": str(
                                    silver_index_mins_path(
                                        lake_root,
                                        silver_freq,
                                        trade_date,
                                    )
                                ),
                                "skipped": True,
                            }
                        )
                        continue
                    result = silver_writer(
                        lake_root=lake_root,
                        duckdb=duckdb_resource,
                        freq=silver_freq,
                        partition_key=trade_date,
                    )
                    metadata = _result_metadata(result)
                    metadata["trade_date"] = trade_date
                    silver_records.append(metadata)
            _write_stage_report(
                paths["silver_batch"],
                base,
                stage="silver",
                batch_size=batch_size,
                completed_batch_end=batch_dates[-1],
                records=silver_records,
            )

        stage = "silver_audit"
        with duckdb_resource.connect() as connection:
            final_audits = audit_index_mins_targets(
                connection=connection,
                lake_root=lake_root,
                expected_trade_dates=date_plan.expected_trade_dates,
                raw_source_empty_scope=source_empty_scope,
            )
        _write_json(
            paths["silver_audit"],
            {
                **base,
                "stage": stage,
                "raw_audit": _audit_summary(_audit_by_layer(final_audits, "raw")),
                "silver_audit": _audit_summary(_audit_by_layer(final_audits, "silver")),
            },
        )
        if not _target_audits_pass(final_audits, "raw") or not _target_audits_pass(
            final_audits, "silver"
        ):
            raise IndexMinsBootstrapApplyError("final Raw/Silver reconciliation failed")

        final_report = dict(base) | {
            "stage": "final",
            "raw_records": raw_records,
            "silver_records": silver_records,
            "raw_audit": _audit_summary(_audit_by_layer(final_audits, "raw")),
            "silver_audit": _audit_summary(_audit_by_layer(final_audits, "silver")),
            "historical_source_scope": {
                "date_count": len(scopes),
                "code_count_min": min(pool.code_count for pool in scopes.values()),
                "code_count_max": max(pool.code_count for pool in scopes.values()),
            },
            "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
            "should_stop": False,
        }
        _write_json(paths["final"], final_report)
        return {"report_paths": {key: str(path) for key, path in paths.items()}, **final_report}
    except Exception as error:
        _write_json(
            paths["failure"],
            dict(base)
            | {
                "stage": stage,
                "should_stop": True,
                "error_type": type(error).__name__,
                "error": str(error),
                "raw_record_count": len(raw_records),
                "silver_record_count": len(silver_records),
                "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
            },
        )
        if isinstance(error, IndexMinsBootstrapApplyError):
            raise
        raise IndexMinsBootstrapApplyError(
            f"index_mins Bootstrap failed during {stage}: {error}"
        ) from error


__all__ = [
    "INDEX_MINS_APPROVED_SOURCE_EMPTY_FALLBACK_SCOPE",
    "IndexMinsBootstrapApplyError",
    "load_historical_index_mins_code_scopes",
    "run_bootstrap_apply",
]
