"""Frozen announcement bootstrap intent; planning does not create Lake paths."""

import hashlib
import json
import os
import shutil
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from orchestrator.defs.anns_d_checkpoint import (
    announcement_atomic_json,
    announcement_file_fingerprint,
    assert_safe_announcement_path,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_VERSION,
    AnnouncementError,
    announcement_dates,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_anns_d_path,
)
from orchestrator.defs.prod_db.anns_d import announcement_month_bounds
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy

BOOTSTRAP_MIN_FREE_BYTES = 35 * 1024**3
ANNOUNCEMENT_REPORT_MAX_BYTES = 8 * 1024**2


def history_document_fingerprint(document):
    values = {key: value for key, value in document.items() if key != "fingerprint"}
    return hashlib.sha256(
        json.dumps(
            values,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def seal_history_document(document):
    return {**document, "fingerprint": history_document_fingerprint(document)}


def load_announcement_history_document(path, *, kind, fingerprint=None):
    path = assert_safe_announcement_path(path)
    if not path.is_file() or path.stat().st_size > ANNOUNCEMENT_REPORT_MAX_BYTES:
        raise AnnouncementError("announcement_report_budget")
    document = json.loads(path.read_text())
    if document.get("kind") != kind or document.get(
        "fingerprint"
    ) != history_document_fingerprint(document):
        raise AnnouncementError("announcement_report_fingerprint")
    if fingerprint is not None and fingerprint != document["fingerprint"]:
        raise AnnouncementError("announcement_plan_identity")
    return document


def save_announcement_history_report(path, document):
    path = assert_safe_announcement_path(path)
    if Path("/private/tmp") not in path.parents:
        raise AnnouncementError("announcement_report_requires_private_tmp")
    if path.exists():
        raise AnnouncementError("announcement_report_exists")
    announcement_atomic_json(path, document)


def announcement_bootstrap_volume_gate(root, staging):
    root, staging = (
        assert_safe_announcement_path(root),
        assert_safe_announcement_path(staging),
    )
    if not root.is_dir() or not staging.is_dir():
        raise AnnouncementError("announcement_volume_missing")
    if root == Path(DEFAULT_LAKE_ROOT) and (
        staging != Path(DEFAULT_LAKE_STAGING_ROOT)
        or not os.path.ismount("/Volumes/datasource")
    ):
        raise AnnouncementError("announcement_formal_volume_contract")
    if (
        staging == root
        or root in staging.parents
        or "goldenshare-tushare-lake" in root.parts
    ):
        raise AnnouncementError("announcement_bootstrap_root_contract")
    if root.stat().st_dev != staging.stat().st_dev:
        raise AnnouncementError("announcement_volume_changed")
    free = shutil.disk_usage(staging).free
    if (
        free < BOOTSTRAP_MIN_FREE_BYTES
        or not os.access(root, os.W_OK)
        or not os.access(staging, os.W_OK)
    ):
        raise AnnouncementError("announcement_bootstrap_space")
    return free


def validate_announcement_history_plan(
    plan, *, roots=(DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT)
):
    if (
        plan.get("kind") != "anns_d_history_plan"
        or plan.get("contract_version") != ANNOUNCEMENT_VERSION
    ):
        raise AnnouncementError("announcement_plan_contract")
    if plan["fingerprint"] != history_document_fingerprint(plan):
        raise AnnouncementError("announcement_plan_identity")
    if (plan["lake_root"], plan["staging_root"]) != tuple(map(str, roots)):
        raise AnnouncementError("announcement_cli_formal_roots_only")
    try:
        AnnouncementPolicy(**plan["policy"])
    except (TypeError, ValueError):
        raise AnnouncementError("announcement_plan_policy") from None
    if (
        not plan["run_id"]
        or not plan["run_id"].replace("-", "").replace("_", "").isalnum()
    ):
        raise AnnouncementError("announcement_invalid_run_id")
    first, _ = announcement_month_bounds(plan["start_date"])
    _, end = announcement_month_bounds(plan["end_date"])
    dates = announcement_dates(plan["start_date"], plan["end_date"])
    if (
        first.isoformat() != dates[0]
        or (end - timedelta(days=1)).isoformat() != dates[-1]
    ):
        raise AnnouncementError("announcement_bootstrap_full_months_required")
    planned_dates = [item["day"] for month in plan["months"] for item in month["days"]]
    if planned_dates != list(dates):
        raise AnnouncementError("announcement_plan_dates")
    for month in plan["months"]:
        if (
            type(month["upper_id"]) is not int
            or month["upper_id"] < 0
            or (month["source_rows"] and not month["upper_id"])
        ):
            raise AnnouncementError("announcement_inventory_upper_id")
        bound, next_month = announcement_month_bounds(month["month"])
        if (
            month["month"] != bound.isoformat()
            or month["days"][0]["day"] != bound.isoformat()
            or month["days"][-1]["day"] != (next_month - timedelta(days=1)).isoformat()
        ):
            raise AnnouncementError("announcement_plan_month")
        if (
            sum(day["source_rows"] for day in month["days"]) != month["source_rows"]
            or month["source_rows"] > plan["policy"]["max_month_rows"]
        ):
            raise AnnouncementError("announcement_plan_count")
        for day in month["days"]:
            if (
                type(day["source_rows"]) is not int
                or day["source_rows"] < 0
                or day["target"]
                != str(raw_anns_d_path(Path(plan["lake_root"]), day["day"]))
            ):
                raise AnnouncementError("announcement_plan_target")
    return plan


def make_announcement_history_plan(
    start,
    end,
    run_id,
    inventory,
    policy,
    *,
    root=Path(DEFAULT_LAKE_ROOT),
    staging=Path(DEFAULT_LAKE_STAGING_ROOT),
):
    if not run_id or not run_id.replace("-", "").replace("_", "").isalnum():
        raise AnnouncementError("announcement_invalid_run_id")
    first, _ = announcement_month_bounds(start)
    _, stop = announcement_month_bounds(end)
    dates = announcement_dates(start, end)
    if first.isoformat() != start or (stop - timedelta(days=1)).isoformat() != end:
        raise AnnouncementError("announcement_bootstrap_full_months_required")
    free = announcement_bootstrap_volume_gate(root, staging)
    indexed = {row["day"]: row for row in inventory}
    if len(indexed) != len(inventory) or not set(indexed).issubset(dates):
        raise AnnouncementError("announcement_inventory_dates")
    months = []
    month = first
    while month < stop:
        _, last = announcement_month_bounds(month.isoformat())
        days = []
        for index in range((last - month).days):
            day = (month + timedelta(days=index)).isoformat()
            target = raw_anns_d_path(root, day)
            days.append(
                {
                    "day": day,
                    "source_rows": indexed.get(day, {}).get("rows", 0),
                    "target": str(target),
                    "baseline": announcement_file_fingerprint(target),
                }
            )
        rows = sum(day["source_rows"] for day in days)
        if rows > policy.max_month_rows:
            raise AnnouncementError("announcement_month_budget")
        upper = max(
            (indexed.get(day["day"], {}).get("upper_id", 0) for day in days), default=0
        )
        if rows and upper <= 0:
            raise AnnouncementError("announcement_inventory_upper_id")
        months.append(
            {
                "month": month.isoformat(),
                "source_rows": rows,
                "upper_id": upper,
                "days": days,
            }
        )
        month = last
    document = seal_history_document(
        {
            "kind": "anns_d_history_plan",
            "contract_version": ANNOUNCEMENT_VERSION,
            "run_id": run_id,
            "start_date": start,
            "end_date": end,
            "lake_root": str(root),
            "staging_root": str(staging),
            "policy": asdict(policy),
            "months": months,
            "cost": {
                "months": len(months),
                "days": len(dates),
                "source_rows": sum(m["source_rows"] for m in months),
                "expected_files": len(dates),
                "estimated_seconds_range": [900, 3600] if len(months) == 81 else None,
                "estimate_basis": "P0 full-history budget; sample calibration pending",
                "min_free_bytes": BOOTSTRAP_MIN_FREE_BYTES,
                "free_bytes_observed": free,
                "max_source_batch_rows": policy.prod_fetch_rows,
                "source_requests": 0,
                "event_writes": 0,
            },
        }
    )
    return validate_announcement_history_plan(document, roots=(root, staging))
