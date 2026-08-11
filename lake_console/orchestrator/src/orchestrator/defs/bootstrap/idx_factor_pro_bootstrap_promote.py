"""Manifest-only formal promotion for verified ``idx_factor_pro`` candidates."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from orchestrator.defs.bootstrap.idx_factor_pro_bootstrap_plan import (
    IdxFactorProBootstrapPlan,
    file_sha256,
    load_idx_factor_pro_bootstrap_plan,
)
from orchestrator.defs.duckdb_sql import read_parquet
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
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    active_idx_factor_pro_daily_codes,
)


class IdxFactorProBootstrapPromoteError(RuntimeError):
    """Raised before a candidate can overwrite or contaminate formal Lake."""


@dataclass(frozen=True, slots=True)
class PromotionFileResult:
    layer: str
    trade_date: str
    candidate_path: str
    formal_path: str
    sha256: str
    row_count: int
    action: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _load_json(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IdxFactorProBootstrapPromoteError(f"{label} is unreadable: {path}") from error
    if not isinstance(payload, Mapping):
        raise IdxFactorProBootstrapPromoteError(f"{label} must be a JSON object")
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


def _candidate_entries(
    *,
    plan: IdxFactorProBootstrapPlan,
    candidate_report_path: Path,
) -> tuple[Mapping[str, Any], ...]:
    report = _load_json(candidate_report_path, label="candidate report")
    if report.get("plan_hash") != plan.plan_hash or report.get("should_stop") is not False:
        raise IdxFactorProBootstrapPromoteError(
            "candidate report is not a green report for the frozen plan"
        )
    files = report.get("files")
    if not isinstance(files, list):
        raise IdxFactorProBootstrapPromoteError("candidate report has no file manifest")
    entries = tuple(value for value in files if isinstance(value, Mapping))
    if len(entries) != len(plan.candidate_trade_dates) * 2:
        raise IdxFactorProBootstrapPromoteError(
            "candidate manifest file count does not match frozen dates"
        )
    expected_keys = {
        (layer, trade_date)
        for layer in ("raw", "silver")
        for trade_date in plan.candidate_trade_dates
    }
    observed_keys = {
        (str(value.get("layer")), str(value.get("trade_date"))) for value in entries
    }
    if observed_keys != expected_keys:
        raise IdxFactorProBootstrapPromoteError(
            "candidate manifest layer/date scope differs from the frozen plan"
        )
    return entries


def _formal_path(plan: IdxFactorProBootstrapPlan, layer: str, trade_date: str) -> Path:
    if layer == "raw":
        return raw_idx_factor_pro_path(plan.lake_root, trade_date)
    if layer == "silver":
        return silver_index_factor_pro_path(plan.lake_root, trade_date)
    raise IdxFactorProBootstrapPromoteError(f"unsupported candidate layer: {layer}")


def _promote_one(
    *,
    plan: IdxFactorProBootstrapPlan,
    entry: Mapping[str, Any],
) -> PromotionFileResult:
    layer = str(entry["layer"])
    trade_date = str(entry["trade_date"])
    candidate = Path(str(entry["path"]))
    formal = _formal_path(plan, layer, trade_date)
    expected_hash = str(entry["sha256"])
    row_count = int(entry["row_count"])
    if formal.exists():
        if file_sha256(formal) != expected_hash:
            raise IdxFactorProBootstrapPromoteError(
                f"formal target conflicts with candidate manifest: {formal}"
            )
        return PromotionFileResult(
            layer, trade_date, str(candidate), str(formal), expected_hash,
            row_count, "reused_identical_formal",
        )
    if not candidate.is_file() or file_sha256(candidate) != expected_hash:
        raise IdxFactorProBootstrapPromoteError(
            f"candidate is missing or changed: {candidate}"
        )
    formal.parent.mkdir(parents=True, exist_ok=True)
    if candidate.parent.stat().st_dev != formal.parent.stat().st_dev:
        raise IdxFactorProBootstrapPromoteError(
            "candidate and formal target must share one filesystem for os.replace"
        )
    os.replace(candidate, formal)
    if file_sha256(formal) != expected_hash:
        raise IdxFactorProBootstrapPromoteError(
            f"formal readback hash mismatch after promotion: {formal}"
        )
    return PromotionFileResult(
        layer, trade_date, str(candidate), str(formal), expected_hash,
        row_count, "promoted",
    )


def _post_audit(
    *,
    plan: IdxFactorProBootstrapPlan,
    resource: DuckDBResource,
    entries: tuple[Mapping[str, Any], ...],
) -> None:
    by_key = {
        (str(value["layer"]), str(value["trade_date"])): value for value in entries
    }
    with resource.connect() as connection:
        for trade_date in plan.candidate_trade_dates:
            expected_codes = active_idx_factor_pro_daily_codes(trade_date)
            raw_path = raw_idx_factor_pro_path(plan.lake_root, trade_date)
            silver_path = silver_index_factor_pro_path(plan.lake_root, trade_date)
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
                silver_relation_sql=read_parquet(silver_path, hive_partitioning=False),
            )
            if raw_audit.errors or silver_audit.errors or parity.errors:
                raise IdxFactorProBootstrapPromoteError(
                    "formal physical audit failed: "
                    f"date={trade_date}, raw={raw_audit.errors!r}, "
                    f"silver={silver_audit.errors!r}, parity={parity.errors!r}"
                )
            if raw_audit.row_count != int(by_key[("raw", trade_date)]["row_count"]):
                raise IdxFactorProBootstrapPromoteError(
                    f"formal Raw row count differs from manifest: {trade_date}"
                )
            if silver_audit.row_count != int(
                by_key[("silver", trade_date)]["row_count"]
            ):
                raise IdxFactorProBootstrapPromoteError(
                    f"formal Silver row count differs from manifest: {trade_date}"
                )


def promote_idx_factor_pro_candidates(
    *,
    plan_report_path: Path,
    candidate_report_path: Path,
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource | None = None,
    apply: bool = False,
) -> Path:
    """Promote Raw first, then Silver, with manifest and physical readback gates."""

    if not apply:
        raise IdxFactorProBootstrapPromoteError("formal promotion requires apply=True")
    plan = load_idx_factor_pro_bootstrap_plan(
        plan_report_path, expected_plan_hash=expected_plan_hash
    )
    entries = _candidate_entries(
        plan=plan, candidate_report_path=candidate_report_path
    )
    results: list[PromotionFileResult] = []
    for layer in ("raw", "silver"):
        for entry in sorted(
            (value for value in entries if value.get("layer") == layer),
            key=lambda value: str(value.get("trade_date")),
        ):
            results.append(_promote_one(plan=plan, entry=entry))
    _post_audit(
        plan=plan,
        resource=duckdb_resource or DuckDBResource(),
        entries=entries,
    )
    report_path = (
        plan.report_root / f"idx_factor_pro_promote_{plan.plan_hash}.json"
    )
    _atomic_write_json(
        report_path,
        {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "plan_hash": plan.plan_hash,
            "candidate_report_path": str(candidate_report_path),
            "candidate_report_sha256": file_sha256(candidate_report_path),
            "formal_lake_root": str(plan.lake_root),
            "results": [value.to_dict() for value in results],
            "promoted_count": sum(value.action == "promoted" for value in results),
            "reused_count": sum(
                value.action == "reused_identical_formal" for value in results
            ),
            "should_stop": False,
            "writes": {
                "formal_lake": sum(value.action == "promoted" for value in results),
                "dynamic_partitions": 0,
                "dagster_events": 0,
            },
        },
    )
    return report_path


__all__ = [
    "IdxFactorProBootstrapPromoteError",
    "promote_idx_factor_pro_candidates",
]
