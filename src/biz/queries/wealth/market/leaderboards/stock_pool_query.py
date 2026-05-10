from __future__ import annotations

from datetime import date

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.security_serving import Security


class LeaderboardStockPoolQuery:
    """Load CN_A leaderboard stock pool codes for a target trade date."""

    def load_codes(self, session: Session, *, trade_date: date) -> set[str]:
        upper_name = func.upper(Security.name)
        rows = session.execute(
            select(Security.ts_code).where(
                Security.security_type == "EQUITY",
                Security.exchange.in_(("SSE", "SZSE")),
                Security.list_status == "L",
                Security.list_date.is_not(None),
                Security.list_date <= trade_date,
                or_(Security.delist_date.is_(None), Security.delist_date > trade_date),
                not_(
                    or_(
                        upper_name.like("ST%"),
                        upper_name.like("*ST%"),
                    )
                ),
            )
        ).scalars().all()
        return set(rows)

