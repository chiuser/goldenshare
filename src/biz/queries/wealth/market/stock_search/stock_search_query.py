from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.stock_search import A_SHARE_EXCHANGES
from src.foundation.models.core_serving.security_serving import Security


@dataclass(frozen=True, slots=True)
class StockSearchRow:
    ts_code: str
    name: str


class StockSearchQuery:
    """Load a bounded current-listed A-share suggestion set."""

    def search(
        self,
        session: Session,
        *,
        keyword: str,
        escaped_prefix: str,
        limit: int,
    ) -> list[StockSearchRow]:
        normalized_symbol = func.upper(func.coalesce(Security.symbol, ""))
        normalized_ts_code = func.upper(func.coalesce(Security.ts_code, ""))
        normalized_cnspell = func.upper(func.coalesce(Security.cnspell, ""))

        symbol_prefix_match = normalized_symbol.like(escaped_prefix, escape="\\")
        ts_code_prefix_match = normalized_ts_code.like(escaped_prefix, escape="\\")
        cnspell_prefix_match = normalized_cnspell.like(escaped_prefix, escape="\\")

        rank = case(
            (
                or_(normalized_symbol == keyword, normalized_ts_code == keyword),
                0,
            ),
            (symbol_prefix_match, 1),
            (ts_code_prefix_match, 2),
            (cnspell_prefix_match, 3),
            else_=4,
        )
        statement = (
            select(Security.ts_code, Security.name)
            .where(
                Security.security_type == "EQUITY",
                Security.list_status == "L",
                Security.curr_type == "CNY",
                Security.exchange.in_(A_SHARE_EXCHANGES),
                or_(
                    symbol_prefix_match,
                    ts_code_prefix_match,
                    cnspell_prefix_match,
                ),
            )
            .order_by(rank.asc(), Security.ts_code.asc())
            .limit(limit)
        )
        rows = session.execute(statement).all()
        return [StockSearchRow(ts_code=row.ts_code, name=row.name) for row in rows]
