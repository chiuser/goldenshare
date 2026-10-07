"""Bounded Prod moneyflow history planning; no database or filesystem execution."""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA,
    SILVER_MONEYFLOW_MKT_DC_SCHEMA,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_MAX_DATE_FACTS,
    MONEYFLOW_HISTORY_MAX_DATES_PER_WINDOW,
    MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT,
    MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
    MoneyflowContractError,
    market_moneyflow_day,
)
from orchestrator.defs.run_contracts.moneyflow_daily import (
    daily_key_fields,
    daily_schema,
)


@dataclass(frozen=True)
class MoneyflowHistoryDateCount:
    trade_date: str
    row_count: int
    distinct_business_keys: int


@dataclass(frozen=True)
class MoneyflowHistoryWindow:
    window_id: int
    dates: tuple[str, ...]
    row_count: int


@dataclass(frozen=True)
class MoneyflowHistorySourceUnit:
    unit_id: int
    row_count: int
    dates: tuple[str, ...]
    # Empty dates mean keyset over the entire frozen range, not an empty export.


@dataclass(frozen=True)
class MoneyflowHistoryPlan:
    dataset: str
    cutoff: str
    date_counts: tuple[MoneyflowHistoryDateCount, ...]
    windows: tuple[MoneyflowHistoryWindow, ...]
    source_units: tuple[MoneyflowHistorySourceUnit, ...]
    schema_hash: str
    source_counts_hash: str
    plan_hash: str

    @property
    def row_count(self) -> int:
        return sum(fact.row_count for fact in self.date_counts)

    @property
    def formal_file_count(self) -> int:
        return 2 * len(self.date_counts)


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def history_schema(dataset: str, *, silver=False):
    if dataset == "moneyflow_mkt_dc":
        return (
            SILVER_MONEYFLOW_MKT_DC_SCHEMA
            if silver
            else RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA
        )
    return daily_schema(dataset, silver=silver)


def history_source_key_fields(dataset: str) -> tuple[str, ...]:
    history_schema(dataset)
    if dataset == "moneyflow":
        return ("ts_code", "trade_date")
    if dataset == "moneyflow_mkt_dc":
        return ("trade_date",)
    return daily_key_fields(dataset)


def build_moneyflow_history_plan(
    dataset: str,
    date_counts: Iterable[MoneyflowHistoryDateCount],
    *,
    cutoff: str,
) -> MoneyflowHistoryPlan:
    """Freeze count-based scope, never invent keyset boundaries or fill source gaps."""
    raw = history_schema(dataset)
    silver = history_schema(dataset, silver=True)
    market_moneyflow_day(cutoff)
    facts = []
    for fact in date_counts:
        if len(facts) >= MONEYFLOW_HISTORY_MAX_DATE_FACTS:
            raise MoneyflowContractError("history_date_fact_budget")
        if not isinstance(fact, MoneyflowHistoryDateCount):
            raise MoneyflowContractError("history_date_fact")
        market_moneyflow_day(fact.trade_date)
        if fact.trade_date > cutoff:
            raise MoneyflowContractError("history_cutoff")
        if (
            type(fact.row_count) is not int
            or type(fact.distinct_business_keys) is not int
            or not 0 < fact.row_count <= MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT
            or fact.distinct_business_keys != fact.row_count
        ):
            raise MoneyflowContractError("history_count_or_keys")
        if dataset == "moneyflow_mkt_dc" and fact.row_count != 1:
            raise MoneyflowContractError("history_market_count")
        facts.append(fact)
    facts.sort(key=lambda fact: fact.trade_date)
    if not facts or len({fact.trade_date for fact in facts}) != len(facts):
        raise MoneyflowContractError("history_dates_empty_or_duplicate")
    windows = []
    dates = []
    rows = 0
    for fact in facts:
        if dates and (
            len(dates) == MONEYFLOW_HISTORY_MAX_DATES_PER_WINDOW
            or rows + fact.row_count > MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT
            or dates[0][:4] != fact.trade_date[:4]
        ):
            windows.append(MoneyflowHistoryWindow(len(windows), tuple(dates), rows))
            dates, rows = [], 0
        dates.append(fact.trade_date)
        rows += fact.row_count
    windows.append(MoneyflowHistoryWindow(len(windows), tuple(dates), rows))
    total = sum(fact.row_count for fact in facts)
    if dataset == "moneyflow":
        units = tuple(
            MoneyflowHistorySourceUnit(
                index, min(MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT, total - start), ()
            )
            for index, start in enumerate(
                range(0, total, MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT)
            )
        )
    else:
        units = tuple(
            MoneyflowHistorySourceUnit(w.window_id, w.row_count, w.dates)
            for w in windows
        )
    schema_hash = _hash(
        {
            "raw": [(c.name, c.type) for c in raw],
            "silver": [(c.name, c.type) for c in silver],
            "source_keys": history_source_key_fields(dataset),
        }
    )
    source_counts_hash = _hash([asdict(fact) for fact in facts])
    payload = {
        "dataset": dataset,
        "cutoff": cutoff,
        "date_counts": tuple(facts),
        "windows": tuple(windows),
        "source_units": units,
        "schema_hash": schema_hash,
        "source_counts_hash": source_counts_hash,
    }
    draft = MoneyflowHistoryPlan(**payload, plan_hash="")
    plan_hash = _hash(
        {
            "contract": "prod_moneyflow_history_plan_v1",
            "plan": asdict(draft),
            "budget": {
                "rows": MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT,
                "dates": MONEYFLOW_HISTORY_MAX_DATES_PER_WINDOW,
                "facts": MONEYFLOW_HISTORY_MAX_DATE_FACTS,
                "sql_seconds": MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
            },
        }
    )
    return MoneyflowHistoryPlan(**payload, plan_hash=plan_hash)


def validate_moneyflow_history_plan(plan: MoneyflowHistoryPlan) -> None:
    if not isinstance(plan, MoneyflowHistoryPlan):
        raise MoneyflowContractError("history_plan_type")
    rebuilt = build_moneyflow_history_plan(
        plan.dataset, plan.date_counts, cutoff=plan.cutoff
    )
    if rebuilt != plan:
        raise MoneyflowContractError("history_plan_changed")


def _key(plan: MoneyflowHistoryPlan, value) -> tuple[str, str]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise MoneyflowContractError("history_keyset_boundary")
    code, day = value
    if (
        not isinstance(code, str)
        or not code
        or len(code) > 64
        or any(ord(char) < 32 for char in code)
    ):
        raise MoneyflowContractError("history_keyset_boundary")
    market_moneyflow_day(day)
    if not plan.date_counts[0].trade_date <= day <= plan.date_counts[-1].trade_date:
        raise MoneyflowContractError("history_keyset_date")
    return code, day


def _literal(value: str) -> str:
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def moneyflow_history_export_sql(
    plan: MoneyflowHistoryPlan,
    unit_id: int,
    *,
    after_key: tuple[str, str] | None = None,
    through_key: tuple[str, str] | None = None,
) -> str:
    """Generate one read-only COPY. Boundaries must later be proven by CSV/checkpoint.

    through_key closes a completed keyset unit for independent source verification.
    This builder neither runs SQL nor asserts that a plan is approved for APPLY.
    """
    validate_moneyflow_history_plan(plan)
    if type(unit_id) is not int or not 0 <= unit_id < len(plan.source_units):
        raise MoneyflowContractError("history_source_unit")
    unit = plan.source_units[unit_id]
    if plan.dataset != "moneyflow" and (
        after_key is not None or through_key is not None
    ):
        raise MoneyflowContractError("history_unexpected_keyset")
    if plan.dataset == "moneyflow" and (unit_id == 0) != (after_key is None):
        raise MoneyflowContractError("history_keyset_continuation")
    predicates = []
    if unit.dates:
        predicates.append(
            'source."trade_date" IN ('
            + ",".join(f"DATE '{day}'" for day in unit.dates)
            + ")"
        )
    else:
        predicates.append(
            f"source.\"trade_date\" BETWEEN DATE '{plan.date_counts[0].trade_date}' AND DATE '{plan.date_counts[-1].trade_date}'"
        )
        after = _key(plan, after_key) if after_key is not None else None
        through = _key(plan, through_key) if through_key is not None else None
        if after and through and through <= after:
            raise MoneyflowContractError("history_keyset_order")
        for operator, boundary in ((">", after), ("<=", through)):
            if boundary:
                predicates.append(
                    f'(source."ts_code", source."trade_date") {operator} ({_literal(boundary[0])}, DATE \'{boundary[1]}\')'
                )
    # Explicit DATE formatting makes CSV independent of the server DateStyle.
    projection = ", ".join(
        'to_char(source."trade_date", \'YYYY-MM-DD\') AS "trade_date"'
        if c.name == "trade_date"
        else f'source."{c.name}"'
        for c in history_schema(plan.dataset)
    )
    order = ", ".join(
        f'source."{name}"' for name in history_source_key_fields(plan.dataset)
    )
    return (
        "BEGIN READ ONLY;\n"
        f"SET LOCAL statement_timeout = '{MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS}s';\n"
        f"COPY (SELECT {projection} FROM raw_tushare.{plan.dataset} AS source "
        f"WHERE {' AND '.join(predicates)} ORDER BY {order} "
        f"LIMIT {MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT}) "
        "TO STDOUT WITH (FORMAT CSV, HEADER TRUE, NULL E'\\\\N', ENCODING 'UTF8');\n"
        "ROLLBACK;\n"
    )
