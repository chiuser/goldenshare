"""Explicit source staging and candidate build for ``idx_factor_pro`` history."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from orchestrator.defs.bootstrap.idx_factor_pro_bootstrap_plan import (
    BOOTSTRAP_BATCH_DATE_COUNT,
    IdxFactorProBootstrapPlan,
    file_sha256,
    hash_payload,
    load_idx_factor_pro_bootstrap_plan,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.io.idx_factor_pro_raw_writer import (
    validate_idx_factor_pro_raw_relation,
)
from orchestrator.defs.io.idx_factor_pro_silver_writer import (
    validate_idx_factor_pro_raw_silver_parity,
    validate_idx_factor_pro_silver_relation,
)
from orchestrator.defs.paths import (
    raw_idx_factor_pro_path,
    silver_index_factor_pro_path,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_PAGE_LIMIT,
    IDX_FACTOR_PRO_RAW_COLUMN_TYPES,
    IDX_FACTOR_PRO_SILVER_COLUMN_TYPES,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    active_idx_factor_pro_daily_codes,
    build_idx_factor_pro_history_request,
)


class IdxFactorProBootstrapStageError(RuntimeError):
    """Raised before unsafe source or candidate staging can continue."""


@dataclass(frozen=True, slots=True)
class SourcePageAudit:
    ts_code: str
    offset: int
    row_count: int
    min_trade_date: str | None
    max_trade_date: str | None
    parquet_path: str
    parquet_sha256: str
    key_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CandidateFileAudit:
    layer: str
    trade_date: str
    path: str
    row_count: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


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
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IdxFactorProBootstrapStageError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, Mapping):
        raise IdxFactorProBootstrapStageError(f"{label} must be a JSON object")
    return value


def source_page_path(
    plan: IdxFactorProBootstrapPlan, ts_code: str, offset: int
) -> Path:
    return (
        plan.candidate_root
        / "source"
        / f"ts_code={ts_code}"
        / f"offset={offset:08d}"
        / "part-000.parquet"
    )


def source_page_sidecar_path(path: Path) -> Path:
    return path.with_suffix(".json")


def source_stage_report_path(
    plan: IdxFactorProBootstrapPlan,
    selected_codes: Sequence[str] | None = None,
) -> Path:
    all_codes = tuple(value.ts_code for value in plan.code_plans)
    selected = tuple(selected_codes or all_codes)
    suffix = "" if set(selected) == set(all_codes) else f"_scope_{hash_payload(selected)[:12]}"
    return plan.report_root / (
        f"idx_factor_pro_source_stage_{plan.plan_hash}{suffix}.json"
    )


def candidate_report_path(plan: IdxFactorProBootstrapPlan) -> Path:
    return plan.report_root / f"idx_factor_pro_candidate_{plan.plan_hash}.json"


def _typed_source_select(relation_name: str) -> str:
    return ", ".join(
        f'CAST("{column}" AS {IDX_FACTOR_PRO_RAW_COLUMN_TYPES[column]}) AS "{column}"'
        for column in IDX_FACTOR_PRO_SOURCE_COLUMNS
    ).join(("SELECT ", f" FROM {relation_name}"))


def _validate_source_rows(
    *,
    rows: Sequence[Mapping[str, object]],
    columns: Sequence[str],
    ts_code: str,
    source_start_date: str,
    end_date: str,
    seen_keys: set[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    if tuple(columns) != IDX_FACTOR_PRO_SOURCE_COLUMNS:
        raise IdxFactorProBootstrapStageError(
            "source schema drift: "
            f"expected={IDX_FACTOR_PRO_SOURCE_COLUMNS!r}, observed={tuple(columns)!r}"
        )
    page_keys: list[tuple[str, str]] = []
    for row in rows:
        if tuple(row) != IDX_FACTOR_PRO_SOURCE_COLUMNS:
            raise IdxFactorProBootstrapStageError(
                "source row keys/order differ from the frozen 89-field contract"
            )
        code = str(row.get("ts_code") or "").strip().upper()
        trade_date = str(row.get("trade_date") or "").strip()
        if code != ts_code:
            raise IdxFactorProBootstrapStageError(
                f"source page returned another code: expected={ts_code}, got={code}"
            )
        if len(trade_date) != 8 or not trade_date.isdigit():
            raise IdxFactorProBootstrapStageError(
                f"source page returned an invalid trade_date: {trade_date!r}"
            )
        iso_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
        if not source_start_date <= iso_date <= end_date:
            raise IdxFactorProBootstrapStageError(
                f"source page returned an out-of-range date: {iso_date}"
            )
        key = (code, trade_date)
        if key in seen_keys or key in page_keys:
            raise IdxFactorProBootstrapStageError(
                f"source page contains a duplicate key: {key!r}"
            )
        page_keys.append(key)
    return tuple(page_keys)


def _write_source_page(
    *,
    duckdb_resource: DuckDBResource,
    path: Path,
    rows: Sequence[Mapping[str, object]],
) -> None:
    try:
        import pandas as pd
    except ModuleNotFoundError as error:
        raise IdxFactorProBootstrapStageError(
            "pandas is required for bounded source-page staging"
        ) from error
    frame = pd.DataFrame.from_records(rows, columns=IDX_FACTOR_PRO_SOURCE_COLUMNS)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb_resource.connect() as connection:
        connection.register("idx_factor_pro_bootstrap_page", frame)
        try:
            connection.execute(
                copy_query_to_parquet(
                    _typed_source_select("idx_factor_pro_bootstrap_page"),
                    temporary,
                )
            )
        finally:
            connection.unregister("idx_factor_pro_bootstrap_page")
    if path.exists():
        temporary.unlink(missing_ok=True)
        raise IdxFactorProBootstrapStageError(
            f"source page appeared while staging; refusing overwrite: {path}"
        )
    os.replace(temporary, path)


def stage_idx_factor_pro_source(
    *,
    plan_report_path: Path,
    expected_plan_hash: str,
    tushare: TushareResource,
    duckdb_resource: DuckDBResource | None = None,
    apply: bool = False,
    selected_codes: Sequence[str] | None = None,
) -> Path:
    """Fetch frozen per-code pages to source staging; never writes formal Lake."""

    if not apply:
        raise IdxFactorProBootstrapStageError("source staging requires apply=True")
    plan = load_idx_factor_pro_bootstrap_plan(
        plan_report_path,
        expected_plan_hash=expected_plan_hash,
    )
    if not plan.disk_budget.passed:
        raise IdxFactorProBootstrapStageError("frozen disk budget did not pass")
    code_plans = {value.ts_code: value for value in plan.code_plans}
    requested_codes = tuple(selected_codes or code_plans)
    unknown = tuple(sorted(set(requested_codes) - set(code_plans)))
    if unknown:
        raise IdxFactorProBootstrapStageError(
            f"selected codes are outside the frozen plan: {unknown!r}"
        )
    resource = duckdb_resource or DuckDBResource()
    page_audits: list[SourcePageAudit] = []
    page_hashes: set[str] = set()
    request_count = 0
    for code in requested_codes:
        code_plan = code_plans[code]
        seen_keys: set[tuple[str, str]] = set()
        exhausted = False
        for request_index in range(code_plan.max_request_count):
            offset = request_index * IDX_FACTOR_PRO_PAGE_LIMIT
            request = build_idx_factor_pro_history_request(
                code,
                code_plan.source_start_date,
                code_plan.end_date,
                offset,
            )
            request_count += 1
            result = tushare.call(request.api_name, request.params, request.fields)
            rows = tuple(result.rows)
            keys = _validate_source_rows(
                rows=rows,
                columns=result.columns,
                ts_code=code,
                source_start_date=code_plan.source_start_date,
                end_date=code_plan.end_date,
                seen_keys=seen_keys,
            )
            if not rows:
                exhausted = True
                break
            path = source_page_path(plan, code, offset)
            if path.exists():
                sidecar = _load_json(
                    source_page_sidecar_path(path), label="source-page sidecar"
                )
                if str(sidecar.get("key_hash")) != hash_payload(keys):
                    raise IdxFactorProBootstrapStageError(
                        f"existing source page differs from current response: {path}"
                    )
            else:
                _write_source_page(
                    duckdb_resource=resource,
                    path=path,
                    rows=rows,
                )
            page_hash = file_sha256(path)
            if page_hash in page_hashes:
                raise IdxFactorProBootstrapStageError(
                    f"duplicate source page payload detected: code={code}, offset={offset}"
                )
            page_hashes.add(page_hash)
            seen_keys.update(keys)
            dates = tuple(key[1] for key in keys)
            audit = SourcePageAudit(
                ts_code=code,
                offset=offset,
                row_count=len(rows),
                min_trade_date=min(dates) if dates else None,
                max_trade_date=max(dates) if dates else None,
                parquet_path=str(path),
                parquet_sha256=page_hash,
                key_hash=hash_payload(keys),
            )
            sidecar_payload = {
                **audit.to_dict(),
                "request": {
                    "api_name": request.api_name,
                    "params": dict(request.params),
                    "fields": list(request.fields),
                },
                "schema_hash": plan.schema_hash,
                "plan_hash": plan.plan_hash,
            }
            sidecar_path = source_page_sidecar_path(path)
            if sidecar_path.exists():
                existing_sidecar = _load_json(sidecar_path, label="source-page sidecar")
                if existing_sidecar != sidecar_payload:
                    raise IdxFactorProBootstrapStageError(
                        f"existing source-page sidecar differs: {sidecar_path}"
                    )
            else:
                _atomic_write_json(sidecar_path, sidecar_payload)
            page_audits.append(audit)
            if len(rows) < IDX_FACTOR_PRO_PAGE_LIMIT:
                exhausted = True
                break
        if not exhausted:
            raise IdxFactorProBootstrapStageError(
                f"source request budget exhausted before short page: code={code}"
            )

    all_codes_complete = set(requested_codes) == set(code_plans)
    row_count = sum(value.row_count for value in page_audits)
    report_path = source_stage_report_path(plan, requested_codes)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_hash": plan.plan_hash,
        "selected_codes": list(requested_codes),
        "all_codes_complete": all_codes_complete,
        "page_count": len(page_audits),
        "request_count": request_count,
        "row_count": row_count,
        "estimated_row_count": plan.estimated_source_row_count,
        "row_count_delta": row_count - plan.estimated_source_row_count,
        "pages": [value.to_dict() for value in page_audits],
        "writes": {
            "tushare_requests": request_count,
            "source_staging": len(page_audits),
            "candidate_files": 0,
            "formal_lake": 0,
            "dagster_events": 0,
        },
    }
    _atomic_write_json(report_path, payload)
    return report_path


def _source_paths_from_report(
    *, plan: IdxFactorProBootstrapPlan, source_report_path: Path
) -> tuple[Path, ...]:
    payload = _load_json(source_report_path, label="source-stage report")
    if payload.get("plan_hash") != plan.plan_hash:
        raise IdxFactorProBootstrapStageError("source-stage plan hash mismatch")
    if payload.get("all_codes_complete") is not True:
        raise IdxFactorProBootstrapStageError(
            "all frozen codes must be staged before candidate build"
        )
    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise IdxFactorProBootstrapStageError("source-stage report has no pages")
    paths: list[Path] = []
    for item in pages:
        if not isinstance(item, Mapping):
            raise IdxFactorProBootstrapStageError("invalid source page report item")
        path = Path(str(item.get("parquet_path")))
        if not path.is_file() or file_sha256(path) != item.get("parquet_sha256"):
            raise IdxFactorProBootstrapStageError(
                f"source page is missing or changed: {path}"
            )
        paths.append(path)
    return tuple(paths)


def _raw_candidate_select(source_relation: str, trade_date: str) -> str:
    fields = ", ".join(f'"{column}"' for column in IDX_FACTOR_PRO_SOURCE_COLUMNS)
    return (
        f"SELECT {fields} FROM {source_relation} "
        f"WHERE trade_date = {duckdb_string(trade_date.replace('-', ''))} "
        "ORDER BY ts_code, trade_date"
    )


def _silver_candidate_select(raw_path: Path) -> str:
    numeric = ", ".join(
        f'CAST("{column}" AS {IDX_FACTOR_PRO_SILVER_COLUMN_TYPES[column]}) AS "{column}"'
        for column in IDX_FACTOR_PRO_SOURCE_COLUMNS[2:]
    )
    return (
        "SELECT CAST(ts_code AS VARCHAR) AS ts_code, "
        "CAST(strptime(trade_date, '%Y%m%d') AS DATE) AS trade_date, "
        f"{numeric} FROM {read_parquet(raw_path, hive_partitioning=False)} "
        "ORDER BY ts_code, trade_date"
    )


def _write_candidate_file(connection, *, query: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    connection.execute(copy_query_to_parquet(query, temporary))
    if target.exists():
        if file_sha256(target) == file_sha256(temporary):
            temporary.unlink()
            return
        temporary.unlink()
        raise IdxFactorProBootstrapStageError(
            f"candidate target already exists with different content: {target}"
        )
    os.replace(temporary, target)


def _load_candidate_checkpoint(
    *,
    plan: IdxFactorProBootstrapPlan,
    checkpoint_path: Path,
) -> tuple[tuple[str, ...], list[CandidateFileAudit]]:
    if not checkpoint_path.exists():
        return (), []
    payload = _load_json(checkpoint_path, label="candidate checkpoint")
    if payload.get("plan_hash") != plan.plan_hash:
        raise IdxFactorProBootstrapStageError(
            "candidate checkpoint belongs to another frozen plan"
        )
    completed_value = payload.get("completed_dates")
    files_value = payload.get("files")
    if not isinstance(completed_value, list) or not isinstance(files_value, list):
        raise IdxFactorProBootstrapStageError(
            "candidate checkpoint is missing completed dates or file manifest"
        )
    completed = tuple(str(value) for value in completed_value)
    if completed != plan.candidate_trade_dates[: len(completed)]:
        raise IdxFactorProBootstrapStageError(
            "candidate checkpoint dates are not a contiguous frozen-plan prefix"
        )
    audits = [
        CandidateFileAudit(**dict(value))
        for value in files_value
        if isinstance(value, Mapping)
    ]
    if len(audits) != len(completed) * 2:
        raise IdxFactorProBootstrapStageError(
            "candidate checkpoint file count does not match completed dates"
        )
    for audit in audits:
        path = Path(audit.path)
        if not path.is_file() or file_sha256(path) != audit.sha256:
            raise IdxFactorProBootstrapStageError(
                f"checkpoint candidate is missing or changed: {path}"
            )
    return completed, audits


def _write_candidate_checkpoint(
    *,
    checkpoint_path: Path,
    plan_hash: str,
    completed_dates: Sequence[str],
    audits: Sequence[CandidateFileAudit],
    complete: bool = False,
) -> None:
    _atomic_write_json(
        checkpoint_path,
        {
            "plan_hash": plan_hash,
            "completed_dates": list(completed_dates),
            "completed_file_count": len(audits),
            "files": [value.to_dict() for value in audits],
            "complete": complete,
        },
    )


def build_idx_factor_pro_candidates(
    *,
    plan_report_path: Path,
    source_report_path: Path,
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource | None = None,
    apply: bool = False,
) -> Path:
    """Repartition staged source into audited daily Raw/Silver candidates."""

    if not apply:
        raise IdxFactorProBootstrapStageError("candidate build requires apply=True")
    plan = load_idx_factor_pro_bootstrap_plan(
        plan_report_path, expected_plan_hash=expected_plan_hash
    )
    source_paths = _source_paths_from_report(
        plan=plan, source_report_path=source_report_path
    )
    candidate_lake_root = plan.candidate_root / "candidate_lake"
    resource = duckdb_resource or DuckDBResource()
    checkpoint_path = plan.candidate_root / "candidate-checkpoint.json"
    completed_prefix, audits = _load_candidate_checkpoint(
        plan=plan,
        checkpoint_path=checkpoint_path,
    )
    completed_dates = list(completed_prefix)
    with resource.connect() as connection:
        path_values = ", ".join(duckdb_string(path) for path in source_paths)
        source_relation = (
            f"read_parquet([{path_values}], hive_partitioning=false, union_by_name=true)"
        )
        duplicate_count = int(
            connection.execute(
                f"""
                SELECT coalesce(sum(row_count - 1), 0)
                FROM (
                  SELECT ts_code, trade_date, count(*) AS row_count
                  FROM {source_relation}
                  GROUP BY ts_code, trade_date
                  HAVING count(*) > 1
                )
                """
            ).fetchone()[0]
            or 0
        )
        if duplicate_count:
            raise IdxFactorProBootstrapStageError(
                f"source staging has duplicate keys: {duplicate_count}"
            )
        for index, trade_date in enumerate(plan.candidate_trade_dates, start=1):
            expected_codes = active_idx_factor_pro_daily_codes(trade_date)
            raw_path = raw_idx_factor_pro_path(candidate_lake_root, trade_date)
            silver_path = silver_index_factor_pro_path(candidate_lake_root, trade_date)
            if trade_date in completed_prefix:
                raw_audit = validate_idx_factor_pro_raw_relation(
                    connection,
                    relation_sql=read_parquet(raw_path, hive_partitioning=False),
                    expected_codes=expected_codes,
                    partition_key=trade_date,
                )
                silver_audit = validate_idx_factor_pro_silver_relation(
                    connection,
                    relation_sql=read_parquet(silver_path, hive_partitioning=False),
                    expected_codes=expected_codes,
                    partition_key=trade_date,
                )
                parity = validate_idx_factor_pro_raw_silver_parity(
                    connection,
                    raw_relation_sql=read_parquet(raw_path, hive_partitioning=False),
                    silver_relation_sql=read_parquet(
                        silver_path,
                        hive_partitioning=False,
                    ),
                )
                if raw_audit.errors or silver_audit.errors or parity.errors:
                    raise IdxFactorProBootstrapStageError(
                        f"checkpoint candidate physical audit failed: {trade_date}"
                    )
                continue
            if raw_path.exists() or silver_path.exists():
                raise IdxFactorProBootstrapStageError(
                    "candidate files exist outside the verified checkpoint: "
                    f"trade_date={trade_date}"
                )
            _write_candidate_file(
                connection,
                query=_raw_candidate_select(source_relation, trade_date),
                target=raw_path,
            )
            raw_audit = validate_idx_factor_pro_raw_relation(
                connection,
                relation_sql=read_parquet(raw_path, hive_partitioning=False),
                expected_codes=expected_codes,
                partition_key=trade_date,
            )
            if raw_audit.errors:
                raise IdxFactorProBootstrapStageError(
                    f"Raw candidate failed for {trade_date}: {raw_audit.errors!r}"
                )
            _write_candidate_file(
                connection,
                query=_silver_candidate_select(raw_path),
                target=silver_path,
            )
            silver_audit = validate_idx_factor_pro_silver_relation(
                connection,
                relation_sql=read_parquet(silver_path, hive_partitioning=False),
                expected_codes=expected_codes,
                partition_key=trade_date,
            )
            parity = validate_idx_factor_pro_raw_silver_parity(
                connection,
                raw_relation_sql=read_parquet(raw_path, hive_partitioning=False),
                silver_relation_sql=read_parquet(silver_path, hive_partitioning=False),
            )
            if silver_audit.errors or parity.errors:
                raise IdxFactorProBootstrapStageError(
                    "Silver candidate failed: "
                    f"date={trade_date}, contract={silver_audit.errors!r}, "
                    f"parity={parity.errors!r}"
                )
            audits.extend(
                (
                    CandidateFileAudit(
                        "raw", trade_date, str(raw_path), raw_audit.row_count,
                        file_sha256(raw_path),
                    ),
                    CandidateFileAudit(
                        "silver", trade_date, str(silver_path), silver_audit.row_count,
                        file_sha256(silver_path),
                    ),
                )
            )
            completed_dates.append(trade_date)
            if index % BOOTSTRAP_BATCH_DATE_COUNT == 0:
                _write_candidate_checkpoint(
                    checkpoint_path=checkpoint_path,
                    plan_hash=plan.plan_hash,
                    completed_dates=completed_dates,
                    audits=audits,
                )
    if len(audits) != len(plan.candidate_trade_dates) * 2:
        raise IdxFactorProBootstrapStageError("candidate file count reconciliation failed")
    if sum(value.row_count for value in audits if value.layer == "raw") != plan.selected_candidate_row_count:
        raise IdxFactorProBootstrapStageError("selected source/Raw row reconciliation failed")
    report_path = candidate_report_path(plan)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_hash": plan.plan_hash,
        "source_report_path": str(source_report_path),
        "source_report_sha256": file_sha256(source_report_path),
        "candidate_lake_root": str(candidate_lake_root),
        "date_count": len(plan.candidate_trade_dates),
        "files": [value.to_dict() for value in audits],
        "raw_row_count": sum(value.row_count for value in audits if value.layer == "raw"),
        "silver_row_count": sum(
            value.row_count for value in audits if value.layer == "silver"
        ),
        "should_stop": False,
        "writes": {
            "source_staging": 0,
            "candidate_files": len(audits),
            "formal_lake": 0,
            "dynamic_partitions": 0,
            "dagster_events": 0,
        },
    }
    _atomic_write_json(report_path, payload)
    _write_candidate_checkpoint(
        checkpoint_path=checkpoint_path,
        plan_hash=plan.plan_hash,
        completed_dates=completed_dates,
        audits=audits,
        complete=True,
    )
    return report_path


__all__ = [
    "IdxFactorProBootstrapStageError",
    "build_idx_factor_pro_candidates",
    "candidate_report_path",
    "source_page_path",
    "source_stage_report_path",
    "stage_idx_factor_pro_source",
]
