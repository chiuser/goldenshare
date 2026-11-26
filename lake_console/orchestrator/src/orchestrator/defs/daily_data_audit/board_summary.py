"""Apply versioned Eastmoney board evidence to the existing daily report."""

import json
from collections import Counter
from datetime import datetime

from orchestrator.defs.daily_data_audit.evidence import SHANGHAI, metadata

RAW_CLASSIFICATION = "raw_tushare_dc_index"
SILVER_CLASSIFICATION = "silver_dc_index"
RAW_MONEYFLOW = "raw_tushare_moneyflow_ind_dc"
BOARD_CHECKS = {
    RAW_CLASSIFICATION: "raw_tushare_dc_index_core_check",
    SILVER_CLASSIFICATION: "silver_dc_index_core_check",
    RAW_MONEYFLOW: "raw_tushare_moneyflow_ind_dc_file_contract_check",
}
BOARD_CATEGORIES = ("行业板块", "地域板块", "概念板块")


def _category_codes(boards, category):
    return {board["code"] for board in boards if board["category"] == category}


def _classification_components(current, reference, concept_status):
    components = []
    for category in BOARD_CATEGORIES:
        if category == "概念板块" and concept_status is not None:
            status, code, message = concept_status
        elif reference is None:
            status, code, message = "pending", "reference_missing", "参照标准集缺失"
        else:
            actual = _category_codes(current, category)
            expected = _category_codes(reference, category)
            if actual == expected:
                status, code, message = (
                    "complete",
                    "check_passed",
                    "板块代码与标准集一致",
                )
            else:
                status, code, message = (
                    "gap",
                    "published_coverage",
                    f"缺少 {len(expected - actual)} 个，多出 {len(actual - expected)} 个",
                )
        components.append(
            {
                "name": f"东方财富{category}",
                "status": status,
                "reason": {"code": code, "message": message},
            }
        )
    return components


def _raw_classification(row, review, standard, publication_fields):
    reference = standard or review.get("reference")
    concept_status = None
    if not standard:
        if (review.get("recheck") or {}).get("has_confirmed_gap"):
            concept_status = (
                "gap",
                "published_coverage",
                "Tushare 已确认本地板块名单有缺口",
            )
        elif review.get("reason") == "manual_review":
            concept_status = (
                "pending",
                "manual_review",
                "概念板块名单有增减，需要人工核查"
                if reference
                else "需要确认首份东方财富板块分类标准集",
            )
        elif reference:
            concept_status = "pending", "not_verified", "等待保存当天标准集"
    current = review["current"]
    components = _classification_components(
        current, reference["boards"] if reference else None, concept_status
    )
    _apply_classification(row, components, current, reference)
    if version := publication_fields.get("tushare_source_fingerprint"):
        row["version"]["target_version"] = version


def _apply_classification(row, components, current, reference):
    statuses = {component["status"] for component in components}
    status = (
        "gap"
        if "gap" in statuses
        else "pending"
        if "pending" in statuses
        else "complete"
    )
    reason = next(
        component["reason"] for component in components if component["status"] == status
    )
    row["completeness"].update(
        status=status,
        reason=reason,
        components=components,
        actual_count=len(current),
        expected_count=len(reference["boards"]) if reference else None,
    )
    if reference:
        expected = {(board["category"], board["code"]) for board in reference["boards"]}
        actual = {(board["category"], board["code"]) for board in current}
        row["completeness"].update(
            missing_count=len(expected - actual),
            extra_count=len(actual - expected),
        )


def _silver_classification(row, fields, publication_fields, standard):
    parity = fields.get("board_parity") or {}
    current = fields.get("board_classification_codes")
    target_version = (publication_fields.get("board_classification_input") or {}).get(
        "target_version"
    )
    if not (
        current is not None
        and target_version
        and parity.get("target_version") == target_version
        and parity.get("status") in {"complete", "gap"}
    ):
        return
    if not standard or parity.get("raw_run_id") != standard["raw_run_id"]:
        row["completeness"]["reason"] = {
            "code": "upstream_parity_only",
            "message": "转换已有核对结果，等待同版 Raw 标准集",
        }
        return
    components = _classification_components(current, standard["boards"], None)
    _apply_classification(row, components, current, standard)
    if parity["status"] == "gap":
        row["completeness"].update(
            status="gap",
            reason={
                "code": "published_coverage",
                "message": "板块代码与同版 Raw 的转换结果不一致",
            },
        )
    row["version"]["target_version"] = json.dumps(target_version, separators=(",", ":"))


def _moneyflow(row, fields, delivery, publication_fields, standard):
    proof = fields.get("board_coverage") or {}
    version = publication_fields.get("file_sha256")
    if not (
        standard
        and version
        and proof.get("file_version") == version
        and proof.get("raw_run_id") == delivery.materialization.run_id
        and proof.get("standard_version") == standard["version"]
        and proof.get("status") in {"complete", "gap"}
    ):
        row["completeness"].update(
            status="pending",
            reason={
                "code": "not_verified" if standard else "reference_missing",
                "message": "等待同版东方财富板块资金流向 Check"
                if standard
                else "等待当日板块分类标准集",
            },
        )
        return
    missing = proof.get("missing_codes", [])
    extra = proof.get("extra_codes", [])
    row["completeness"].update(
        status=proof["status"],
        reason={
            "code": "published_coverage",
            "message": "已按同版标准集逐类别核对板块代码",
        },
        expected_count=proof["expected_count"],
        actual_count=proof["actual_count"],
        missing_count=len(missing),
        extra_count=len(extra),
        samples=[
            {"ts_code": code, "change": change}
            for change, codes in (("缺少", missing), ("多出", extra))
            for code in codes[:10]
        ],
    )
    row["version"]["target_version"] = version


def apply_board_summary(report, evidence, review, standard, changed):
    """Refresh only the selected audit fields, preserving published update states."""
    raw = evidence.get(RAW_CLASSIFICATION)
    raw_run_id = raw.materialization.run_id if raw and raw.materialization else None
    if not standard or standard.get("raw_run_id") != raw_run_id:
        standard = None
    if review and review.get("raw_run_id") != raw_run_id:
        review = None
    rows = []
    for original in report["rows"]:
        key = original["scope"]["asset_key"]
        if (
            key not in changed
            or key not in BOARD_CHECKS
            or original["completeness"]["status"] == "not_applicable"
        ):
            rows.append(original)
            continue
        row = {
            **original,
            "version": dict(original["version"]),
            "completeness": dict(original["completeness"]),
        }
        rows.append(row)
        row["version"].update(
            target_version=None, inputs=[], rule_version="dc_board_standard_v1"
        )
        row["completeness"].update(
            status="pending",
            reason={
                "code": "not_verified",
                "message": "缺少当次产出的同版板块核验结果",
            },
            expected_count=None,
            actual_count=None,
            missing_count=None,
            extra_count=None,
            checked_at=None,
            samples=[],
            evidence=[],
            components=[
                {
                    "name": f"东方财富{category}",
                    "status": "pending",
                    "reason": {
                        "code": "not_verified",
                        "message": "等待同版板块核验结果",
                    },
                }
                for category in BOARD_CATEGORIES
            ]
            if key != RAW_MONEYFLOW
            else [],
        )
        delivery = evidence.get(key)
        if key == RAW_CLASSIFICATION:
            row.pop("board_review", None)
            if review:
                row["board_review"] = review
        if not delivery or not delivery.materialization:
            continue
        check = delivery.checks.get(BOARD_CHECKS[key])
        if not check:
            continue
        fields = metadata(check.evaluation)
        publication_fields = metadata(delivery.materialization.asset_materialization)
        if not check.evaluation.passed:
            row["completeness"]["reason"] = {
                "code": "not_verified",
                "message": "同版生产 Check 未通过",
            }
        elif key == RAW_CLASSIFICATION and review and review["current"]:
            _raw_classification(row, review, standard, publication_fields)
        elif key == SILVER_CLASSIFICATION:
            _silver_classification(row, fields, publication_fields, standard)
        elif key == RAW_MONEYFLOW:
            _moneyflow(row, fields, delivery, publication_fields, standard)
        complete = row["completeness"]
        complete["checked_at"] = datetime.fromtimestamp(
            check.event.timestamp, SHANGHAI
        ).isoformat()
        complete["evidence"] = [
            {
                "type": "check",
                "check_name": BOARD_CHECKS[key],
                "run_id": check.run_id,
                "record_id": check.id,
                "target_version": row["version"]["target_version"],
                "passed": check.evaluation.passed,
                "message": complete["reason"]["message"],
            }
        ]
        if standard:
            row["version"].update(
                inputs=[
                    {
                        "asset_key": RAW_CLASSIFICATION,
                        "target_version": standard["version"],
                    }
                ],
                rule_version="dc_board_standard_v1",
            )
    counts = Counter(row["completeness"]["status"] for row in rows)
    output = {
        **report,
        "rows": rows,
        "summary": dict.fromkeys(report["summary"], 0) | dict(counts),
    }
    if RAW_CLASSIFICATION in changed:
        output["board_standard_version"] = standard["version"] if standard else None
    return output
