"""Lossless audit of native, partially populated review submissions."""
from copy import deepcopy
from typing import Mapping

from .review_policy import REVIEW_FIELDS, resolve_review


def audit_submission(*, response: Mapping[str, object], prediction, role: str,
                     source_text: str) -> dict[str, object]:
    """Never interpret an omitted nonempty suggestion as a human answer."""
    original = deepcopy(dict(response))
    normalized = deepcopy(original)
    issues = []

    def issue(code, fields, message):
        issues.append({"code": code, "fields": fields, "message": message})

    clear = normalized.pop("clear_fields", [])
    if not isinstance(clear, list) or any(
        key not in {"secondary_topics", "industries", "interest_tags"} for key in clear
    ):
        issue("INVALID_CLEAR_FIELDS", ["clear_fields"], "清空字段不合法")
        clear = []
    if clear and normalized.get("review_action") != "EDIT":
        issue("CLEAR_REQUIRES_EDIT", ["review_action", "clear_fields"], "清空需选择修改")
    for key in clear:
        if normalized.get(key):
            issue("FILL_AND_CLEAR", [key, "clear_fields"], "不能同时填写和清空")
        else:
            normalized[key] = []
    # An explicit negative status may clear an OMITTED dependent field, never
    # an explicitly submitted value. Contradictions remain visible to humans.
    if normalized.get("event_type_status") in {"NOT_APPLICABLE", "UNRESOLVED"}:
        normalized.setdefault("primary_event_type", None)
    if normalized.get("industry_status") in {"NONE", "UNKNOWN"}:
        normalized.setdefault("industries", [])
    if normalized.get("review_action") == "LABEL":
        for key in ("secondary_topics", "industries", "interest_tags"):
            normalized.setdefault(key, [])
        if normalized.get("classification_status") != "CLASSIFIED":
            normalized.setdefault("topic_path", None)

    action = normalized.get("review_action")
    base = prediction.get("values", {}) if isinstance(prediction, Mapping) else {}
    # A lone ACCEPT deliberately accepts the entire frozen proposal. Partial
    # forms, however, can omit a value because the user cleared it in the UI.
    lone_accept = action == "ACCEPT" and not any(k in original for k in REVIEW_FIELDS)
    if action in {"ACCEPT", "EDIT"} and not lone_accept:
        missing = [k for k in REVIEW_FIELDS if k not in normalized and base.get(k) not in (None, [])]
        if missing:
            issue("OMITTED_SUGGESTION", missing, "原建议未随提交返回：需确认保留还是清空")
    try:
        resolved = resolve_review(response=normalized, prediction=prediction,
                                  role=role, source_text=source_text)
    except ValueError as exc:
        issue("INVALID_REVIEW", list(k for k in REVIEW_FIELDS if k in original), str(exc))
        resolved = None
    if issues:
        return {"machine_prediction": deepcopy(prediction), "human_response": original,
                "final_values": None, "changed_fields": [], "status": "NEEDS_CONFIRMATION",
                "review_issues": issues}
    return {**resolved, "human_response": original, "review_issues": []}
