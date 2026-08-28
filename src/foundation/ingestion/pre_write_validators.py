from __future__ import annotations

from datetime import date
from decimal import Decimal
import math
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.sw_industry_contracts import (
    SW2021_CLASSIFICATION_VERSION,
    SW2021_INDEX_CODE_ALIASES_V1,
)
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.etf_basic_snapshot import (
    EtfBasicSnapshotValidationError,
    validate_etf_basic_snapshot,
)
from src.foundation.models.core_serving.sw_industry_classification import (
    SwIndustryClassification,
)


class PreWriteValidationError(ValueError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


PreWriteValidator = Callable[
    [Session, list[dict[str, Any]], DatasetDefinition, PlanUnitSnapshot | None],
    None,
]


def _validate_etf_basic_snapshot(
    session: Session,
    rows: list[dict[str, Any]],
    definition: DatasetDefinition,
    plan_unit: PlanUnitSnapshot | None,
) -> None:
    del session
    del definition
    del plan_unit
    try:
        validate_etf_basic_snapshot(
            rows,
            source_row_count=len(rows),
            normalized_row_count=len(rows),
        )
    except EtfBasicSnapshotValidationError as exc:
        raise PreWriteValidationError(str(exc), details=exc.details) from exc


def _validate_sw2021_classification_snapshot(
    session: Session,
    rows: list[dict[str, Any]],
    definition: DatasetDefinition,
    plan_unit: PlanUnitSnapshot | None,
) -> None:
    del session
    del definition
    del plan_unit
    by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    by_business_code: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        src = str(row.get("src") or "")
        industry_code = str(row.get("industry_code") or "")
        index_code = str(row.get("index_code") or "")
        identity = (src, industry_code)
        business_identity = (src, index_code)
        if identity in by_identity or business_identity in by_business_code:
            raise PreWriteValidationError("申万分类存在重复业务身份")
        by_identity[identity] = row
        by_business_code[business_identity] = row
        if src != SW2021_CLASSIFICATION_VERSION:
            raise PreWriteValidationError("申万分类快照只能包含 SW2021")
        source_index_code = str(row.get("source_index_code") or "")
        if source_index_code in SW2021_INDEX_CODE_ALIASES_V1:
            if industry_code != "230501" or index_code != "850412.SI":
                raise PreWriteValidationError(
                    "850401.SI 分类映射与 230501/850412.SI 契约不一致"
                )

    for row in rows:
        src = str(row["src"])
        level = str(row["level"])
        parent_code = row.get("parent_code")
        if level == "L1":
            if parent_code is not None:
                raise PreWriteValidationError("L1 分类不得包含业务父级")
            continue
        expected_parent_level = (
            "L1" if level == "L2" else "L2" if level == "L3" else None
        )
        if expected_parent_level is None or parent_code in (None, ""):
            raise PreWriteValidationError("申万分类层级或父级非法")
        parent = by_identity.get((src, str(parent_code)))
        if parent is None or parent.get("level") != expected_parent_level:
            raise PreWriteValidationError(
                "申万分类父子层级不闭合",
                details={
                    "industry_code": row.get("industry_code"),
                    "parent_code": parent_code,
                },
            )


def _validate_sw2021_member_snapshot(
    session: Session,
    rows: list[dict[str, Any]],
    definition: DatasetDefinition,
    plan_unit: PlanUnitSnapshot | None,
) -> None:
    del definition
    del plan_unit
    versions = {str(row.get("classification_version") or "") for row in rows}
    if versions != {SW2021_CLASSIFICATION_VERSION}:
        raise PreWriteValidationError("申万成员全集只能引用 SW2021 分类")
    classification_rows = list(
        session.scalars(
            select(SwIndustryClassification).where(
                SwIndustryClassification.src == SW2021_CLASSIFICATION_VERSION
            )
        )
    )
    if not classification_rows:
        raise PreWriteValidationError("SW2021 分类尚未发布，不能发布成员全集")
    by_index_code = {item.index_code: item for item in classification_rows}
    by_industry_code = {item.industry_code: item for item in classification_rows}
    for row in rows:
        chain = (
            ("L1", str(row.get("l1_code") or ""), str(row.get("l1_name") or "")),
            ("L2", str(row.get("l2_code") or ""), str(row.get("l2_name") or "")),
            ("L3", str(row.get("l3_code") or ""), str(row.get("l3_name") or "")),
        )
        nodes = []
        for expected_level, code, name in chain:
            node = by_index_code.get(code)
            if (
                node is None
                or node.level != expected_level
                or node.industry_name != name
            ):
                raise PreWriteValidationError(
                    "申万成员的分类代码、层级或名称不匹配",
                    details={
                        "expected_level": expected_level,
                        "code": code,
                        "name": name,
                    },
                )
            nodes.append(node)
        l1_node, l2_node, l3_node = nodes
        if by_industry_code.get(l2_node.parent_code) is not l1_node:
            raise PreWriteValidationError("申万成员 L1/L2 父子关系不匹配")
        if by_industry_code.get(l3_node.parent_code) is not l2_node:
            raise PreWriteValidationError("申万成员 L2/L3 父子关系不匹配")
        in_date = row.get("in_date")
        out_date = row.get("out_date")
        if not isinstance(in_date, date) or (
            out_date is not None
            and (not isinstance(out_date, date) or out_date < in_date)
        ):
            raise PreWriteValidationError("申万成员纳入/剔除日期非法")


def _to_finite_number(value: Any, *, field_name: str) -> float:
    if isinstance(value, Decimal):
        result = float(value)
    else:
        result = float(value)
    if not math.isfinite(result):
        raise PreWriteValidationError(f"申万日行情字段 {field_name} 必须是有限数值")
    return result


def _validate_sw2021_daily_scope(
    session: Session,
    rows: list[dict[str, Any]],
    definition: DatasetDefinition,
    plan_unit: PlanUnitSnapshot | None,
) -> None:
    del session
    del definition
    for row in rows:
        if row.get("classification_version") != SW2021_CLASSIFICATION_VERSION:
            raise PreWriteValidationError("申万日行情只能写入 SW2021 分类版本")
        for field_name in ("open", "low", "high", "close"):
            _to_finite_number(row.get(field_name), field_name=field_name)
        for field_name in ("vol", "amount", "float_mv", "total_mv"):
            value = row.get(field_name)
            if (
                value is not None
                and _to_finite_number(value, field_name=field_name) < 0
            ):
                raise PreWriteValidationError(f"申万日行情字段 {field_name} 不得为负")
        if plan_unit is not None and row.get("trade_date") != plan_unit.trade_date:
            raise PreWriteValidationError("申万日行情日期与执行单元不一致")


PRE_WRITE_VALIDATORS: dict[str, PreWriteValidator] = {
    "etf_basic_snapshot": _validate_etf_basic_snapshot,
    "sw2021_classification_snapshot": _validate_sw2021_classification_snapshot,
    "sw2021_member_snapshot": _validate_sw2021_member_snapshot,
    "sw2021_daily_scope": _validate_sw2021_daily_scope,
}


def get_pre_write_validator(key: str) -> PreWriteValidator:
    try:
        return PRE_WRITE_VALIDATORS[key]
    except KeyError as exc:
        raise PreWriteValidationError(f"未知预写校验器：{key}") from exc


__all__ = ["PRE_WRITE_VALIDATORS", "PreWriteValidationError", "get_pre_write_validator"]
