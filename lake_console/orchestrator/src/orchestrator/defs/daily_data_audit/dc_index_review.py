"""Read and compare one day's Oriental Fortune board classification evidence."""

import json
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.asset_guards.dc_board_source_probe import normalize_tushare_rows
from orchestrator.defs.catalog.lake_assets import get_lake_asset_catalog_entry
from orchestrator.defs.daily_data_audit.evidence import (
    BUSINESS_DATE_TAG,
    SHANGHAI,
    DeliveryEvidence,
    load_evidence,
    metadata,
)
from orchestrator.defs.daily_data_audit.registry import AuditTarget
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    raw_dc_daily_path,
    raw_dc_index_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_FIELDS,
    DC_INDEX_FIELDS,
    RAW_DC_INDEX_CHECKS,
    build_dc_board_tushare_source_snapshot,
    is_dc_index_placeholder,
)

BOARD_CONFIRM_JOB = "daily_data_audit_board_confirm_job"
BOARD_RECHECK_JOB = "daily_data_audit_board_recheck_job"
BOARD_STANDARD_META = "dc_index_standard"
BOARD_RECHECK_META = "dc_index_recheck"
REVIEW_VERSION_TAG = "audit/review_version"
BOARD_CODES_META = "board_classification_codes"
RAW_DC_INDEX = "raw_tushare_dc_index"
CONCEPT = "概念板块"
BASELINE_DAY = date(2026, 11, 19)
ACTIVE_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.NOT_STARTED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)
_UNSET_EVIDENCE = object()


def _read_board_output(
    instance, business_date, job_name, key, *, review_version=None, run_id=None
):
    tags = {BUSINESS_DATE_TAG: business_date.isoformat()}
    if review_version is not None:
        tags[REVIEW_VERSION_TAG] = review_version
    runs = instance.get_runs(
        filters=dg.RunsFilter(
            job_name=job_name,
            tags=tags,
            run_ids=[run_id] if run_id else None,
            statuses=[dg.DagsterRunStatus.SUCCESS],
        ),
        limit=1,
    )
    if not runs:
        return None
    records = instance.get_records_for_run(
        runs[0].run_id,
        of_type=dg.DagsterEventType.STEP_OUTPUT,
        limit=1,
    ).records
    if not records:
        return None
    output = records[0].event_log_entry.dagster_event.step_output_data.metadata.get(key)
    if not isinstance(output, dg.JsonMetadataValue) or not isinstance(
        output.value, dict
    ):
        return None
    result = output.value
    standard = key == BOARD_STANDARD_META
    run_id_key = "version" if standard else "run_id"
    records_key = "boards" if standard else "results"
    expected_review_version = runs[0].tags.get(REVIEW_VERSION_TAG)
    if (
        result.get("business_date") != business_date.isoformat()
        or result.get(run_id_key) != runs[0].run_id
        or not expected_review_version
        or result.get("review_version") != expected_review_version
        or not isinstance(result.get(records_key), list)
        or (not standard and not isinstance(result.get("has_confirmed_gap"), bool))
    ):
        return None
    return result


def read_dc_index_standard(instance, business_date, *, run_id=None):
    """Read the latest successful standard for one business date, or an exact version."""
    return _read_board_output(
        instance,
        business_date,
        BOARD_CONFIRM_JOB,
        BOARD_STANDARD_META,
        run_id=run_id,
    )


def read_dc_index_recheck(instance, business_date, review_version, *, run_id=None):
    """Read prior source results for the exact review version only."""
    return _read_board_output(
        instance,
        business_date,
        BOARD_RECHECK_JOB,
        BOARD_RECHECK_META,
        review_version=review_version,
        run_id=run_id,
    )


def find_active_board_run(instance, business_date, review_version, job_name):
    """Support submission deduplication for a specific board operation."""
    runs = instance.get_runs(
        filters=dg.RunsFilter(
            job_name=job_name,
            tags={
                BUSINESS_DATE_TAG: business_date.isoformat(),
                REVIEW_VERSION_TAG: review_version,
            },
            statuses=ACTIVE_STATUSES,
        ),
        limit=1,
    )
    return runs[0] if runs else None


def _raw_index_evidence(instance, day):
    target = AuditTarget(
        get_lake_asset_catalog_entry(RAW_DC_INDEX),
        day.isoformat(),
        day,
        True,
        RAW_DC_INDEX_CHECKS,
        False,
        "日更",
    )
    return load_evidence(instance, (target,), day, datetime.now(SHANGHAI)).get(
        RAW_DC_INDEX
    )


def _read_previous_trade_date(root, day):
    with connect_configured_duckdb(temp_policy="existing_no_spill") as connection:
        record = connection.execute(
            "SELECT pretrade_date FROM read_parquet(?) "
            "WHERE exchange = 'SSE' AND trade_date = ? AND is_open",
            [str(silver_trade_calendar_path(root)), day],
        ).fetchone()
    return record[0] if record else None


def _read_historical_boards(root, day, expected_fingerprint):
    if not expected_fingerprint:
        return None
    day_key = day.isoformat()
    with connect_configured_duckdb(temp_policy="existing_no_spill") as connection:
        index_rows = _read_source_rows(
            connection, raw_dc_index_path(root, day_key), DC_INDEX_FIELDS
        )
        daily_rows = _read_source_rows(
            connection, raw_dc_daily_path(root, day_key), DC_DAILY_FIELDS
        )
    snapshot = build_dc_board_tushare_source_snapshot(
        trade_date=day_key,
        index_rows=index_rows,
        daily_rows=daily_rows,
    )
    if snapshot.source_fingerprint != expected_fingerprint:
        return None
    return [
        {"category": row["idx_type"], "code": row["ts_code"], "name": row["name"]}
        for row in index_rows
        if not is_dc_index_placeholder(row)
    ]


def _read_source_rows(connection, path, fields):
    projection = ", ".join(f'"{field}"' for field in fields)
    rows = connection.execute(
        f"SELECT {projection} FROM read_parquet(?, hive_partitioning=false)",
        [str(path)],
    ).fetchall()
    return normalize_tushare_rows(
        [dict(zip(fields, row, strict=True)) for row in rows], fields
    )


def _snapshot_boards(bundle: DeliveryEvidence | None, day, root, use_history, standard, historical_candidate):
    if not bundle or not bundle.materialization:
        return None, None, False
    publication = bundle.materialization
    facts = bundle.checks.get(RAW_DC_INDEX_CHECKS[0])
    if facts is None or facts.status.value != "SUCCEEDED":
        return None, None, False
    evaluation = facts.evaluation
    target = evaluation.target_materialization_data
    if target is None or target.storage_id != publication.storage_id:
        return None, None, False
    fingerprint = metadata(publication.asset_materialization).get(
        "tushare_source_fingerprint"
    )
    boards = metadata(evaluation).get(BOARD_CODES_META)
    if (
        boards is None
        and fingerprint
        and standard
        and standard["raw_run_id"] == publication.run_id
        and standard["raw_fingerprint"] == fingerprint
    ):
        boards = standard["boards"]
    if (
        boards is None and historical_candidate and historical_candidate.get("used_history")
        and fingerprint and historical_candidate["raw_fingerprint"] == fingerprint
        and historical_candidate["raw_run_id"] == publication.run_id
    ):
        return historical_candidate["current"], fingerprint, True
    if boards is None and use_history:
        try:
            boards = _read_historical_boards(root, day, fingerprint)
        except (OSError, duckdb.Error):
            boards = None
        return boards, fingerprint, boards is not None
    return boards, fingerprint, False


def _board_identity(board):
    return board["category"], board["code"]


def read_board_review(
    instance,
    business_date: date,
    *,
    previous_trade_date: date | None,
    raw_evidence=_UNSET_EVIDENCE,
    use_history: bool = False,
    lake_root: Path = DEFAULT_LAKE_ROOT,
    historical_candidate: dict | None = None,
) -> dict:
    """Build the current comparison. With supplied evidence normal reads use metadata only."""
    bundle = (
        _raw_index_evidence(instance, business_date)
        if raw_evidence is _UNSET_EVIDENCE
        else raw_evidence
    )
    reference = (
        read_dc_index_standard(instance, previous_trade_date)
        if previous_trade_date
        else None
    )
    publication = bundle.materialization if bundle else None
    standard = read_dc_index_standard(instance, business_date)
    boards, fingerprint, used_history = _snapshot_boards(
        bundle,
        business_date,
        lake_root,
        use_history,
        standard,
        historical_candidate,
    )
    raw_run_id = publication.run_id if publication else None
    result = {
        "business_date": business_date.isoformat(),
        "review_version": None,
        "raw_run_id": raw_run_id,
        "raw_fingerprint": fingerprint,
        "used_history": used_history,
        "state": "pending",
        "reason": "not_verified",
        "can_confirm": False,
        "reference": reference,
        "current": [],
        "added": [],
        "removed": [],
        "standard": None,
        "recheck": None,
    }
    if boards:
        result["current"] = sorted(boards, key=_board_identity)
    baseline = business_date == BASELINE_DAY and (
        use_history
        or (
            standard
            and standard["raw_run_id"] == raw_run_id
            and standard["reference_version"] is None
        )
    )
    if reference is None and not baseline:
        return {**result, "state": "reference_missing", "reason": "reference_missing"}
    if not boards:
        return result
    current = {_board_identity(board): board for board in boards}
    previous = (
        {_board_identity(board): board for board in reference["boards"]}
        if reference
        else {}
    )
    # Compare coverage by category and code. Name changes alone do not change coverage.
    added = (
        [current[key] for key in sorted(current.keys() - previous.keys())]
        if reference
        else []
    )
    removed = [previous[key] for key in sorted(previous.keys() - current.keys())]
    version_payload = [
        business_date.isoformat(),
        raw_run_id,
        fingerprint,
        reference["version"] if reference else None,
        result["current"],
        added,
        removed,
    ]
    review_version = sha256(
        json.dumps(
            version_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    if standard and standard["review_version"] != review_version:
        standard = None
    recheck = (
        read_dc_index_recheck(instance, business_date, review_version)
        if any(board["category"] == CONCEPT for board in (*added, *removed))
        else None
    )
    gap = recheck is not None and recheck["has_confirmed_gap"]
    return {
        **result,
        "review_version": review_version,
        "state": "ready" if standard else "pending",
        "reason": (
            None
            if standard
            else "confirmed_source_gap"
            if gap
            else "manual_review"
            if baseline or added or removed
            else "standard_pending"
        ),
        "can_confirm": standard is None and not gap,
        "added": added,
        "removed": removed,
        "standard": standard,
        "recheck": recheck,
    }


def read_board_review_for_job(
    instance, business_date: date, *, use_history=False
) -> dict:
    """Resolve the one SSE calendar row only when a review job actually runs."""
    root = Path(DEFAULT_LAKE_ROOT)
    if use_history and business_date < BASELINE_DAY:
        raise ValueError("历史接续从 2026-11-19 开始")
    previous = (
        None
        if use_history and business_date == BASELINE_DAY
        else _read_previous_trade_date(root, business_date)
    )
    return read_board_review(
        instance,
        business_date,
        previous_trade_date=previous,
        use_history=use_history,
        lake_root=root,
    )
