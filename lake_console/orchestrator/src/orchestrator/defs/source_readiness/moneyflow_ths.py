"""One-date THS source coverage; no jobs, files, events or retry loop are written."""

import re
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Timer
from time import perf_counter

import duckdb
from requests.exceptions import HTTPError

from orchestrator.defs.duckdb_connection import DEFAULT_DUCKDB_TEMP_DIRECTORY
from orchestrator.defs.duckdb_sql import silver_cny_stock_lifecycle_select
from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_connection
from orchestrator.defs.paths import (
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_ROWS_PER_ROUND,
    MONEYFLOW_PAGE_SIZE,
    MONEYFLOW_REQUEST_TIMEOUT_SECONDS,
    MoneyflowContractError,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    STOCK_THS_MONEYFLOW_AUTOMATION,
)
from orchestrator.defs.sensors.readiness import (
    SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY,
    SILVER_SUSPEND_D_CHECKS,
    AssetReadinessSpec,
    asset_readiness_status,
    silver_stock_lifecycle_ready_for_trade_date,
)
from orchestrator.defs.source_readiness.moneyflow_transport import call_moneyflow_source
from orchestrator.defs.stock_trading_universe import stock_trading_universe_ctes
from orchestrator.defs.tushare_errors import TushareResponseError
from orchestrator.defs.tushare_request_policy import classify_tushare_error

FIELDS = ("ts_code", "trade_date")


@dataclass(frozen=True)
class MoneyflowThsSourceReadiness:
    reason: str
    expected_count: int = 0
    source_count: int = 0
    missing_count: int | None = None

    @property
    def ready(self):
        return self.reason == "ready"


def check_moneyflow_ths_deadline(deadline, *, clock=perf_counter):
    if clock() >= deadline:
        raise MoneyflowContractError("source_precheck_deadline")


@contextmanager
def moneyflow_ths_connection(deadline, *, clock=perf_counter):
    check_moneyflow_ths_deadline(deadline, clock=clock)
    with moneyflow_candidate_connection(DEFAULT_DUCKDB_TEMP_DIRECTORY) as connection:
        check_moneyflow_ths_deadline(deadline, clock=clock)
        timer = Timer(deadline - clock(), connection.interrupt)
        timer.start()
        try:
            yield connection
            check_moneyflow_ths_deadline(deadline, clock=clock)
        finally:
            timer.cancel()
            timer.join()


def load_moneyflow_ths_universe(instance, root, trade_date, *, deadline, clock=perf_counter):
    check_moneyflow_ths_deadline(deadline, clock=clock)
    lifecycle = silver_stock_lifecycle_ready_for_trade_date(instance, trade_date)
    check_moneyflow_ths_deadline(deadline, clock=clock)
    if not lifecycle.ready:
        raise MoneyflowContractError("source_lifecycle_not_ready")
    suspension = asset_readiness_status(
        instance, AssetReadinessSpec(SILVER_STOCK_SUSPEND_DAILY_ASSET_KEY, SILVER_SUSPEND_D_CHECKS),
        partition_key=trade_date,
    )
    check_moneyflow_ths_deadline(deadline, clock=clock)
    if not suspension.ready:
        raise MoneyflowContractError("source_suspend_not_ready")
    ctes = stock_trading_universe_ctes(
        trade_date=trade_date,
        lifecycle_sql=silver_cny_stock_lifecycle_select(silver_stock_lifecycle_path(root)),
        suspend_path=silver_stock_suspend_daily_path(root, trade_date),
        listed_filter="ends_with(ts_code, '.SH') OR ends_with(ts_code, '.SZ')",
    )
    with moneyflow_ths_connection(deadline, clock=clock) as connection:
        rows = connection.execute(
            f"WITH {ctes} SELECT ts_code, false FROM expected "
            "UNION ALL SELECT ts_code, true FROM full_day_suspended"
        ).fetchall()
    expected = frozenset(code for code, suspended in rows if not suspended)
    full_day_suspended = frozenset(code for code, suspended in rows if suspended)
    if not expected:
        raise MoneyflowContractError("source_expected_empty")
    return expected, full_day_suspended


def check_moneyflow_ths_source_ready(context, trade_date, *, deadline, clock=perf_counter):
    try:
        expected, suspended = load_moneyflow_ths_universe(
            context.instance, context.resources.lake_root.root(), trade_date,
            deadline=deadline, clock=clock,
        )
    except MoneyflowContractError as error:
        return MoneyflowThsSourceReadiness(str(error))
    except (duckdb.Error, OSError):
        return MoneyflowThsSourceReadiness("source_universe_unavailable")

    seen = set()
    source_deadline = min(deadline, clock() + MONEYFLOW_REQUEST_TIMEOUT_SECONDS)
    try:
        for offset in range(0, MONEYFLOW_MAX_ROWS_PER_ROUND + MONEYFLOW_PAGE_SIZE, MONEYFLOW_PAGE_SIZE):
            check_moneyflow_ths_deadline(source_deadline, clock=clock)
            response = call_moneyflow_source(
                context.resources.tushare, "moneyflow_ths",
                {"trade_date": trade_date.replace("-", ""), "limit": MONEYFLOW_PAGE_SIZE, "offset": offset},
                FIELDS, deadline=source_deadline,
                check_cancel=lambda: check_moneyflow_ths_deadline(source_deadline, clock=clock),
            )
            check_moneyflow_ths_deadline(source_deadline, clock=clock)
            if tuple(response.columns) != FIELDS:
                raise MoneyflowContractError("source_schema")
            if len(response.rows) > MONEYFLOW_PAGE_SIZE:
                raise MoneyflowContractError("source_page_size")
            for row in response.rows:
                if (
                    set(row) != set(FIELDS)
                    or type(row["ts_code"]) is not str
                    or re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", row["ts_code"]) is None
                    or row["trade_date"] != trade_date.replace("-", "")
                ):
                    raise MoneyflowContractError("source_partition_or_key")
                code = row["ts_code"]
                if code in seen:
                    raise MoneyflowContractError("source_duplicate_key")
                seen.add(code)
            if len(seen) > MONEYFLOW_MAX_ROWS_PER_ROUND:
                raise MoneyflowContractError("source_row_budget")
            if len(response.rows) < MONEYFLOW_PAGE_SIZE:
                break
        if not seen:
            raise MoneyflowContractError("source_empty")
        if seen - expected - suspended:
            raise MoneyflowContractError("source_extra_codes")
        missing = len(expected - seen)
        check_moneyflow_ths_deadline(source_deadline, clock=clock)
        return MoneyflowThsSourceReadiness(
            "ready" if missing < STOCK_THS_MONEYFLOW_AUTOMATION.missing_record_limit else "source_missing_codes",
            len(expected), len(seen), missing,
        )
    except MoneyflowContractError as error:
        return MoneyflowThsSourceReadiness(str(error), len(expected), len(seen))
    except (ValueError, HTTPError, TushareResponseError) as error:
        return MoneyflowThsSourceReadiness(classify_tushare_error(error)[0], len(expected), len(seen))
