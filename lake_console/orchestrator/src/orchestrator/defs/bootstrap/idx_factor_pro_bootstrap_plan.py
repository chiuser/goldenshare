"""Read-only frozen plan for the Tushare ``idx_factor_pro`` Bootstrap."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from math import floor
from pathlib import Path
from typing import Any
from uuid import uuid4

from orchestrator.defs.paths import (
    raw_idx_factor_pro_path,
    silver_index_factor_pro_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_FIRST_AVAILABLE_TRADE_DATES,
    IDX_FACTOR_PRO_PAGE_LIMIT,
    IDX_FACTOR_PRO_RAW_COLUMN_TYPES,
    IDX_FACTOR_PRO_SILVER_COLUMN_TYPES,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    active_idx_factor_pro_daily_codes,
    approved_idx_factor_pro_daily_codes,
    idx_factor_pro_effective_start_trade_date,
    normalize_idx_factor_pro_trade_date,
)

FORMAL_LAKE_ROOT = Path("/Volumes/datasource/data_lake")
BOOTSTRAP_STAGING_ROOT = Path("/Volumes/datasource/data_lake_staging")
BOOTSTRAP_REPORT_ROOT = Path("/private/tmp/goldenshare-bootstrap/idx_factor_pro")
BOOTSTRAP_PRODUCT = "idx_factor_pro"
BOOTSTRAP_BATCH_DATE_COUNT = 20
BOOTSTRAP_DISK_SAFETY_MULTIPLIER = 2.0
BOOTSTRAP_RECENT_CHECK_DATE_COUNT = 20
_ESTIMATED_SOURCE_BYTES_PER_ROW = 1_024
_ESTIMATED_RAW_BYTES_PER_ROW = 1_024
_ESTIMATED_SILVER_BYTES_PER_ROW = 720


class IdxFactorProBootstrapPlanError(ValueError):
    """Raised when a frozen Bootstrap plan cannot be trusted."""


def hash_payload(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class IdxFactorProCodeBootstrapPlan:
    ts_code: str
    source_start_date: str
    effective_start_date: str
    end_date: str
    estimated_source_row_count: int
    selected_candidate_row_count: int
    max_request_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IdxFactorProDiskBudget:
    disk_free_bytes: int
    estimated_source_staging_bytes: int
    estimated_candidate_raw_bytes: int
    estimated_candidate_silver_bytes: int
    estimated_required_bytes: int
    safety_multiplier: float
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IdxFactorProBootstrapPlan:
    generated_at: str
    end_date: str
    lake_root: Path
    staging_root: Path
    report_root: Path
    trade_dates: tuple[str, ...]
    code_plans: tuple[IdxFactorProCodeBootstrapPlan, ...]
    schema_hash: str
    object_pool_hash: str
    contract_hash: str
    disk_budget: IdxFactorProDiskBudget
    plan_hash: str
    report_path: Path | None = None

    @property
    def candidate_trade_dates(self) -> tuple[str, ...]:
        return tuple(
            trade_date
            for trade_date in self.trade_dates
            if active_idx_factor_pro_daily_codes(trade_date)
        )

    @property
    def candidate_root(self) -> Path:
        return (
            self.staging_root
            / "bootstrap"
            / BOOTSTRAP_PRODUCT
            / f"plan_hash={self.plan_hash}"
        )

    @property
    def estimated_source_row_count(self) -> int:
        return sum(value.estimated_source_row_count for value in self.code_plans)

    @property
    def selected_candidate_row_count(self) -> int:
        return sum(value.selected_candidate_row_count for value in self.code_plans)

    @property
    def max_request_count(self) -> int:
        return sum(value.max_request_count for value in self.code_plans)

    def hash_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "product": BOOTSTRAP_PRODUCT,
            "end_date": self.end_date,
            "lake_root": str(self.lake_root),
            "staging_root": str(self.staging_root),
            "trade_dates": self.trade_dates,
            "code_plans": [value.to_dict() for value in self.code_plans],
            "schema_hash": self.schema_hash,
            "object_pool_hash": self.object_pool_hash,
            "contract_hash": self.contract_hash,
            "estimated_disk_bytes": {
                "source": self.disk_budget.estimated_source_staging_bytes,
                "raw": self.disk_budget.estimated_candidate_raw_bytes,
                "silver": self.disk_budget.estimated_candidate_silver_bytes,
                "required": self.disk_budget.estimated_required_bytes,
            },
            "batch_date_count": BOOTSTRAP_BATCH_DATE_COUNT,
            "disk_safety_multiplier": BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
            "recent_check_date_count": BOOTSTRAP_RECENT_CHECK_DATE_COUNT,
        }

    def to_dict(self) -> dict[str, object]:
        candidate_dates = self.candidate_trade_dates
        return {
            **self.hash_payload(),
            "generated_at": self.generated_at,
            "plan_hash": self.plan_hash,
            "report_path": str(self.report_path) if self.report_path else None,
            "candidate_root": str(self.candidate_root),
            "source_staging_root": str(self.candidate_root / "source"),
            "candidate_lake_root": str(self.candidate_root / "candidate_lake"),
            "candidate_run_staging_root": str(
                self.candidate_root / "candidate_run_staging"
            ),
            "candidate_date_count": len(candidate_dates),
            "candidate_start_date": candidate_dates[0] if candidate_dates else None,
            "candidate_end_date": candidate_dates[-1] if candidate_dates else None,
            "estimated_source_row_count": self.estimated_source_row_count,
            "selected_candidate_row_count": self.selected_candidate_row_count,
            "max_request_count": self.max_request_count,
            "disk_budget": self.disk_budget.to_dict(),
            "target_samples": {
                "raw": [
                    str(raw_idx_factor_pro_path(self.lake_root, value))
                    for value in (*candidate_dates[:2], *candidate_dates[-2:])
                ],
                "silver": [
                    str(silver_index_factor_pro_path(self.lake_root, value))
                    for value in (*candidate_dates[:2], *candidate_dates[-2:])
                ],
            },
            "writes": {
                "tushare_requests": 0,
                "source_staging": 0,
                "candidate_files": 0,
                "formal_lake": 0,
                "dynamic_partitions": 0,
                "dagster_events": 0,
            },
        }


def _normalize_trade_dates(values: Sequence[str], *, end_date: str) -> tuple[str, ...]:
    normalized_values = {
        normalize_idx_factor_pro_trade_date(value) for value in values
    }
    normalized = tuple(sorted(value for value in normalized_values if value <= end_date))
    if not normalized:
        raise IdxFactorProBootstrapPlanError(
            "trade calendar has no dates at or before the explicit end date"
        )
    return normalized


def load_sse_open_trade_dates(
    *,
    lake_root: Path,
    end_date: str,
    duckdb_resource: DuckDBResource,
) -> tuple[str, ...]:
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.is_file():
        raise IdxFactorProBootstrapPlanError(
            f"Silver trade calendar is missing: {calendar_path}"
        )
    with duckdb_resource.connect() as connection:
        rows = connection.execute(
            """
            SELECT CAST(trade_date AS DATE)::VARCHAR, count(*)
            FROM read_parquet(?)
            WHERE exchange = 'SSE'
              AND is_open = true
              AND CAST(trade_date AS DATE) <= CAST(? AS DATE)
            GROUP BY CAST(trade_date AS DATE)
            ORDER BY CAST(trade_date AS DATE)
            """,
            [str(calendar_path), end_date],
        ).fetchall()
    duplicates = tuple(str(row[0]) for row in rows if int(row[1]) != 1)
    if duplicates:
        raise IdxFactorProBootstrapPlanError(
            f"SSE calendar contains duplicate dates: {duplicates[:20]!r}"
        )
    return _normalize_trade_dates(tuple(str(row[0]) for row in rows), end_date=end_date)


def _count_dates(values: Sequence[str], start_date: str, end_date: str) -> int:
    return sum(start_date <= value <= end_date for value in values)


def _build_code_plans(
    trade_dates: Sequence[str], *, end_date: str
) -> tuple[IdxFactorProCodeBootstrapPlan, ...]:
    plans: list[IdxFactorProCodeBootstrapPlan] = []
    for code in approved_idx_factor_pro_daily_codes():
        source_start = IDX_FACTOR_PRO_FIRST_AVAILABLE_TRADE_DATES[code]
        effective_start = idx_factor_pro_effective_start_trade_date(code)
        source_rows = _count_dates(trade_dates, source_start, end_date)
        selected_rows = _count_dates(trade_dates, effective_start, end_date)
        if source_rows <= 0 or selected_rows <= 0:
            raise IdxFactorProBootstrapPlanError(
                "explicit end date does not cover the frozen source/effective start: "
                f"code={code}, source_start={source_start}, "
                f"effective_start={effective_start}, end={end_date}"
            )
        plans.append(
            IdxFactorProCodeBootstrapPlan(
                ts_code=code,
                source_start_date=source_start,
                effective_start_date=effective_start,
                end_date=end_date,
                estimated_source_row_count=source_rows,
                selected_candidate_row_count=selected_rows,
                # An exact multiple needs one final empty page to prove exhaustion.
                max_request_count=floor(source_rows / IDX_FACTOR_PRO_PAGE_LIMIT) + 1,
            )
        )
    return tuple(plans)


def _disk_budget(
    *,
    staging_root: Path,
    source_rows: int,
    candidate_rows: int,
    disk_free_bytes: int | None,
) -> IdxFactorProDiskBudget:
    free_bytes = (
        int(disk_free_bytes)
        if disk_free_bytes is not None
        else int(shutil.disk_usage(staging_root).free)
    )
    source_bytes = source_rows * _ESTIMATED_SOURCE_BYTES_PER_ROW
    raw_bytes = candidate_rows * _ESTIMATED_RAW_BYTES_PER_ROW
    silver_bytes = candidate_rows * _ESTIMATED_SILVER_BYTES_PER_ROW
    required = int(
        (source_bytes + raw_bytes + silver_bytes)
        * BOOTSTRAP_DISK_SAFETY_MULTIPLIER
    )
    return IdxFactorProDiskBudget(
        disk_free_bytes=free_bytes,
        estimated_source_staging_bytes=source_bytes,
        estimated_candidate_raw_bytes=raw_bytes,
        estimated_candidate_silver_bytes=silver_bytes,
        estimated_required_bytes=required,
        safety_multiplier=BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
        passed=free_bytes >= required,
    )


def build_idx_factor_pro_bootstrap_plan(
    *,
    end_date: str,
    lake_root: Path = FORMAL_LAKE_ROOT,
    staging_root: Path = BOOTSTRAP_STAGING_ROOT,
    report_root: Path = BOOTSTRAP_REPORT_ROOT,
    duckdb_resource: DuckDBResource | None = None,
    trade_dates: Sequence[str] | None = None,
    disk_free_bytes: int | None = None,
    write_report: bool = True,
) -> IdxFactorProBootstrapPlan:
    """Freeze a request-free plan; this function never calls Tushare."""

    normalized_end = normalize_idx_factor_pro_trade_date(end_date)
    if date.fromisoformat(normalized_end) > datetime.now(timezone.utc).date():
        raise IdxFactorProBootstrapPlanError("Bootstrap end date is in the future")
    normalized_dates = (
        _normalize_trade_dates(trade_dates, end_date=normalized_end)
        if trade_dates is not None
        else load_sse_open_trade_dates(
            lake_root=lake_root,
            end_date=normalized_end,
            duckdb_resource=duckdb_resource or DuckDBResource(),
        )
    )
    code_plans = _build_code_plans(normalized_dates, end_date=normalized_end)
    schema_hash = hash_payload(
        {
            "columns": IDX_FACTOR_PRO_SOURCE_COLUMNS,
            "raw_types": dict(IDX_FACTOR_PRO_RAW_COLUMN_TYPES),
            "silver_types": dict(IDX_FACTOR_PRO_SILVER_COLUMN_TYPES),
        }
    )
    object_pool_hash = hash_payload(
        {
            "approved_codes": approved_idx_factor_pro_daily_codes(),
            "source_first_dates": dict(IDX_FACTOR_PRO_FIRST_AVAILABLE_TRADE_DATES),
            "effective_first_dates": {
                code: idx_factor_pro_effective_start_trade_date(code)
                for code in approved_idx_factor_pro_daily_codes()
            },
        }
    )
    contract_hash = hash_payload(
        {
            "api_name": "idx_factor_pro",
            "page_limit": IDX_FACTOR_PRO_PAGE_LIMIT,
            "schema_hash": schema_hash,
            "object_pool_hash": object_pool_hash,
        }
    )
    source_rows = sum(value.estimated_source_row_count for value in code_plans)
    candidate_rows = sum(value.selected_candidate_row_count for value in code_plans)
    budget = _disk_budget(
        staging_root=staging_root,
        source_rows=source_rows,
        candidate_rows=candidate_rows,
        disk_free_bytes=disk_free_bytes,
    )
    draft = IdxFactorProBootstrapPlan(
        generated_at=datetime.now(timezone.utc).isoformat(),
        end_date=normalized_end,
        lake_root=Path(lake_root),
        staging_root=Path(staging_root),
        report_root=Path(report_root),
        trade_dates=normalized_dates,
        code_plans=code_plans,
        schema_hash=schema_hash,
        object_pool_hash=object_pool_hash,
        contract_hash=contract_hash,
        disk_budget=budget,
        plan_hash="",
    )
    plan_hash = hash_payload(draft.hash_payload())
    report_path = Path(report_root) / f"idx_factor_pro_bootstrap_plan_{plan_hash}.json"
    plan = IdxFactorProBootstrapPlan(
        **{
            **asdict(draft),
            "lake_root": Path(lake_root),
            "staging_root": Path(staging_root),
            "report_root": Path(report_root),
            "code_plans": code_plans,
            "disk_budget": budget,
            "plan_hash": plan_hash,
            "report_path": report_path,
        }
    )
    if write_report:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = plan.to_dict()
        existing = _load_json_if_exists(report_path)
        if existing is not None:
            return load_idx_factor_pro_bootstrap_plan(
                report_path,
                expected_plan_hash=plan_hash,
            )
        else:
            _atomic_write_json(report_path, payload)
    return plan


def _load_json_if_exists(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IdxFactorProBootstrapPlanError(f"plan report is unreadable: {path}") from error
    if not isinstance(payload, Mapping):
        raise IdxFactorProBootstrapPlanError("plan report must be a JSON object")
    return payload


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


def load_idx_factor_pro_bootstrap_plan(
    report_path: Path, *, expected_plan_hash: str
) -> IdxFactorProBootstrapPlan:
    payload = _load_json_if_exists(report_path)
    if payload is None:
        raise IdxFactorProBootstrapPlanError(f"plan report does not exist: {report_path}")
    if str(payload.get("plan_hash")) != expected_plan_hash:
        raise IdxFactorProBootstrapPlanError("expected plan hash does not match report")
    code_plans_value = payload.get("code_plans")
    disk_value = payload.get("disk_budget")
    trade_dates_value = payload.get("trade_dates")
    if not isinstance(code_plans_value, list) or not isinstance(disk_value, Mapping):
        raise IdxFactorProBootstrapPlanError("plan report is structurally incomplete")
    if not isinstance(trade_dates_value, list):
        raise IdxFactorProBootstrapPlanError("plan report has no trade_dates list")
    plan = IdxFactorProBootstrapPlan(
        generated_at=str(payload["generated_at"]),
        end_date=str(payload["end_date"]),
        lake_root=Path(str(payload["lake_root"])),
        staging_root=Path(str(payload["staging_root"])),
        report_root=Path(str(report_path).rsplit("/", 1)[0]),
        trade_dates=tuple(str(value) for value in trade_dates_value),
        code_plans=tuple(
            IdxFactorProCodeBootstrapPlan(**dict(value))
            for value in code_plans_value
            if isinstance(value, Mapping)
        ),
        schema_hash=str(payload["schema_hash"]),
        object_pool_hash=str(payload["object_pool_hash"]),
        contract_hash=str(payload["contract_hash"]),
        disk_budget=IdxFactorProDiskBudget(**dict(disk_value)),
        plan_hash=str(payload["plan_hash"]),
        report_path=Path(report_path),
    )
    if hash_payload(plan.hash_payload()) != expected_plan_hash:
        raise IdxFactorProBootstrapPlanError("frozen plan payload has drifted")
    return plan


__all__ = [
    "BOOTSTRAP_BATCH_DATE_COUNT",
    "BOOTSTRAP_RECENT_CHECK_DATE_COUNT",
    "IdxFactorProBootstrapPlan",
    "IdxFactorProBootstrapPlanError",
    "IdxFactorProCodeBootstrapPlan",
    "build_idx_factor_pro_bootstrap_plan",
    "file_sha256",
    "hash_payload",
    "load_idx_factor_pro_bootstrap_plan",
]
