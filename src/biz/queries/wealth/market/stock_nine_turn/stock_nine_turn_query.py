from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from src.foundation.models.core.equity_factor_pro import EquityFactorPro
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
    ) -> StockDailyNineTurnPage:
        conditions = [
            EquityFactorPro.ts_code == ts_code,
            EquityFactorPro.trade_date <= end_date,
        ]
        if start_date is not None:
            conditions.append(EquityFactorPro.trade_date >= start_date)
        if before_trade_date is not None:
            conditions.append(EquityFactorPro.trade_date < before_trade_date)
        join_condition = and_(
            EquityQfqNineTurnDaily.ts_code == EquityFactorPro.ts_code,
            EquityQfqNineTurnDaily.trade_date == EquityFactorPro.trade_date,
        )
        statement = (
            select(
                EquityFactorPro.ts_code.label("ts_code"),
                EquityFactorPro.trade_date.label("trade_date"),
                EquityQfqNineTurnDaily.up_count.label("up_count"),
                EquityQfqNineTurnDaily.down_count.label("down_count"),
                EquityQfqNineTurnDaily.nine_up_turn.label("nine_up_turn"),
                EquityQfqNineTurnDaily.nine_down_turn.label("nine_down_turn"),
                EquityQfqNineTurnDaily.formula_version.label("formula_version"),
            )
            .select_from(EquityFactorPro)
            .outerjoin(EquityQfqNineTurnDaily, join_condition)
            .where(*conditions)
            .order_by(desc(EquityFactorPro.trade_date))
            .limit(limit + 1)
        )
        raw_rows = [dict(row) for row in session.execute(statement).mappings().all()]
        has_more = len(raw_rows) > limit
        rows = raw_rows[:limit]
        rows.reverse()
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
