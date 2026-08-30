"""Versioned Raw Tushare ETF Basic snapshot."""

import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg
import duckdb

from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_SNAPSHOT_ID,
    etf_basic_staging_path,
    lake_path_template,
    raw_etf_basic_snapshot_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_ETF_BASIC_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.etf_basic import (
    ETF_BASIC_CODE_SUFFIXES,
    ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT,
    ETF_BASIC_LIST_STATUSES,
    ETF_BASIC_PAGE_LIMIT,
    ETF_BASIC_SILVER_SUFFIXES,
    ETF_BASIC_SOURCE_API,
    ETF_BASIC_SOURCE_COLUMNS,
    compute_etf_basic_snapshot_hash,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.tushare_api_io import fetch_tushare_full_file_to_raw
from orchestrator.utils.dg_log_helper import DgStdoutLogger

ETF_BASIC_RAW_COLUMN_TYPES = {
    column.name: column.type for column in RAW_TUSHARE_ETF_BASIC_SCHEMA
}
ETF_BASIC_RAW_DESCRIPTION = (
    "从 Tushare 保存无业务过滤的 ETF 基础信息完整快照，包含沪深场内和源端其它后缀/状态；"
    "供同版 Silver 和后续分钟范围校验追溯。"
)
LOGGER = DgStdoutLogger("etf_basic.raw")


class EtfBasicSnapshotValidationError(RuntimeError):
    """Fail-closed validation error raised before a formal snapshot is changed."""


@dataclass(frozen=True)
class EtfBasicRawSnapshotAudit:
    path: Path
    observed_columns: tuple[str, ...]
    observed_types: tuple[str, ...]
    row_count: int
    rows: tuple[dict[str, object], ...]
    source_contract_failures: tuple[str, ...]
    key_domain_failures: tuple[str, ...]
    content_hash_failures: tuple[str, ...]
    raw_snapshot_hash: str | None
    status_counts: dict[str, int]
    suffix_counts: dict[str, int]
    list_date_null_counts: dict[str, object]
    failure_counts: dict[str, int]
    failure_samples: tuple[dict[str, object], ...]

    @property
    def passed(self) -> bool:
        return not (
            self.source_contract_failures
            or self.key_domain_failures
            or self.content_hash_failures
        )


@dataclass(frozen=True)
class EtfBasicRawSnapshotWriteResult:
    target_path: Path
    staging_path: Path
    source_row_count: int
    row_count: int
    page_count: int
    raw_snapshot_hash: str
    observed_at: str
    status_counts: dict[str, int]
    suffix_counts: dict[str, int]
    list_date_null_counts: dict[str, object]
    write_mode: str


def _code_suffix(value: object) -> str:
    if not isinstance(value, str) or "." not in value:
        return ""
    return value.rsplit(".", maxsplit=1)[-1]


def _bounded_samples(
    samples: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    return tuple(dict(sample) for sample in samples[:ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT])


def _read_snapshot_rows(
    *,
    path: Path,
    duckdb_resource: DuckDBResource,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[dict[str, object], ...], int]:
    with duckdb_resource.connect() as connection:
        description = connection.execute(
            describe_parquet_query(path, hive_partitioning=False)
        ).fetchall()
        observed_columns = tuple(str(row[0]) for row in description)
        observed_types = tuple(str(row[1]).upper() for row in description)
        row_count = int(
            connection.execute(
                count_parquet_query(path, hive_partitioning=False)
            ).fetchone()[0]
        )
        if observed_columns != ETF_BASIC_SOURCE_COLUMNS:
            return observed_columns, observed_types, (), row_count
        selected_rows = connection.execute(
            "SELECT "
            + ", ".join(ETF_BASIC_SOURCE_COLUMNS)
            + f" FROM {read_parquet(path, hive_partitioning=False)}"
        ).fetchall()
    rows = tuple(
        dict(zip(ETF_BASIC_SOURCE_COLUMNS, row, strict=True)) for row in selected_rows
    )
    return observed_columns, observed_types, rows, row_count


def audit_etf_basic_raw_snapshot(
    *,
    path: Path,
    duckdb_resource: DuckDBResource,
    expected_source_row_count: int | None = None,
    expected_snapshot_hash: str | None = None,
) -> EtfBasicRawSnapshotAudit:
    """Audit one Raw file without scanning snapshot directories or older versions."""

    expected_types = tuple(
        ETF_BASIC_RAW_COLUMN_TYPES[column] for column in ETF_BASIC_SOURCE_COLUMNS
    )
    source_failures: list[str] = []
    key_failures: list[str] = []
    content_failures: list[str] = []
    failure_counts: Counter[str] = Counter()
    samples: list[dict[str, object]] = []

    if not path.is_file():
        return EtfBasicRawSnapshotAudit(
            path=path,
            observed_columns=(),
            observed_types=(),
            row_count=0,
            rows=(),
            source_contract_failures=("file_unreadable",),
            key_domain_failures=(),
            content_hash_failures=("source_contract_required",),
            raw_snapshot_hash=None,
            status_counts={},
            suffix_counts={},
            list_date_null_counts={"total": 0, "by_status": {}},
            failure_counts={"file_unreadable": 1},
            failure_samples=(),
        )

    try:
        observed_columns, observed_types, rows, row_count = _read_snapshot_rows(
            path=path,
            duckdb_resource=duckdb_resource,
        )
    except (OSError, duckdb.Error) as error:
        return EtfBasicRawSnapshotAudit(
            path=path,
            observed_columns=(),
            observed_types=(),
            row_count=0,
            rows=(),
            source_contract_failures=("file_unreadable",),
            key_domain_failures=(),
            content_hash_failures=("source_contract_required",),
            raw_snapshot_hash=None,
            status_counts={},
            suffix_counts={},
            list_date_null_counts={"total": 0, "by_status": {}},
            failure_counts={"file_unreadable": 1},
            failure_samples=(
                {
                    "reason_code": "file_unreadable",
                    "error_type": type(error).__name__,
                },
            ),
        )

    if observed_columns != ETF_BASIC_SOURCE_COLUMNS:
        source_failures.append("column_contract_mismatch")
        failure_counts["column_contract_mismatch"] = 1
        samples.append(
            {
                "reason_code": "column_contract_mismatch",
                "observed_columns": list(observed_columns),
            }
        )
    if observed_types != expected_types:
        source_failures.append("type_contract_mismatch")
        failure_counts["type_contract_mismatch"] = 1
        samples.append(
            {
                "reason_code": "type_contract_mismatch",
                "observed_types": list(observed_types),
            }
        )
    if row_count <= 0:
        source_failures.append("empty_snapshot")
        failure_counts["empty_snapshot"] = 1
    if expected_source_row_count is not None and row_count != expected_source_row_count:
        source_failures.append("source_row_count_mismatch")
        failure_counts["source_row_count_mismatch"] = abs(
            expected_source_row_count - row_count
        )
        samples.append(
            {
                "reason_code": "source_row_count_mismatch",
                "expected": expected_source_row_count,
                "observed": row_count,
            }
        )

    status_counts: Counter[str] = Counter()
    suffix_counts: Counter[str] = Counter()
    list_date_null_by_status: Counter[str] = Counter()
    code_counts: Counter[object] = Counter()
    if not source_failures:
        for row in rows:
            ts_code = row["ts_code"]
            list_status = row["list_status"]
            suffix = _code_suffix(ts_code)
            status_key = "<NULL>" if list_status is None else str(list_status)
            suffix_key = "<INVALID>" if not suffix else suffix
            status_counts[status_key] += 1
            suffix_counts[suffix_key] += 1
            code_counts[ts_code] += 1
            if row["list_date"] is None:
                list_date_null_by_status[status_key] += 1

            row_reasons: list[str] = []
            if not isinstance(ts_code, str) or not ts_code:
                row_reasons.append("ts_code_empty")
            if list_status not in ETF_BASIC_LIST_STATUSES:
                row_reasons.append("list_status_unknown")
            if suffix not in ETF_BASIC_CODE_SUFFIXES:
                row_reasons.append("code_suffix_unknown")
            if suffix in ETF_BASIC_SILVER_SUFFIXES and row["exchange"] != suffix:
                row_reasons.append("exchange_suffix_mismatch")
            if row_reasons:
                for reason in row_reasons:
                    failure_counts[reason] += 1
                    if reason not in key_failures:
                        key_failures.append(reason)
                samples.append(
                    {
                        "reason_code": ",".join(row_reasons),
                        "ts_code": ts_code,
                        "list_status": list_status,
                        "exchange": row["exchange"],
                    }
                )

        duplicate_codes = sorted(
            (
                ("<NULL>" if code is None else str(code), count)
                for code, count in code_counts.items()
                if count > 1
            ),
            key=lambda item: item[0],
        )
        if duplicate_codes:
            key_failures.append("ts_code_duplicate")
            failure_counts["ts_code_duplicate"] = sum(
                count - 1 for _, count in duplicate_codes
            )
            samples.extend(
                {
                    "reason_code": "ts_code_duplicate",
                    "ts_code": code,
                    "row_count": count,
                }
                for code, count in duplicate_codes
            )

    snapshot_hash: str | None = None
    if source_failures:
        content_failures.append("source_contract_required")
        failure_counts["source_contract_required"] = 1
    elif key_failures:
        content_failures.append("key_domain_required")
        failure_counts["key_domain_required"] = 1
    else:
        try:
            snapshot_hash = compute_etf_basic_snapshot_hash(rows)
        except ValueError as error:
            content_failures.append("content_hash_unavailable")
            failure_counts["content_hash_unavailable"] = 1
            samples.append(
                {
                    "reason_code": "content_hash_unavailable",
                    "error": str(error),
                }
            )
        if (
            snapshot_hash is not None
            and expected_snapshot_hash is not None
            and snapshot_hash != expected_snapshot_hash
        ):
            content_failures.append("content_hash_mismatch")
            failure_counts["content_hash_mismatch"] = 1
            samples.append(
                {
                    "reason_code": "content_hash_mismatch",
                    "expected": expected_snapshot_hash,
                    "observed": snapshot_hash,
                }
            )

    return EtfBasicRawSnapshotAudit(
        path=path,
        observed_columns=observed_columns,
        observed_types=observed_types,
        row_count=row_count,
        rows=rows,
        source_contract_failures=tuple(source_failures),
        key_domain_failures=tuple(key_failures),
        content_hash_failures=tuple(content_failures),
        raw_snapshot_hash=snapshot_hash,
        status_counts=dict(sorted(status_counts.items())),
        suffix_counts=dict(sorted(suffix_counts.items())),
        list_date_null_counts={
            "total": sum(list_date_null_by_status.values()),
            "by_status": dict(sorted(list_date_null_by_status.items())),
        },
        failure_counts=dict(sorted(failure_counts.items())),
        failure_samples=_bounded_samples(samples),
    )


def _require_passed_audit(
    audit: EtfBasicRawSnapshotAudit,
    *,
    reason_code: str,
) -> None:
    if audit.passed:
        return
    raise EtfBasicSnapshotValidationError(
        f"{reason_code}: path={audit.path}, "
        f"source_contract_failures={audit.source_contract_failures}, "
        f"key_domain_failures={audit.key_domain_failures}, "
        f"content_hash_failures={audit.content_hash_failures}, "
        f"failure_samples={audit.failure_samples}."
    )


def _prepare_atomic_paths(
    *,
    lake_root_path: Path,
    staging_root_path: Path,
    staging_path: Path,
) -> None:
    if not lake_root_path.is_dir():
        raise EtfBasicSnapshotValidationError(
            f"etf_basic_lake_root_unavailable: {lake_root_path}."
        )
    if not staging_root_path.is_dir():
        raise EtfBasicSnapshotValidationError(
            f"etf_basic_staging_root_unavailable: {staging_root_path}."
        )
    if lake_root_path.stat().st_dev != staging_root_path.stat().st_dev:
        raise EtfBasicSnapshotValidationError(
            "etf_basic_staging_filesystem_mismatch: staging and formal Lake must "
            "share one filesystem for atomic os.replace."
        )
    formal_dataset_root = lake_root_path / "raw" / "tushare" / "etf_basic"
    formal_dataset_root.mkdir(parents=True, exist_ok=True)
    staging_path.parent.mkdir(parents=True, exist_ok=True)


def write_etf_basic_raw_snapshot(
    *,
    tushare: TushareResource,
    duckdb_resource: DuckDBResource,
    lake_root_path: Path,
    staging_root_path: Path,
    run_id: str,
    observed_at: str,
) -> EtfBasicRawSnapshotWriteResult:
    """Fetch, validate, and atomically publish or reuse one immutable snapshot."""

    staging_path = etf_basic_staging_path(staging_root_path, run_id, "raw")
    _prepare_atomic_paths(
        lake_root_path=lake_root_path,
        staging_root_path=staging_root_path,
        staging_path=staging_path,
    )

    fetch_metadata = fetch_tushare_full_file_to_raw(
        tushare=tushare,
        duckdb=duckdb_resource,
        api_name=ETF_BASIC_SOURCE_API,
        api_params={},
        fields=ETF_BASIC_SOURCE_COLUMNS,
        column_types=ETF_BASIC_RAW_COLUMN_TYPES,
        target_path=staging_path,
        allow_empty=False,
        limit=ETF_BASIC_PAGE_LIMIT,
    )
    source_row_count = int(fetch_metadata["dagster/row_count"])
    page_count = int(fetch_metadata["goldenshare/page_count"])

    candidate_audit = audit_etf_basic_raw_snapshot(
        path=staging_path,
        duckdb_resource=duckdb_resource,
        expected_source_row_count=source_row_count,
    )
    _require_passed_audit(
        candidate_audit,
        reason_code="etf_basic_candidate_invalid",
    )
    raw_snapshot_hash = candidate_audit.raw_snapshot_hash
    if raw_snapshot_hash is None:
        raise EtfBasicSnapshotValidationError(
            "etf_basic_candidate_hash_missing: validated candidate has no content hash."
        )

    readback_audit = audit_etf_basic_raw_snapshot(
        path=staging_path,
        duckdb_resource=duckdb_resource,
        expected_source_row_count=source_row_count,
        expected_snapshot_hash=raw_snapshot_hash,
    )
    _require_passed_audit(
        readback_audit,
        reason_code="etf_basic_candidate_readback_mismatch",
    )

    target_path = raw_etf_basic_snapshot_path(lake_root_path, raw_snapshot_hash)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.parent.stat().st_dev != staging_path.parent.stat().st_dev:
        raise EtfBasicSnapshotValidationError(
            "etf_basic_staging_filesystem_mismatch: candidate and immutable target "
            "must share one filesystem for atomic os.replace."
        )

    if target_path.exists():
        existing_audit = audit_etf_basic_raw_snapshot(
            path=target_path,
            duckdb_resource=duckdb_resource,
            expected_source_row_count=source_row_count,
            expected_snapshot_hash=raw_snapshot_hash,
        )
        _require_passed_audit(
            existing_audit,
            reason_code="etf_basic_snapshot_conflict",
        )
        staging_path.unlink()
        write_mode = "reuse_existing"
    else:
        os.replace(staging_path, target_path)
        write_mode = "write_new"

    return EtfBasicRawSnapshotWriteResult(
        target_path=target_path,
        staging_path=staging_path,
        source_row_count=source_row_count,
        row_count=candidate_audit.row_count,
        page_count=page_count,
        raw_snapshot_hash=raw_snapshot_hash,
        observed_at=observed_at,
        status_counts=candidate_audit.status_counts,
        suffix_counts=candidate_audit.suffix_counts,
        list_date_null_counts=candidate_audit.list_date_null_counts,
        write_mode=write_mode,
    )


def build_etf_basic_raw_materialization_metadata(
    result: EtfBasicRawSnapshotWriteResult,
) -> dict[str, object]:
    """Build the exact P2 materialization contract without Dagster storage ids."""

    return build_materialization_metadata(
        uri=result.target_path,
        row_count=result.row_count,
        observed_columns=ETF_BASIC_SOURCE_COLUMNS,
        extra_metadata={
            "source_row_count": result.source_row_count,
            "raw_snapshot_hash": result.raw_snapshot_hash,
            "observed_at": result.observed_at,
            "api_name": ETF_BASIC_SOURCE_API,
            "business_params": {},
            "fields": list(ETF_BASIC_SOURCE_COLUMNS),
            "page_limit": ETF_BASIC_PAGE_LIMIT,
            "page_count": result.page_count,
            "status_counts": result.status_counts,
            "suffix_counts": result.suffix_counts,
            "list_date_null_counts": result.list_date_null_counts,
            "write_mode": result.write_mode,
        },
    )


@dg.asset(
    name="raw_tushare_etf_basic",
    group_name="etf_basic",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="etf_basic",
        source_system=SourceSystem.TUSHARE,
        source_api=ETF_BASIC_SOURCE_API,
        source_doc="docs/sources/tushare/ETF专题/0385_ETF基础信息.md",
        data_contract="source_mirror_versioned",
        column_schema=RAW_TUSHARE_ETF_BASIC_SCHEMA,
        path_template=lake_path_template(
            raw_etf_basic_snapshot_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_SNAPSHOT_ID,
            )
        ),
    ),
    description=ETF_BASIC_RAW_DESCRIPTION,
)
def raw_tushare_etf_basic(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    observed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    staging_path = etf_basic_staging_path(
        Path(DEFAULT_LAKE_STAGING_ROOT),
        context.run_id,
        "raw",
    )
    LOGGER.stdout(
        "etf_basic_source_fetch_started",
        api_name=ETF_BASIC_SOURCE_API,
        staging_path=str(staging_path),
    )
    result = write_etf_basic_raw_snapshot(
        tushare=tushare,
        duckdb_resource=duckdb,
        lake_root_path=lake_root.root(),
        staging_root_path=Path(DEFAULT_LAKE_STAGING_ROOT),
        run_id=context.run_id,
        observed_at=observed_at,
    )
    LOGGER.stdout(
        "etf_basic_source_page_completed",
        page_count=result.page_count,
        source_row_count=result.source_row_count,
    )
    LOGGER.stdout(
        "etf_basic_candidate_validated",
        row_count=result.row_count,
        raw_snapshot_hash=result.raw_snapshot_hash,
    )
    LOGGER.stdout(
        "etf_basic_snapshot_promoted",
        write_mode=result.write_mode,
        raw_snapshot_hash=result.raw_snapshot_hash,
    )
    return dg.MaterializeResult(
        metadata=build_etf_basic_raw_materialization_metadata(result)
    )
