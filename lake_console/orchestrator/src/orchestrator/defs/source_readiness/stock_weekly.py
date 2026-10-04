"""Bounded physical reference capture and source completion verification."""

from datetime import date, timedelta

from orchestrator.defs.bootstrap.stock_weekly_candidates import fingerprint
from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    raw_trade_calendar_path,
    silver_stock_identity_map_path,
)
from orchestrator.defs.run_contracts.stock_weekly import WeeklyBudget
from orchestrator.defs.stock_weekly_update import (
    WEEKLY_UPDATE_POLICY,
    weekly_open_dates,
)


def load_weekly_calendar(connection, root, week):
    path = raw_trade_calendar_path(root)
    before = fingerprint(path)
    if before is None:
        raise WeeklyCaptureError("calendar_missing")
    friday = date.fromisoformat(week)
    rows = connection.execute(
        "SELECT cal_date,is_open FROM read_parquet(?,hive_partitioning=false) "
        "WHERE exchange='SSE' AND cal_date BETWEEN ? AND ?",
        [
            str(path),
            (friday - timedelta(days=4)).strftime("%Y%m%d"),
            friday.strftime("%Y%m%d"),
        ],
    ).fetchall()
    calendar = {date.fromisoformat(day).isoformat(): opened for day, opened in rows}
    if len(rows) != len(calendar) or fingerprint(path) != before:
        raise WeeklyCaptureError("calendar_changed_or_duplicate")
    try:
        days = weekly_open_dates(week, calendar)
    except ValueError as error:
        raise WeeklyCaptureError("calendar_incomplete") from error
    return days, {"path": str(path), "sha256": before}


def load_weekly_reference(connection, root, week, *, upstream_ready):
    """Upstream event checks supplied by caller; one week, no listed-only filter."""
    days, calendar = load_weekly_calendar(connection, root, week)
    if not days:
        raise WeeklyCaptureError("no_trading_week")
    if len(days) > WEEKLY_UPDATE_POLICY.max_daily_files:
        raise WeeklyCaptureError("weekly_reference_budget_exceeded")
    identity = silver_stock_identity_map_path(root)
    paths = [raw_stock_daily_path(root, day) for day in days]
    references = [
        calendar,
        *[
            {"path": str(path), "sha256": fingerprint(path)}
            for path in [identity, *paths]
        ],
    ]
    if any(item["sha256"] is None for item in references):
        raise WeeklyCaptureError("weekly_upstream_file_missing")
    if not upstream_ready(days):
        raise WeeklyCaptureError("weekly_upstream_not_ready")
    identities = connection.execute(
        "SELECT source_ts_code,latest_ts_code,confidence FROM "
        "read_parquet(?,hive_partitioning=false) LIMIT ?",
        [str(identity), WeeklyBudget().max_codes + 1],
    ).fetchall()
    if len(identities) > WeeklyBudget().max_codes:
        raise WeeklyCaptureError("weekly_identity_budget_exceeded")
    canonical = {}
    for code, latest, confidence in identities:
        if code in canonical or not code or not latest:
            raise WeeklyCaptureError("weekly_identity_invalid")
        canonical[code] = latest if confidence == "confirmed" else None
    rows = connection.execute(
        "SELECT ts_code,trade_date,filename FROM read_parquet(?,hive_partitioning=false,union_by_name=false,filename=true) LIMIT ?",
        [[str(p) for p in paths], WEEKLY_UPDATE_POLICY.max_reference_rows + 1],
    ).fetchall()
    if len(rows) > WEEKLY_UPDATE_POLICY.max_reference_rows:
        raise WeeklyCaptureError("weekly_reference_budget_exceeded")
    allowed = {day.replace("-", "") for day in days}
    expected, seen, observed_days = {}, set(), set()
    placement = {
        str(path): day.replace("-", "") for path, day in zip(paths, days, strict=True)
    }
    for code, day, filename in rows:
        if day not in allowed or placement.get(filename) != day or (code, day) in seen:
            raise WeeklyCaptureError("weekly_daily_keys_invalid")
        seen.add((code, day))
        observed_days.add(day)
        latest = canonical.get(code)
        if latest is None:
            raise WeeklyCaptureError("weekly_identity_unresolved")
        expected[latest] = max(expected.get(latest, day), day)
    if observed_days != allowed or not expected:
        raise WeeklyCaptureError("weekly_daily_coverage_unverified")
    assert_weekly_references_unchanged(references)
    return {
        "week": week,
        "open_dates": days,
        "expected": expected,
        "canonical": canonical,
        "references": references,
        "daily_rows": len(rows),
    }


def assert_weekly_references_unchanged(references):
    from pathlib import Path

    if any(fingerprint(Path(item["path"])) != item["sha256"] for item in references):
        raise WeeklyCaptureError("weekly_reference_changed")


def verify_weekly_source_completion(rows, reference):
    """Preserve rows; identity is only an audit coordinate, never a Raw rewrite."""
    expected = reference["expected"]
    canonical = reference["canonical"]
    if not rows or len(rows) > WeeklyBudget().max_codes:
        raise WeeklyCaptureError("weekly_source_empty_or_over_budget")
    observed = {}
    week = reference["week"].replace("-", "")
    for code, trade_date, cutoff, freq in rows:
        latest = canonical.get(code)
        if latest is None:
            raise WeeklyCaptureError("weekly_identity_unresolved")
        if trade_date != week or freq != "week":
            raise WeeklyCaptureError("weekly_source_coordinate_mismatch")
        try:
            parsed = date.fromisoformat(cutoff)
        except (TypeError, ValueError) as error:
            raise WeeklyCaptureError("weekly_source_cutoff_invalid") from error
        if parsed.strftime("%Y%m%d") != cutoff:
            raise WeeklyCaptureError("weekly_source_cutoff_invalid")
        observed[latest] = max(observed.get(latest, cutoff), cutoff)
    if set(expected) - set(observed):
        raise WeeklyCaptureError("weekly_source_coverage_incomplete")
    if any(observed[code] < day for code, day in expected.items()):
        raise WeeklyCaptureError("weekly_source_not_ready")
    return {
        "expected_codes": len(expected),
        "source_rows": len(rows),
        "reason_code": "ready",
    }
