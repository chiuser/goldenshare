"""Bounded full-month reference capture and vectorized per-stock completion audit."""

from datetime import date
from pathlib import Path

import pandas as pd

from orchestrator.defs.bootstrap.stock_monthly_files import monthly_file_hash
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    raw_trade_calendar_path,
    silver_stock_identity_map_path,
)
from orchestrator.defs.run_contracts.stock_monthly import (
    MONTHLY_UPDATE_POLICY,
    StockMonthlyPolicy,
    month_window,
    request_date_for_month,
)
from orchestrator.defs.stock_monthly_update import monthly_open_dates


def assert_month_references_unchanged(references):
    for item in references:
        if monthly_file_hash(Path(item["path"])) != item["sha256"]:
            raise ValueError("monthly_reference_changed")


def load_monthly_calendar(connection, root, month):
    path = raw_trade_calendar_path(root)
    fingerprint = monthly_file_hash(path)
    first, upper = month_window(month)
    rows = connection.execute(
        "SELECT cal_date,is_open FROM read_parquet(?,hive_partitioning=false) WHERE exchange='SSE' AND cal_date>=? AND cal_date<? LIMIT 32",
        [str(path), first.strftime("%Y%m%d"), upper.strftime("%Y%m%d")],
    ).fetchall()
    calendar = {date.fromisoformat(day).isoformat(): opened for day, opened in rows}
    if len(rows) != len(calendar) or monthly_file_hash(path) != fingerprint:
        raise ValueError("monthly_calendar_changed_or_duplicate")
    return monthly_open_dates(month, calendar), {
        "path": str(path),
        "sha256": fingerprint,
    }


def freeze_month_references(connection, root, month, *, upstream_bindings):
    days, calendar = load_monthly_calendar(connection, root, month)
    if not days:
        raise ValueError("monthly_no_trading_days")
    if len(days) > MONTHLY_UPDATE_POLICY.max_daily_files:
        raise ValueError("monthly_reference_budget_exceeded")
    bindings = upstream_bindings(days)
    if not bindings:
        raise ValueError("monthly_upstream_not_ready")
    identity = silver_stock_identity_map_path(root)
    paths = [raw_stock_daily_path(root, day) for day in days]
    references = [
        calendar,
        *[{"path": str(p), "sha256": monthly_file_hash(p)} for p in (identity, *paths)],
    ]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE monthly_identity AS SELECT source_ts_code,latest_ts_code,confidence FROM read_parquet(?,hive_partitioning=false) LIMIT ?",
        [str(identity), StockMonthlyPolicy().max_codes + 1],
    )
    count, invalid = connection.execute(
        "SELECT count(*),count(*) FILTER(WHERE source_ts_code IS NULL OR latest_ts_code IS NULL OR trim(source_ts_code)='' OR trim(latest_ts_code)='') FROM monthly_identity"
    ).fetchone()
    if (
        count > StockMonthlyPolicy().max_codes
        or invalid
        or connection.execute(
            "SELECT count(*) FROM (SELECT source_ts_code FROM monthly_identity GROUP BY 1 HAVING count(*)>1)"
        ).fetchone()[0]
    ):
        raise ValueError("monthly_identity_invalid_or_over_budget")
    for path in paths:
        observed = connection.execute(
            "DESCRIBE SELECT ts_code,trade_date FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
        ).fetchall()
        if [r[:2] for r in observed] != [
            ("ts_code", "VARCHAR"),
            ("trade_date", "VARCHAR"),
        ]:
            raise ValueError("monthly_daily_key_schema_invalid")
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE monthly_daily AS SELECT ts_code,trade_date,filename FROM read_parquet(?,hive_partitioning=false,filename=true,union_by_name=false) LIMIT ?",
        [[str(p) for p in paths], MONTHLY_UPDATE_POLICY.max_reference_rows + 1],
    )
    connection.register(
        "monthly_placement",
        pd.DataFrame(
            {
                "filename": [str(p) for p in paths],
                "expected_date": [day.replace("-", "") for day in days],
            }
        ),
    )
    daily_rows, bad = connection.execute(
        "SELECT count(*),count(*) FILTER(WHERE d.ts_code IS NULL OR p.filename IS NULL OR d.trade_date IS DISTINCT FROM p.expected_date) FROM monthly_daily d LEFT JOIN monthly_placement p USING(filename)"
    ).fetchone()
    if daily_rows > MONTHLY_UPDATE_POLICY.max_reference_rows or bad or not daily_rows:
        raise ValueError("monthly_daily_keys_invalid_or_over_budget")
    if connection.execute(
        "SELECT count(*) FROM (SELECT ts_code,trade_date FROM monthly_daily GROUP BY 1,2 HAVING count(*)>1)"
    ).fetchone()[0] or connection.execute(
        "SELECT count(DISTINCT filename) FROM monthly_daily"
    ).fetchone()[0] != len(paths):
        raise ValueError("monthly_daily_coverage_invalid")
    if connection.execute(
        "SELECT count(*) FROM monthly_daily d LEFT JOIN monthly_identity i ON d.ts_code=i.source_ts_code WHERE i.latest_ts_code IS NULL OR i.confidence IS DISTINCT FROM 'confirmed' OR NOT regexp_full_match(i.source_ts_code,'[0-9]{6}\\.(SH|SZ|BJ)') OR NOT regexp_full_match(i.latest_ts_code,'[0-9]{6}\\.(SH|SZ|BJ)')"
    ).fetchone()[0]:
        raise ValueError("monthly_identity_unresolved")
    expected = dict(
        connection.execute(
            "SELECT i.latest_ts_code,max(d.trade_date) FROM monthly_daily d JOIN monthly_identity i ON d.ts_code=i.source_ts_code GROUP BY 1 ORDER BY 1"
        ).fetchall()
    )
    canonical = dict(
        connection.execute(
            "SELECT source_ts_code,CASE WHEN confidence='confirmed' THEN latest_ts_code END FROM monthly_identity ORDER BY 1"
        ).fetchall()
    )
    assert_month_references_unchanged(references)
    if upstream_bindings(days) != bindings:
        raise ValueError("monthly_upstream_events_changed")
    return {
        "month": month,
        "open_dates": list(days),
        "expected": expected,
        "canonical": canonical,
        "references": references,
        "daily_rows": daily_rows,
        "bindings": bindings,
    }


def verify_month_completion(connection, reference):
    """monthly_capture is the unmodified source mirror; join only for audit."""
    if (
        not reference["expected"]
        or len(reference["expected"]) > StockMonthlyPolicy().max_codes
        or len(reference["canonical"]) > StockMonthlyPolicy().max_codes
    ):
        raise ValueError("monthly_reference_invalid")
    connection.register(
        "monthly_expected",
        pd.DataFrame(
            list(reference["expected"].items()), columns=["code", "last_daily"]
        ),
    )
    connection.register(
        "monthly_canonical",
        pd.DataFrame(
            list(reference["canonical"].items()), columns=["raw_code", "code"]
        ),
    )
    count, invalid = connection.execute(
        "SELECT count(*),count(*) FILTER(WHERE i.code IS NULL OR NOT regexp_full_match(i.raw_code,'[0-9]{6}\\.(SH|SZ|BJ)') OR NOT regexp_full_match(i.code,'[0-9]{6}\\.(SH|SZ|BJ)') OR trade_date<>? OR freq<>'month' OR end_date IS NULL OR try_strptime(end_date,'%Y%m%d') IS NULL) FROM monthly_capture s LEFT JOIN monthly_canonical i ON s.ts_code=i.raw_code",
        [request_date_for_month(reference["month"])],
    ).fetchone()
    if not count or count > StockMonthlyPolicy().max_update_rows:
        raise ValueError("monthly_source_empty_or_over_budget")
    if invalid:
        raise ValueError("monthly_identity_or_source_cutoff_invalid")
    missing, stale = connection.execute(
        "SELECT count(*) FILTER(WHERE s.code IS NULL),count(*) FILTER(WHERE s.cutoff<e.last_daily) FROM monthly_expected e LEFT JOIN (SELECT i.code,max(s.end_date) cutoff FROM monthly_capture s JOIN monthly_canonical i ON s.ts_code=i.raw_code GROUP BY 1) s USING(code)"
    ).fetchone()
    if missing:
        raise ValueError("monthly_source_missing_keys")
    if stale:
        raise ValueError("monthly_source_not_ready")
    return {
        "expected_codes": len(reference["expected"]),
        "source_rows": count,
        "reason_code": "ready",
    }
