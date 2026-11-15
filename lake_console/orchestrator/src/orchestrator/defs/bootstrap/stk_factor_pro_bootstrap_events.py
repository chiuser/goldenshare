"""Register accepted bootstrap facts; never open or repair business data files."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from itertools import groupby
from pathlib import Path
from time import monotonic

import dagster as dg
import sqlalchemy as sa
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecord,
    AssetCheckExecutionRecordStatus,
)
from dagster._core.storage.event_log.schema import AssetCheckExecutionsTable

from orchestrator.audits.stk_factor_pro_coverage import (
    STK_FACTOR_PRO_HISTORICAL_COVERAGE_RULE_VERSION,
)
from orchestrator.defs.asset_guards.stk_factor_pro_readiness import (
    require_stk_factor_pro_no_other_active_runs,
)
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_publication import (
    read_stk_factor_pro_bootstrap_publication,
)
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    operation_path,
    read_json,
    write_json,
)
from orchestrator.defs.paths import stk_factor_pro_bootstrap_record_path
from orchestrator.defs.run_contracts import stk_factor_pro as C

_LAYERS = {
    "raw": (C.STK_FACTOR_PRO_RAW_ASSET_KEY, C.STK_FACTOR_PRO_RAW_CHECK_NAME),
    "silver": (C.STK_FACTOR_PRO_SILVER_ASSET_KEY, C.STK_FACTOR_PRO_SILVER_CHECK_NAME),
}


@dataclass(frozen=True)
class _EventPlan:
    record_version: int
    operation_id: str
    approval_digest: str
    historical_coverage_ref: tuple[str, str]
    code_revision: str
    contract_content_digest: str
    processing_version: str
    coverage_rule_version: str
    instance_identity: tuple[str, str]
    trade_dates: tuple[date, ...]
    missing_events: tuple[tuple[date, str, str], ...]
    existing_count: int
    conflicts: tuple[tuple[date, str, str], ...]
    max_new_events: int


def _instance_identity(instance):
    storage = type(instance.event_log_storage)
    return str(instance.root_directory), f"{storage.__module__}.{storage.__name__}"


def _approval(staging_root, operation_id, known_records):
    path = stk_factor_pro_bootstrap_record_path(
        staging_root, operation_id, "approval.json"
    )
    approval = read_json(
        path, C.StkFactorProBootstrapApproval, known_records=known_records
    )
    if approval is None or approval.operation_id != operation_id:
        raise ValueError("历史事件缺原bootstrap批准")
    if approval.contract_content_digest != C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST:
        raise ValueError("历史事件原批准与当前字段合同不符")
    return approval, known_records[path][1]


def _coverage(staging_root, approval, approval_digest, reference, trade_dates):
    relative, digest = reference
    path = operation_path(staging_root, approval, relative)
    payload = path.read_bytes()
    if sha256(payload).hexdigest() != digest:
        raise ValueError("历史覆盖验收摘要不符")
    summary = json.loads(payload)
    if (
        summary["operation_id"] != approval.operation_id
        or summary["approval_digest"] != approval_digest
        or summary["rule_version"] != STK_FACTOR_PRO_HISTORICAL_COVERAGE_RULE_VERSION
        or summary["passed"] is not True
        or summary["missing_count"] != 0
        or summary["unknown_dates"] != 0
        or summary["incomplete_dates"] != 0
    ):
        raise ValueError("历史覆盖验收尚未通过或不属于本operation")
    daily_relative = (Path(relative).parent / "daily.csv").as_posix()
    daily = operation_path(staging_root, approval, daily_relative).read_bytes()
    if sha256(daily).hexdigest() != summary["reports"]["daily.csv"]:
        raise ValueError("历史覆盖逐日统计摘要不符")
    rows = tuple(csv.DictReader(io.StringIO(daily.decode())))
    accepted = {
        date.fromisoformat(row["trade_date"])
        for row in rows
        if row["status"] == "complete"
    }
    days = tuple(sorted(set(trade_dates)))
    if (
        not days
        or len(accepted) != summary["date_count"]
        or len(rows) != len(accepted)
        or not set(days).issubset(accepted)
        or days[0] < approval.start_trade_date
        or days[-1] > approval.end_trade_date
    ):
        raise ValueError("历史事件必须明确选择已验收范围内的非空日期")
    return days


def _facts(lake_root, staging_root, approval, approval_digest, days, known_records):
    facts = {}
    for day in days:
        raw_sha = None
        for layer in _LAYERS:
            _, complete = read_stk_factor_pro_bootstrap_publication(
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                trade_date=day,
                layer=layer,
                known_records=known_records,
            )
            if complete is None or not complete.audit.path.is_file():
                raise ValueError(f"历史事件缺原发布记录或目标文件：{day}/{layer}")
            if layer == "raw":
                raw_sha = complete.actual_file_sha256
            relative = f"publication/{day}/{layer}/complete.json"
            source = {
                "goldenshare/bootstrap_operation_id": approval.operation_id,
                "goldenshare/bootstrap_approval_digest": approval_digest,
                "goldenshare/bootstrap_publication_ref": dg.MetadataValue.json(
                    {
                        "relative_path": relative,
                        "file_sha256": known_records[
                            operation_path(staging_root, approval, relative)
                        ][1],
                    }
                ),
            }
            facts[day, layer] = C.build_stk_factor_pro_publication_metadata(
                complete.audit, raw_file_sha256=raw_sha, source_metadata=source
            )
    return facts


def _materials(instance, keys):
    result = {}
    for layer, (asset, _) in _LAYERS.items():
        partitions = {str(day) for day, key_layer in keys if key_layer == layer}
        if not partitions:
            continue
        ids = instance.event_log_storage.get_latest_storage_id_by_partition(
            dg.AssetKey(asset),
            dg.DagsterEventType.ASSET_MATERIALIZATION,
            partitions=partitions,
        )
        if ids:
            records = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(asset), storage_ids=list(ids.values())
                ),
                limit=len(ids),
            ).records
            result.update(
                {(date.fromisoformat(r.partition_key), layer): r for r in records}
            )
    return result


def _checks(instance, days):
    if not days:
        return {}
    table = AssetCheckExecutionsTable
    latest = (
        sa.select(sa.func.max(table.c.id).label("id"))
        .where(
            table.c.partition.in_([str(day) for day in days]),
            sa.or_(
                *(
                    sa.and_(
                        table.c.asset_key == dg.AssetKey(asset).to_string(),
                        table.c.check_name == name,
                    )
                    for asset, name in _LAYERS.values()
                )
            ),
        )
        .group_by(table.c.asset_key, table.c.check_name, table.c.partition)
        .subquery()
    )
    query = sa.select(table).select_from(table.join(latest, table.c.id == latest.c.id))
    with instance.event_log_storage.index_connection() as conn:
        rows = conn.execute(query).mappings().all()
    layers = {asset: layer for layer, (asset, _) in _LAYERS.items()}
    result = {}
    for row in rows:
        asset = dg.AssetKey.from_db_string(row["asset_key"])
        key = dg.AssetCheckKey(asset, row["check_name"])
        result[date.fromisoformat(row["partition"]), layers[asset.to_user_string()]] = (
            AssetCheckExecutionRecord.from_db_row(row, key=key)
        )
    return result


def _same_metadata(saved, expected):
    # An existing valid producer need not carry bootstrap tool provenance tags.
    return all(
        getattr(saved.get(key), "value", saved.get(key))
        == getattr(value, "value", value)
        for key, value in expected.items()
        if not key.startswith("goldenshare/bootstrap_") or key in saved
    )


def _material_valid(material, expected):
    return _same_metadata(material.asset_materialization.metadata, expected)


def _check_valid(check, material, expected, name):
    evaluation = check.evaluation
    if check.status != AssetCheckExecutionRecordStatus.SUCCEEDED or evaluation is None:
        return False
    target = evaluation.target_materialization_data
    return (
        evaluation.passed
        and evaluation.blocking
        and evaluation.check_name == name
        and evaluation.partition == material.partition_key
        and evaluation.asset_key == material.asset_key
        and target is not None
        and (target.storage_id, target.run_id, target.timestamp)
        == (material.storage_id, material.event_log_entry.run_id, material.timestamp)
        and _same_metadata(evaluation.metadata, expected)
    )


def _inspect(facts, materials, checks):
    missing, conflicts = [], []
    for (day, layer), metadata in facts.items():
        material, check = materials.get((day, layer)), checks.get((day, layer))
        if material is None:
            if check is not None:
                conflicts.append((day, layer, "check存在但缺物化"))
            else:
                missing.extend(((day, layer, "materialization"), (day, layer, "check")))
        elif not _material_valid(material, metadata):
            conflicts.append((day, layer, "最新物化与原发布事实不符"))
        elif check is None:
            missing.append((day, layer, "check"))
        elif not _check_valid(check, material, metadata, _LAYERS[layer][1]):
            conflicts.append((day, layer, "最新check失败、等待或绑定不符"))
    return tuple(missing), tuple(conflicts)


def _months(days):
    for _, group in groupby(days, key=lambda day: (day.year, day.month)):
        yield tuple(group)


def plan_stk_factor_pro_bootstrap_events(
    *,
    instance,
    lake_root: Path,
    staging_root: Path,
    operation_id: str,
    historical_coverage_ref: tuple[str, str],
    trade_dates: tuple[date, ...],
    code_revision: str,
):
    """Read accepted records/native events and save one minimal approval plan."""
    known = {}
    approval, digest = _approval(staging_root, operation_id, known)
    days = _coverage(
        staging_root, approval, digest, historical_coverage_ref, trade_dates
    )
    missing, conflicts, existing = [], [], 0
    for batch in _months(days):
        facts = _facts(lake_root, staging_root, approval, digest, batch, dict(known))
        materials, checks = _materials(instance, facts), _checks(instance, batch)
        pending, problems = _inspect(facts, materials, checks)
        existing += len(materials) + len(checks)
        missing.extend(pending)
        conflicts.extend(problems)
    plan = _EventPlan(
        1,
        operation_id,
        digest,
        historical_coverage_ref,
        code_revision,
        C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST,
        C.STK_FACTOR_PRO_PROCESSING_VERSION,
        STK_FACTOR_PRO_HISTORICAL_COVERAGE_RULE_VERSION,
        _instance_identity(instance),
        days,
        tuple(missing),
        existing,
        tuple(conflicts),
        len(missing),
    )
    payload = (
        json.dumps(
            C.stk_factor_pro_record_to_dict(plan),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()
    plan_digest = sha256(payload).hexdigest()
    path = operation_path(staging_root, approval, f"events/plans/{plan_digest}.json")
    write_json(path, plan, known_records=known)
    return plan, plan_digest


def apply_stk_factor_pro_bootstrap_events(
    *,
    instance,
    lake_root: Path,
    staging_root: Path,
    operation_id: str,
    expected_plan_digest: str,
    trade_dates: tuple[date, ...],
):
    """Fill approved missing events, checking each batch before moving on."""
    started, known = monotonic(), {}
    approval, digest = _approval(staging_root, operation_id, known)
    # Existing path contract validates the digest as a single filename component.
    if len(expected_plan_digest) != 64 or any(
        c not in "0123456789abcdef" for c in expected_plan_digest
    ):
        raise ValueError("事件计划SHA必须为64位小写十六进制")
    path = operation_path(
        staging_root, approval, f"events/plans/{expected_plan_digest}.json"
    )
    plan = read_json(path, _EventPlan, known_records=known)
    if plan is None or known[path][1] != expected_plan_digest:
        raise ValueError("事件批准计划不存在或SHA不符")
    if (
        plan.record_version != 1
        or plan.operation_id != operation_id
        or plan.approval_digest != digest
        or plan.conflicts
        or plan.contract_content_digest != C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST
        or plan.processing_version != C.STK_FACTOR_PRO_PROCESSING_VERSION
        or plan.coverage_rule_version != STK_FACTOR_PRO_HISTORICAL_COVERAGE_RULE_VERSION
        or plan.instance_identity != _instance_identity(instance)
    ):
        raise ValueError("事件批准计划与当前operation/合同/instance不符或存在冲突")
    days = _coverage(
        staging_root, approval, digest, plan.historical_coverage_ref, trade_dates
    )
    if not set(days).issubset(plan.trade_dates):
        raise ValueError("执行日期超出批准计划")
    require_stk_factor_pro_no_other_active_runs(instance)
    allowed = set(plan.missing_events)
    new_materializations = new_checks = 0
    for batch in _months(days):
        facts = _facts(lake_root, staging_root, approval, digest, batch, dict(known))
        materials, checks = _materials(instance, facts), _checks(instance, batch)
        pending, conflicts = _inspect(facts, materials, checks)
        if conflicts or not set(pending).issubset(allowed):
            raise ValueError(f"历史事件出现冲突或计划外缺项：{conflicts or pending}")
        new_keys = {
            (day, layer) for day, layer, kind in pending if kind == "materialization"
        }
        for key in facts:
            if key in new_keys:
                day, layer = key
                instance.report_runless_asset_event(
                    dg.AssetMaterialization(
                        asset_key=dg.AssetKey(_LAYERS[layer][0]),
                        partition=str(day),
                        metadata=facts[key],
                    )
                )
                new_materializations += 1
        if new_keys:
            saved = _materials(instance, new_keys)
            if set(saved) != new_keys or any(
                not _material_valid(m, facts[k]) for k, m in saved.items()
            ):
                raise ValueError("新物化未保存或与原发布事实不符")
            materials.update(saved)
        check_keys = {(day, layer) for day, layer, kind in pending if kind == "check"}
        for key in facts:
            if key in check_keys:
                day, layer = key
                material = materials[key]
                instance.report_runless_asset_event(
                    AssetCheckEvaluation(
                        asset_key=dg.AssetKey(_LAYERS[layer][0]),
                        check_name=_LAYERS[layer][1],
                        partition=str(day),
                        passed=True,
                        blocking=True,
                        severity=dg.AssetCheckSeverity.ERROR,
                        metadata=facts[key],
                        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                            storage_id=material.storage_id,
                            run_id=material.event_log_entry.run_id,
                            timestamp=material.timestamp,
                        ),
                    )
                )
                new_checks += 1
        if check_keys:
            checks = _checks(instance, batch)
        pending, conflicts = _inspect(facts, materials, checks)
        if pending or conflicts:
            raise ValueError(f"历史事件写后读回不完整：{pending or conflicts}")
    return {
        "operation_id": operation_id,
        "plan_digest": expected_plan_digest,
        "date_count": len(days),
        "confirmed_events": 4 * len(days),
        "new_materializations": new_materializations,
        "new_checks": new_checks,
        "missing_count": 0,
        "conflict_count": 0,
        "elapsed_seconds": monotonic() - started,
    }
