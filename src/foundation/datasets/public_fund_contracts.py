from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

FUND_COMPANY_SOURCE_FIELDS = (
    "name",
    "shortname",
    "short_enname",
    "province",
    "city",
    "address",
    "phone",
    "office",
    "website",
    "chairman",
    "manager",
    "reg_capital",
    "setup_date",
    "end_date",
    "employees",
    "main_business",
    "org_code",
    "credit_code",
)

MKT_IDX_BMK_SOURCE_FIELDS = (
    "ts_code",
    "symbol",
    "name",
    "fullname",
    "bmk_level",
    "bmk_type",
    "bmk_src",
    "idx_type",
)

FUND_BASIC_SOURCE_FIELDS = (
    "ts_code",
    "name",
    "management",
    "custodian",
    "fund_type",
    "found_date",
    "due_date",
    "list_date",
    "issue_date",
    "delist_date",
    "issue_amount",
    "m_fee",
    "c_fee",
    "duration_year",
    "p_value",
    "min_amount",
    "exp_return",
    "benchmark",
    "status",
    "invest_type",
    "type",
    "trustee",
    "purc_startdate",
    "redm_startdate",
    "market",
)

FUND_MANAGER_SOURCE_FIELDS = (
    "ts_code",
    "ann_date",
    "name",
    "gender",
    "birth_year",
    "edu",
    "nationality",
    "begin_date",
    "end_date",
    "resume",
)


def fund_company_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return the conservative source-record entity key and its basis.

    This function intentionally does not rewrite source values.  It only builds
    metadata that lets the observed-snapshot protocol preserve current variants
    sharing one legal credit code.
    """
    credit_code = _normalized_text(row.get("credit_code"), uppercase=True)
    if credit_code:
        return f"credit:{credit_code}", "credit_code"

    name = _normalized_text(row.get("name"))
    setup_date = _normalized_text(row.get("setup_date"))
    if name and setup_date:
        digest = _sha256_text("\x1f".join((name, setup_date)))
        return f"name_setup:{digest}", "name_setup"

    # Delayed import avoids DatasetDefinition registry -> ingestion package
    # initialization cycle.  The writer independently recomputes this exact B0
    # hash before persistence.
    from src.foundation.ingestion.observed_snapshot import compute_source_content_hash

    content_hash = compute_source_content_hash(row=row, source_fields=FUND_COMPANY_SOURCE_FIELDS)
    return f"content:{content_hash}", "content_hash_fallback"


def mkt_idx_bmk_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    ts_code = _normalized_text(row.get("ts_code"), uppercase=True)
    return ts_code, "ts_code"


def fund_basic_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    ts_code = _normalized_text(row.get("ts_code"), uppercase=True)
    return ts_code, "ts_code"


def fund_manager_identity(row: Mapping[str, Any]) -> tuple[str, str, str | None]:
    assignment_parts = (
        _normalized_text(row.get("ts_code"), uppercase=True),
        _normalized_text(row.get("ann_date")),
        _normalized_text(row.get("name")),
        _normalized_text(row.get("begin_date")),
    )
    source_entity_key = f"assignment:{_sha256_json_parts(assignment_parts)}"

    manager_parts = (
        _normalized_text(row.get("name")),
        _normalized_text(row.get("gender"), uppercase=True),
        _normalized_text(row.get("birth_year")),
    )
    manager_identity_key = None
    if all(manager_parts):
        manager_identity_key = f"manager:{_sha256_json_parts(manager_parts)}"
    return source_entity_key, "assignment_fields", manager_identity_key


def _normalized_text(value: object, *, uppercase: bool = False) -> str:
    text = str(value or "").strip()
    return text.upper() if uppercase else text


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json_parts(parts: tuple[str, ...]) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
