from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.core_serving.index_nineturn_daily import IndexNineTurnDaily


@dataclass(frozen=True, slots=True)
class IndexDailyNineTurnPage:
    rows: tuple[dict[str, Any], ...]
    has_more: bool
    observed_start_date: date | None
    observed_end_date: date | None


class IndexNineTurnQuery:
    def load_daily_page(
        self,
        session: Session,
        *,
        ts_code: str,
        start_date: date | None,
        end_date: date,
        before_trade_date: date | None,
        limit: int,
    ) -> IndexDailyNineTurnPage:
        conditions = [
            IndexFactorPro.ts_code == ts_code,
            IndexFactorPro.trade_date <= end_date,
        ]
        if start_date is not None:
            conditions.append(IndexFactorPro.trade_date >= start_date)
        if before_trade_date is not None:
            conditions.append(IndexFactorPro.trade_date < before_trade_date)
        join_condition = and_(
            IndexNineTurnDaily.ts_code == IndexFactorPro.ts_code,
            IndexNineTurnDaily.trade_date == IndexFactorPro.trade_date,
        )
        statement = (
            select(
                IndexFactorPro.ts_code.label("ts_code"),
                IndexFactorPro.trade_date.label("trade_date"),
                IndexNineTurnDaily.close.label("close"),
                IndexNineTurnDaily.up_count.label("up_count"),
                IndexNineTurnDaily.down_count.label("down_count"),
                IndexNineTurnDaily.nine_up_turn.label("nine_up_turn"),
                IndexNineTurnDaily.nine_down_turn.label("nine_down_turn"),
                IndexNineTurnDaily.formula_version.label("formula_version"),
            )
            .select_from(IndexFactorPro)
            .outerjoin(IndexNineTurnDaily, join_condition)
            .where(*conditions)
            .order_by(desc(IndexFactorPro.trade_date))
            .limit(limit + 1)
        )
        raw_rows = [dict(row) for row in session.execute(statement).mappings().all()]
        has_more = len(raw_rows) > limit
        rows = raw_rows[:limit]
        rows.reverse()
        for row in rows:
            row["nine_turn_matched"] = row["formula_version"] is not None
        observed_dates = [row["trade_date"] for row in rows if row["nine_turn_matched"]]
        return IndexDailyNineTurnPage(
            rows=tuple(rows),
            has_more=has_more,
            observed_start_date=min(observed_dates) if observed_dates else None,
            observed_end_date=max(observed_dates) if observed_dates else None,
        )


__all__ = ["IndexDailyNineTurnPage", "IndexNineTurnQuery"]
