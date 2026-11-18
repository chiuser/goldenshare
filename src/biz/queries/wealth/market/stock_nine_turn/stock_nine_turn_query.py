from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.stock_detail.stock_detail_query import stock_daily_dates
from src.foundation.models.core_serving.equity_qfq_nineturn_daily import (
    EquityQfqNineTurnDaily,
)


@dataclass(frozen=True, slots=True)
class StockDailyNineTurnPage:
    rows: tuple[dict[str, Any], ...]
    has_more: bool
    observed_start_date: date | None
    observed_end_date: date | None


class StockNineTurnQuery:
    def load_daily_page(
        self,
        session: Session,
        *,
        ts_code: str,
        start_date: date | None,
        end_date: date,
        before_trade_date: date | None,
        limit: int,
        load_dates=None,
    ) -> StockDailyNineTurnPage:
        result_fields = (
            EquityQfqNineTurnDaily.up_count,
            EquityQfqNineTurnDaily.down_count,
            EquityQfqNineTurnDaily.nine_up_turn,
            EquityQfqNineTurnDaily.nine_down_turn,
            EquityQfqNineTurnDaily.formula_version,
        )
        if load_dates is None:
            dates = stock_daily_dates(ts_code, start=start_date, end=end_date, before=before_trade_date,
                                      limit=limit + 1).cte("page_dates")
            page = select(dates.c.trade_date).order_by(dates.c.trade_date.desc()).limit(limit).cte("page")
            statement = (select(page.c.trade_date, *result_fields,
                                select(dates.c.trade_date).offset(limit).exists().label("has_more"))
                         .select_from(page)
                         .outerjoin(EquityQfqNineTurnDaily, and_(
                             EquityQfqNineTurnDaily.ts_code == ts_code,
                             EquityQfqNineTurnDaily.trade_date == page.c.trade_date,
                         )).order_by(page.c.trade_date))
            rows = [dict(row) for row in session.execute(statement).mappings()]
            has_more = bool(rows and rows[0]["has_more"])
        else:
            candidates = load_dates(ts_code, start=start_date, end=end_date, before=before_trade_date,
                                    limit=limit + 1)
            has_more = len(candidates) > limit
            page_dates = candidates[-limit:]
            result_by_date = {}
            if page_dates:
                result_by_date = {row["trade_date"]: dict(row) for row in session.execute(
                    select(EquityQfqNineTurnDaily.trade_date, *result_fields)
                    .where(EquityQfqNineTurnDaily.ts_code == ts_code,
                           EquityQfqNineTurnDaily.trade_date.in_(page_dates)),
                ).mappings()}
            rows = [result_by_date.get(day, {"trade_date": day, "formula_version": None})
                    for day in page_dates]
        for row in rows:
            row["nine_turn_matched"] = row["formula_version"] is not None
        observed_dates = [
            row["trade_date"] for row in rows if row["nine_turn_matched"]
        ]
        return StockDailyNineTurnPage(
            rows=tuple(rows),
            has_more=has_more,
            observed_start_date=min(observed_dates) if observed_dates else None,
            observed_end_date=max(observed_dates) if observed_dates else None,
        )
