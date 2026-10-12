"""Bounded first-bootstrap value reconciliation; never a daily history gate."""

from sqlalchemy import select

from src.foundation.datasets.stock_weekly_adj_contracts import (
    SOURCE_FIELDS,
    WeeklyAdjContractError,
    canonical_source_rows,
    digest,
)
from src.foundation.models.core_serving.stk_period_bar_adj import (
    StkPeriodBarAdj as Serving,
)
from src.foundation.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj as Raw


def scope_rows(session, model, filters, policy):
    rows = [
        dict(r)
        for r in session.execute(
            select(
                *(
                    getattr(
                        model,
                        "change_amount" if model is Serving and n == "change" else n,
                    ).label(n)
                    for n in SOURCE_FIELDS
                )
            )
            .where(*filters)
            .limit(policy.max_rows_per_unit + 1)
        ).mappings()
    ]
    if len(rows) > policy.max_rows_per_unit:
        raise WeeklyAdjContractError(
            "首次对账单元超过行数预算", "weekly_adj.row_budget_exceeded"
        )
    return canonical_source_rows(rows, policy)


def key(row):
    return row["ts_code"], row["trade_date"]


def preservation_summary(session, filters_by_model, input_keys, policy, check):
    """Only hashes and bounded keys survive the original unit transaction."""
    result = {}
    for name, model in (("raw", Raw), ("serving", Serving)):
        check()
        retained = [
            r
            for r in scope_rows(session, model, filters_by_model[model], policy)
            if key(r) not in input_keys
        ]
        result[name] = {
            "rows": len(retained),
            "rows_digest": digest(retained),
            "keys": [list(key(r)) for r in retained],
        }
        check()
    return result


def reconcile_scope(session, filters_by_model, summary, policy, check):
    preserved = summary["preserved_values"]
    for name, model in (("raw", Raw), ("serving", Serving)):
        check()
        rows = scope_rows(session, model, filters_by_model[model], policy)
        keys = {tuple(k) for k in preserved[name]["keys"]}
        retained = [r for r in rows if key(r) in keys]
        selected = [r for r in rows if key(r) not in keys]
        if (
            len(retained) != preserved[name]["rows"]
            or digest(retained) != preserved[name]["rows_digest"]
            or len(selected) != summary["rows"]
            or digest(selected) != summary["rows_digest"]
        ):
            raise WeeklyAdjContractError(
                "首次搬运对账不一致，当前单元未通过",
                "weekly_adj.delivery_contract_mismatch",
            )
        check()
