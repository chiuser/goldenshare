"""Whitelisted weekly Prod source: one bounded, rollback-only snapshot per unit."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from time import monotonic

import pandas as pd

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    CancelProbe,
    WeeklyCaptureError,
    check_weekly_cancel,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyUnit,
    StockWeeklySource,
    WeeklyBudget,
    normalize_weekly_code,
    stable_weekly_hash,
    weekly_column_specs,
    weekly_schema_hash,
)


def prod_weekly_table(source: StockWeeklySource) -> str:
    source = StockWeeklySource(source)
    if source is StockWeeklySource.PRIMARY_UNADJUSTED:
        return "raw_tushare.stk_period_bar"
    if source is StockWeeklySource.PRIMARY_ADJUSTED:
        return "raw_tushare.stk_period_bar_adj"
    raise WeeklyCaptureError("alternate_has_no_prod_bootstrap")


def build_prod_weekly_query(
    unit: ProdWeeklyUnit, budget: WeeklyBudget
) -> tuple[str, dict]:
    table = prod_weekly_table(unit.source)
    if (
        not unit.sorted_codes
        or len(unit.sorted_codes) > budget.prod_code_batch
        or unit.sorted_codes != tuple(sorted(set(unit.sorted_codes)))
        or unit.schema_hash != weekly_schema_hash(unit.source)
        or not 0 < unit.max_rows <= budget.max_source_rows_per_prod_unit
        or unit.source_date_start >= unit.source_date_end
    ):
        raise WeeklyCaptureError("prod_unit_invalid")
    for code in unit.sorted_codes:
        normalize_weekly_code(code)
    columns = []
    for name, kind, _ in weekly_column_specs(unit.source):
        if name in ("trade_date", "end_date"):
            columns.append(f"to_char({name}, 'YYYYMMDD') AS {name}")
        elif kind.startswith("DECIMAL"):
            columns.append(f'"{name}"::text AS "{name}"')
        else:
            columns.append(f'"{name}"')
    where = "ts_code = ANY(%(codes)s) AND freq = 'week' AND trade_date >= %(start)s AND trade_date < %(end)s"
    return (
        f"SELECT {','.join(columns)} FROM {table} WHERE {where} ORDER BY ts_code,trade_date,freq",
        {
            "codes": list(unit.sorted_codes),
            "start": unit.source_date_start,
            "end": unit.source_date_end,
        },
    )


@contextmanager
def _prod_watchdog(connection, cancel: CancelProbe, seconds: int) -> Iterator[None]:
    ended = threading.Event()
    interrupted = threading.Event()
    deadline = monotonic() + seconds

    def observe() -> None:
        while not ended.wait(0.1):
            if cancel() or monotonic() >= deadline:
                interrupted.set()
                connection.cancel()
                return

    thread = threading.Thread(target=observe, daemon=True)
    thread.start()
    try:
        yield
        check_weekly_cancel(cancel)
        if interrupted.is_set() or monotonic() >= deadline:
            raise WeeklyCaptureError("prod_unit_timeout")
    except Exception:
        if cancel():
            raise WeeklyCaptureError("canceled") from None
        if interrupted.is_set() or monotonic() >= deadline:
            raise WeeklyCaptureError("prod_unit_timeout") from None
        raise
    finally:
        ended.set()
        thread.join(timeout=1)
        if thread.is_alive():
            raise WeeklyCaptureError("prod_cancel_monitor_failed")


def iter_prod_weekly_batches(
    resource,
    unit: ProdWeeklyUnit,
    budget: WeeklyBudget,
    cancel: CancelProbe,
    evidence: dict,
    remaining_rows: int | None = None,
) -> Iterator[pd.DataFrame]:
    query, params = build_prod_weekly_query(unit, budget)
    check_weekly_cancel(cancel)
    with resource.connect_readonly_transaction() as connection:
        # Existing resource guarantees rollback. Isolation precedes the first SQL.
        connection.set_session(
            isolation_level="REPEATABLE READ", readonly=True, autocommit=False
        )
        with _prod_watchdog(connection, cancel, budget.prod_unit_seconds):
            with connection.cursor() as control:
                control.execute(
                    "SELECT set_config('statement_timeout', %s, true), set_config('work_mem', %s, true)",
                    [str(budget.prod_statement_timeout_ms), budget.prod_work_mem],
                )
                control.execute(
                    "SELECT txid_current_snapshot()::text, transaction_timestamp()::text"
                )
                snapshot, timestamp = control.fetchone()
                count_query = query.replace(
                    query.split(" FROM ")[0], "SELECT count(*)"
                ).split(" ORDER BY ")[0]
                control.execute(count_query, params)
                count = int(control.fetchone()[0])
                if count > unit.max_rows:
                    raise WeeklyCaptureError("unit_row_budget_exceeded")
                if remaining_rows is not None and count > remaining_rows:
                    raise WeeklyCaptureError("phase_row_budget_exceeded")
                evidence.update(
                    source_table=prod_weekly_table(unit.source),
                    source_rows=count,
                    snapshot=snapshot,
                    snapshot_at=timestamp,
                    params_hash=stable_weekly_hash(params),
                    unit_hash=stable_weekly_hash(asdict(unit)),
                )
            fields = [name for name, _, _ in weekly_column_specs(unit.source)]
            total = 0
            with connection.cursor(
                name=f"weekly_{stable_weekly_hash(asdict(unit))[:20]}"
            ) as cursor:
                cursor.itersize = budget.fetch_batch_rows
                cursor.execute(query, params)
                while True:
                    check_weekly_cancel(cancel)
                    rows = cursor.fetchmany(budget.fetch_batch_rows)
                    check_weekly_cancel(cancel)
                    if len(rows) > budget.fetch_batch_rows:
                        raise WeeklyCaptureError("chunk_row_budget_exceeded")
                    if not rows:
                        break
                    total += len(rows)
                    if total > unit.max_rows:
                        raise WeeklyCaptureError("unit_row_budget_exceeded")
                    yield pd.DataFrame(rows, columns=fields, dtype=object)
            if total != count:
                raise WeeklyCaptureError("source_count_changed")
            if total == 0:
                yield pd.DataFrame(columns=fields, dtype=object)
