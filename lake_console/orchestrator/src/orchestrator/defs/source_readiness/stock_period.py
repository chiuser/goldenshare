"""Period source coverage and bounded local input reads; no writes or instance access."""

import json
import re
import tempfile
import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import silver_cny_stock_lifecycle_select
from orchestrator.defs.io.stock_period_raw import file_version
from orchestrator.defs.paths import (
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.stock_period import (
    DEFAULT_POLICY,
    STOCK_PERIOD_READINESS_FIELDS,
    admitted_code,
    period_date,
    period_for,
    request_params,
    source_period,
)
from orchestrator.defs.stock_trading_universe import stock_trading_universe_ctes


def period_input_days(root, business_date, freq, *, closed_period=False):
    day = date.fromisoformat(business_date)
    first = (
        (day - timedelta(days=day.weekday())) if freq == "week" else day.replace(day=1)
    )
    last_text = period_date(period_for(day, freq), freq)
    last = date.fromisoformat(f"{last_text[:4]}-{last_text[4:6]}-{last_text[6:]}")
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=Path(tempfile.gettempdir()).resolve()),
        temp_policy="existing_no_spill",
    ) as con:
        days = [
            r[0].isoformat()
            for r in con.execute(
                "SELECT trade_date FROM read_parquet(?,hive_partitioning=false) "
                "WHERE exchange='SSE' AND is_open AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
                [
                    str(silver_trade_calendar_path(root)),
                    first if closed_period else day,
                    last if closed_period else day,
                ],
            ).fetchall()
        ]
    if closed_period and (not days or days[-1] != business_date):
        raise ValueError("period_closed_intent_date_invalid")
    return days


def load_period_universe(root, business_date, freq, *, days=None):
    """Use date-effective lifecycle and FINAL suspension; never daily prices."""
    days = days if days is not None else [business_date]
    references = {
        "lifecycle": silver_stock_lifecycle_path(root),
        "identity": silver_stock_identity_map_path(root),
    }
    references.update(
        {"suspend:" + day: silver_stock_suspend_daily_path(root, day) for day in days}
    )
    versions = {key: file_version(path) for key, path in references.items()}
    required_dates, listed = {}, set()
    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=Path(tempfile.gettempdir()).resolve()),
        temp_policy="existing_no_spill",
    ) as con:
        for day in days:
            ctes = stock_trading_universe_ctes(
                trade_date=day,
                lifecycle_sql=silver_cny_stock_lifecycle_select(
                    references["lifecycle"]
                ),
                suspend_path=references["suspend:" + day],
            )
            for code, required in con.execute(
                f"WITH {ctes} SELECT ts_code,ts_code IN (SELECT ts_code FROM expected) FROM listed"
            ).fetchall():
                listed.add(code)
                if required:
                    required_dates[code] = day
        identities = con.execute(
            "SELECT source_ts_code,latest_ts_code FROM read_parquet(?,hive_partitioning=false) WHERE confidence='confirmed'",
            [str(references["identity"])],
        ).fetchall()
    aliases = dict(identities)
    aliases.update({latest: latest for _, latest in identities})
    for code in listed:
        admitted_code(code, listed, aliases)
    if any(file_version(path) != versions[key] for key, path in references.items()):
        raise ValueError("period_reference_changed")
    if not required_dates:
        raise ValueError("period_expected_universe_empty")
    return {
        "required": set(required_dates),
        "optional": listed - set(required_dates),
        "listed": listed,
        "aliases": aliases,
        "expected_dates": required_dates,
        "references": {key: str(path) for key, path in references.items()},
        "reference_versions": versions,
        "business_date": business_date,
        "freq": freq,
        "period": period_for(date.fromisoformat(business_date), freq),
    }


def check_period_rows(
    rows,
    *,
    freq,
    business_date,
    required_codes,
    optional_codes,
    aliases,
    expected_dates=None,
    maximum_asof=None,
):
    """Validate exact source keys and per-stock dates; only full-day suspensions may be absent."""
    period = period_for(date.fromisoformat(business_date), freq)
    label = period_date(period, freq)
    listed = set(required_codes) | set(optional_codes)
    dates, duplicates, excluded = {}, set(), 0
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise ValueError("period_readiness_width_invalid")
        code, trade_date, end_date = row
        if (
            not isinstance(code, str)
            or re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code) is None
        ):
            raise ValueError("period_source_identity_invalid")
        if trade_date != label:
            raise ValueError("period_source_period_label_mismatch")
        if code in aliases and aliases[code] != code and aliases[code] in listed:
            raise ValueError("period_source_retired_alias")
        if code not in listed:
            excluded += 1
            continue
        admitted_code(code, listed, aliases)
        source_period(end_date, freq)
        if end_date > (maximum_asof or business_date).replace("-", ""):
            raise ValueError("period_source_future_date")
        if code in dates:
            duplicates.add(code)
        dates[code] = end_date
    missing = set(required_codes) - dates.keys()
    stale = {
        code
        for code in set(required_codes) & dates.keys()
        if (
            dates[code] < expected_dates[code].replace("-", "")
            if expected_dates is not None
            else dates[code] != business_date.replace("-", "")
        )
    }
    ready = not missing and not stale and not duplicates
    return {
        "ready": ready,
        "reason": "ready" if ready else "period_source_incomplete",
        "business_date": business_date,
        "freq": freq,
        "period": period,
        "required_count": len(required_codes),
        "optional_count": len(optional_codes),
        "returned_required_count": len(set(required_codes) & dates.keys()),
        "returned_optional_count": len(set(optional_codes) & dates.keys()),
        "excluded_count": excluded,
        "missing_count": len(missing),
        "stale_count": len(stale),
        "duplicate_count": len(duplicates),
        "missing_sample": sorted(missing)[:20],
        "stale_sample": sorted(stale)[:20],
        "duplicate_sample": sorted(duplicates)[:20],
    }


def probe_stock_period_source(
    *,
    freq,
    business_date,
    required_codes,
    optional_codes,
    aliases,
    deadline,
    transport=None,
):
    from orchestrator.defs.stock_period_source import HttpPage

    policy = replace(DEFAULT_POLICY, retries=0)
    period = period_for(date.fromisoformat(business_date), freq)
    rows, seen, offset, total_bytes = [], set(), 0, 0
    try:
        if time.monotonic() >= deadline:
            raise TimeoutError("period_source_deadline")
        transport = transport or HttpPage(
            policy=policy, fields=STOCK_PERIOD_READINESS_FIELDS
        )
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("period_source_deadline")
            body = transport(
                request_params(freq=freq, period=period, offset=offset, policy=policy),
                deadline=deadline,
            )
            total_bytes += len(body)
            if len(body) > policy.response_bytes or total_bytes > policy.unit_bytes:
                raise ValueError("period_source_unit_budget_exceeded")
            data = json.loads(body)
            if data.get("code") != 0 or not isinstance(data.get("data"), dict):
                raise ValueError("period_source_api_error")
            data = data["data"]
            if data.get("fields") != list(STOCK_PERIOD_READINESS_FIELDS):
                raise ValueError("period_readiness_fields_invalid")
            items = data.get("items")
            if not isinstance(items, list) or len(items) > policy.page_limit:
                raise ValueError("period_source_page_invalid")
            for row in items:
                if not isinstance(row, list) or len(row) != 3:
                    raise ValueError("period_readiness_width_invalid")
                key = tuple(row)
                if key in seen:
                    raise ValueError("period_source_repeated_page")
                seen.add(key)
            rows.extend(items)
            if time.monotonic() >= deadline:
                raise TimeoutError("period_source_deadline")
            if len(items) < policy.page_limit:
                break
            offset += policy.page_limit
        return check_period_rows(
            rows,
            freq=freq,
            business_date=business_date,
            required_codes=required_codes,
            optional_codes=optional_codes,
            aliases=aliases,
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        ConnectionError,
        TimeoutError,
        EOFError,
    ) as error:
        return {
            "ready": False,
            "reason": str(error)
            if str(error).startswith("period_")
            else "period_source_unavailable",
            "business_date": business_date,
            "freq": freq,
            "period": period,
        }
