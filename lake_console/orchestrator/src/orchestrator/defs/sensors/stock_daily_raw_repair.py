from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from orchestrator.defs.duckdb_sql import (
    BJ_MARKET_OPEN_DATE,
    STOCK_DAILY_MIN_TRADE_DATE,
    current_cny_stock_basic_select,
    duckdb_string,
    read_parquet,
    stock_daily_normalized_select,
)
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    silver_stock_basic_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.configs import (
    MAX_STOCK_DAILY_MISSING_CODE_REPAIR_COUNT,
)


MAX_STOCK_DAILY_REPAIR_ATTEMPTS = 20
STOCK_DAILY_REPAIR_RETRY_MINUTES = 10
MAX_STOCK_DAILY_REPAIR_SAMPLE_CODES = 20
STOCK_DAILY_REPAIR_STATE_KEY = "stock_daily_missing_code_repair"


@dataclass(frozen=True)
class StockDailyMissingCodeLocatorResult:
    trade_date: str
    raw_file_exists: bool
    expected_count: int = 0
    raw_code_count: int = 0
    missing_codes: tuple[str, ...] = ()
    extra_count: int = 0
    duplicate_key_count: int = 0
    conflict_key_count: int = 0
    extra_sample_codes: tuple[str, ...] = ()
    duplicate_sample_codes: tuple[str, ...] = ()
    conflict_sample_codes: tuple[str, ...] = ()
    scan_error_code: str | None = None
    scan_error: str | None = None

    @property
    def missing_count(self) -> int:
        return len(self.missing_codes)

    @property
    def missing_sample_codes(self) -> tuple[str, ...]:
        return self.missing_codes[:MAX_STOCK_DAILY_REPAIR_SAMPLE_CODES]


@dataclass(frozen=True)
class StockDailyMissingCodeRepairSelection:
    should_submit: bool
    trade_date: str
    reason: str
    repair_state: dict[str, Any]
    missing_codes_hash: str | None = None
    repair_attempt: int = 0
    next_retry_at: datetime | None = None
    manual_required: bool = False
    waiting: bool = False
    exhausted: bool = False


def locate_stock_daily_missing_codes(
    *,
    lake_root_path: Path,
    duckdb: DuckDBResource,
    trade_date: str,
    sample_limit: int = MAX_STOCK_DAILY_REPAIR_SAMPLE_CODES,
) -> StockDailyMissingCodeLocatorResult:
    raw_path = raw_stock_daily_path(lake_root_path, trade_date)
    if not raw_path.exists():
        return StockDailyMissingCodeLocatorResult(
            trade_date=trade_date,
            raw_file_exists=False,
        )

    basic_path = silver_stock_basic_path(lake_root_path)
    suspend_path = silver_stock_suspend_daily_path(lake_root_path, trade_date)
    missing_support_paths = [
        str(path) for path in (basic_path, suspend_path) if not path.exists()
    ]
    if missing_support_paths:
        return StockDailyMissingCodeLocatorResult(
            trade_date=trade_date,
            raw_file_exists=True,
            scan_error_code="missing_support_file",
            scan_error=f"Missing support files for stock_daily repair: {missing_support_paths}",
        )

    try:
        duckdb_resource = duckdb
        with duckdb_resource.connect() as connection:
            row = connection.execute(
                _locator_query(
                    trade_date=trade_date,
                    raw_path=raw_path,
                    basic_path=basic_path,
                    suspend_path=suspend_path,
                    sample_limit=sample_limit,
                )
            ).fetchone()
    except Exception as error:
        return StockDailyMissingCodeLocatorResult(
            trade_date=trade_date,
            raw_file_exists=True,
            scan_error_code="duckdb_scan_error",
            scan_error=str(error),
        )

    return StockDailyMissingCodeLocatorResult(
        trade_date=trade_date,
        raw_file_exists=True,
        expected_count=int(row[0]),
        raw_code_count=int(row[1]),
        missing_codes=tuple(row[2] or ()),
        extra_count=int(row[3]),
        duplicate_key_count=int(row[4]),
        conflict_key_count=int(row[5]),
        extra_sample_codes=tuple(row[6] or ()),
        duplicate_sample_codes=tuple(row[7] or ()),
        conflict_sample_codes=tuple(row[8] or ()),
    )


def stock_daily_missing_codes_hash(missing_codes: tuple[str, ...]) -> str:
    payload = "\n".join(sorted(missing_codes)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stock_daily_repair_state_from_details(
    details: Mapping[str, Any],
) -> dict[str, Any]:
    raw_state = details.get(STOCK_DAILY_REPAIR_STATE_KEY)
    if not isinstance(raw_state, Mapping):
        return {"dates": {}}
    dates = raw_state.get("dates")
    if not isinstance(dates, Mapping):
        return {"dates": {}}
    return {"dates": {str(key): dict(value) for key, value in dates.items() if isinstance(value, Mapping)}}


def select_stock_daily_missing_code_repair(
    *,
    locator: StockDailyMissingCodeLocatorResult,
    evaluated_at: datetime,
    repair_state: Mapping[str, Any],
    max_attempts: int = MAX_STOCK_DAILY_REPAIR_ATTEMPTS,
) -> StockDailyMissingCodeRepairSelection:
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive.")

    next_state = _copy_repair_state(repair_state)
    trade_date = locator.trade_date

    if not locator.raw_file_exists:
        _clear_trade_date_state(next_state, trade_date)
        return StockDailyMissingCodeRepairSelection(
            should_submit=False,
            trade_date=trade_date,
            reason="raw_file_missing_full_day_required",
            repair_state=next_state,
        )
    if locator.scan_error is not None:
        _set_manual_state(
            next_state,
            trade_date=trade_date,
            reason=locator.scan_error_code or "scan_error",
            missing_codes_hash=None,
            sample_codes=(),
        )
        return StockDailyMissingCodeRepairSelection(
            should_submit=False,
            trade_date=trade_date,
            reason=locator.scan_error_code or "scan_error",
            repair_state=next_state,
            manual_required=True,
        )
    if locator.missing_count == 0:
        _clear_trade_date_state(next_state, trade_date)
        return StockDailyMissingCodeRepairSelection(
            should_submit=False,
            trade_date=trade_date,
            reason="no_missing_codes",
            repair_state=next_state,
        )

    missing_hash = stock_daily_missing_codes_hash(locator.missing_codes)
    if locator.missing_count > MAX_STOCK_DAILY_MISSING_CODE_REPAIR_COUNT:
        _set_manual_state(
            next_state,
            trade_date=trade_date,
            reason="missing_count_exceeds_limit",
            missing_codes_hash=missing_hash,
            sample_codes=locator.missing_sample_codes,
        )
        return StockDailyMissingCodeRepairSelection(
            should_submit=False,
            trade_date=trade_date,
            reason="missing_count_exceeds_limit",
            repair_state=next_state,
            missing_codes_hash=missing_hash,
            manual_required=True,
        )
    if locator.extra_count:
        return _manual_selection(
            next_state,
            locator=locator,
            missing_hash=missing_hash,
            reason="extra_codes_present",
        )
    if locator.duplicate_key_count:
        return _manual_selection(
            next_state,
            locator=locator,
            missing_hash=missing_hash,
            reason="duplicate_keys_present",
        )
    if locator.conflict_key_count:
        return _manual_selection(
            next_state,
            locator=locator,
            missing_hash=missing_hash,
            reason="conflicting_duplicates_present",
        )

    date_state = _date_state(next_state, trade_date)
    previous_hash = date_state.get("missing_codes_hash")
    attempt_count = _state_attempt_count(date_state) if previous_hash == missing_hash else 0
    if attempt_count >= max_attempts:
        _set_manual_state(
            next_state,
            trade_date=trade_date,
            reason="repair_attempts_exhausted",
            missing_codes_hash=missing_hash,
            sample_codes=locator.missing_sample_codes,
            attempt_count=attempt_count,
        )
        return StockDailyMissingCodeRepairSelection(
            should_submit=False,
            trade_date=trade_date,
            reason="repair_attempts_exhausted",
            repair_state=next_state,
            missing_codes_hash=missing_hash,
            repair_attempt=attempt_count,
            manual_required=True,
            exhausted=True,
        )

    next_retry_at = (
        _parse_datetime(date_state.get("next_retry_at"))
        if previous_hash == missing_hash
        else None
    )
    if next_retry_at is not None and next_retry_at > evaluated_at:
        return StockDailyMissingCodeRepairSelection(
            should_submit=False,
            trade_date=trade_date,
            reason="repair_retry_waiting",
            repair_state=next_state,
            missing_codes_hash=missing_hash,
            repair_attempt=attempt_count,
            next_retry_at=next_retry_at,
            waiting=True,
        )

    repair_attempt = attempt_count + 1
    new_next_retry_at = evaluated_at + timedelta(minutes=STOCK_DAILY_REPAIR_RETRY_MINUTES)
    _set_date_state(
        next_state,
        trade_date,
        {
            "missing_codes_hash": missing_hash,
            "attempt_count": repair_attempt,
            "next_retry_at": new_next_retry_at.isoformat(),
            "last_launched_at": evaluated_at.isoformat(),
            "manual_required": False,
            "sample_missing_codes": list(locator.missing_sample_codes),
        },
    )
    return StockDailyMissingCodeRepairSelection(
        should_submit=True,
        trade_date=trade_date,
        reason="repair_due",
        repair_state=next_state,
        missing_codes_hash=missing_hash,
        repair_attempt=repair_attempt,
        next_retry_at=new_next_retry_at,
    )


def _locator_query(
    *,
    trade_date: str,
    raw_path: Path,
    basic_path: Path,
    suspend_path: Path,
    sample_limit: int,
) -> str:
    partition_date_sql = f"CAST({duckdb_string(trade_date)} AS DATE)"
    compact_trade_date_sql = duckdb_string(trade_date.replace("-", ""))
    normalized_sql = stock_daily_normalized_select(raw_path)
    return f"""
    WITH listed AS (
      SELECT DISTINCT ts_code
      FROM ({current_cny_stock_basic_select(basic_path)}) stock_basic
      WHERE {partition_date_sql} >= DATE '{STOCK_DAILY_MIN_TRADE_DATE}'
        AND list_date <= {partition_date_sql}
        AND (
          NOT ends_with(ts_code, '.BJ')
          OR {partition_date_sql} >= DATE '{BJ_MARKET_OPEN_DATE}'
        )
    ),
    full_day_suspended AS (
      SELECT DISTINCT suspend.ts_code
      FROM {read_parquet(suspend_path, hive_partitioning=False)} suspend
      INNER JOIN listed USING (ts_code)
      WHERE suspend.trade_date = {partition_date_sql}
        AND suspend.suspend_type = 'S'
        AND suspend.suspend_timing IS NULL
    ),
    expected AS (
      SELECT ts_code
      FROM listed
      EXCEPT
      SELECT ts_code
      FROM full_day_suspended
    ),
    daily AS (
      SELECT DISTINCT ts_code
      FROM {read_parquet(raw_path, hive_partitioning=False)}
      WHERE CAST(trade_date AS VARCHAR) = {compact_trade_date_sql}
    ),
    missing AS (
      SELECT expected.ts_code
      FROM expected
      LEFT JOIN daily USING (ts_code)
      WHERE daily.ts_code IS NULL
    ),
    extra AS (
      SELECT daily.ts_code
      FROM daily
      LEFT JOIN expected USING (ts_code)
      WHERE expected.ts_code IS NULL
    ),
    duplicate_keys AS (
      SELECT ts_code, trade_date, count(*) AS duplicate_row_count
      FROM {read_parquet(raw_path, hive_partitioning=False)}
      WHERE CAST(trade_date AS VARCHAR) = {compact_trade_date_sql}
      GROUP BY ts_code, trade_date
      HAVING count(*) > 1
    ),
    normalized_distinct AS (
      SELECT DISTINCT *
      FROM ({normalized_sql}) normalized
    ),
    conflict_keys AS (
      SELECT ts_code, trade_date, count(*) AS version_count
      FROM normalized_distinct
      WHERE trade_date = {partition_date_sql}
      GROUP BY ts_code, trade_date
      HAVING count(*) > 1
    )
    SELECT
      (SELECT count(*) FROM expected) AS expected_count,
      (SELECT count(*) FROM daily) AS raw_code_count,
      (SELECT list(ts_code ORDER BY ts_code) FROM missing) AS missing_codes,
      (SELECT count(*) FROM extra) AS extra_count,
      (SELECT count(*) FROM duplicate_keys) AS duplicate_key_count,
      (SELECT count(*) FROM conflict_keys) AS conflict_key_count,
      (
        SELECT list(ts_code ORDER BY ts_code)
        FROM (SELECT ts_code FROM extra ORDER BY ts_code LIMIT {sample_limit}) sample
      ) AS extra_sample_codes,
      (
        SELECT list(ts_code ORDER BY ts_code)
        FROM (SELECT ts_code FROM duplicate_keys ORDER BY ts_code LIMIT {sample_limit}) sample
      ) AS duplicate_sample_codes,
      (
        SELECT list(ts_code ORDER BY ts_code)
        FROM (SELECT ts_code FROM conflict_keys ORDER BY ts_code LIMIT {sample_limit}) sample
      ) AS conflict_sample_codes
    """


def _manual_selection(
    repair_state: dict[str, Any],
    *,
    locator: StockDailyMissingCodeLocatorResult,
    missing_hash: str,
    reason: str,
) -> StockDailyMissingCodeRepairSelection:
    _set_manual_state(
        repair_state,
        trade_date=locator.trade_date,
        reason=reason,
        missing_codes_hash=missing_hash,
        sample_codes=locator.missing_sample_codes,
    )
    return StockDailyMissingCodeRepairSelection(
        should_submit=False,
        trade_date=locator.trade_date,
        reason=reason,
        repair_state=repair_state,
        missing_codes_hash=missing_hash,
        manual_required=True,
    )


def _copy_repair_state(repair_state: Mapping[str, Any]) -> dict[str, Any]:
    dates = repair_state.get("dates") if isinstance(repair_state, Mapping) else None
    if not isinstance(dates, Mapping):
        return {"dates": {}}
    return {
        "dates": {
            str(trade_date): dict(state)
            for trade_date, state in dates.items()
            if isinstance(state, Mapping)
        }
    }


def _date_state(repair_state: Mapping[str, Any], trade_date: str) -> dict[str, Any]:
    dates = repair_state.get("dates")
    if not isinstance(dates, Mapping):
        return {}
    state = dates.get(trade_date)
    return dict(state) if isinstance(state, Mapping) else {}


def _set_date_state(
    repair_state: dict[str, Any], trade_date: str, state: dict[str, Any]
) -> None:
    dates = repair_state.setdefault("dates", {})
    if isinstance(dates, dict):
        dates[trade_date] = state


def _clear_trade_date_state(repair_state: dict[str, Any], trade_date: str) -> None:
    dates = repair_state.setdefault("dates", {})
    if isinstance(dates, dict):
        dates.pop(trade_date, None)


def _set_manual_state(
    repair_state: dict[str, Any],
    *,
    trade_date: str,
    reason: str,
    missing_codes_hash: str | None,
    sample_codes: tuple[str, ...],
    attempt_count: int = 0,
) -> None:
    _set_date_state(
        repair_state,
        trade_date,
        {
            "missing_codes_hash": missing_codes_hash,
            "attempt_count": attempt_count,
            "next_retry_at": None,
            "manual_required": True,
            "manual_reason": reason,
            "sample_missing_codes": list(sample_codes),
        },
    )


def _state_attempt_count(state: Mapping[str, Any]) -> int:
    try:
        value = int(state.get("attempt_count", 0))
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
