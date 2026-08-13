from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, select
from sqlalchemy.orm import Session

from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.security_serving import Security


@dataclass(frozen=True, slots=True)
class SectorMemberRow:
    stock_code: str
    stock_name: str | None
    change_pct: Decimal | None


class SectorMemberQuery:
    """Load one selected sector's effective A-share members, ranked by EOD return."""

    def load_top(
        self,
        session: Session,
        *,
        trade_date: date,
        sector_code: str,
        limit: int = 5,
    ) -> list[SectorMemberRow]:
        suspended = (
            select(EquitySuspendD.ts_code.label("stock_code"))
            .where(
                EquitySuspendD.trade_date == trade_date,
                EquitySuspendD.suspend_type == "S",
            )
            .distinct()
            .subquery("selected_sector_suspended")
        )
        visible_change = case((suspended.c.stock_code.is_(None), EquityDailyBar.pct_chg), else_=None)
        statement = (
            select(
                DcMember.con_code,
                DcMember.name,
                visible_change.label("pct_chg"),
            )
            .select_from(DcMember)
            .join(
                Security,
                and_(
                    Security.ts_code == DcMember.con_code,
                    Security.security_type == "EQUITY",
                    Security.curr_type == "CNY",
                    Security.list_status.in_(("L", "D")),
                    Security.list_date.is_not(None),
                    Security.list_date <= trade_date,
                    (Security.delist_date.is_(None) | (Security.delist_date > trade_date)),
                ),
            )
            .outerjoin(suspended, suspended.c.stock_code == DcMember.con_code)
            .outerjoin(
                EquityDailyBar,
                and_(
                    EquityDailyBar.trade_date == trade_date,
                    EquityDailyBar.ts_code == DcMember.con_code,
                ),
            )
            .where(DcMember.trade_date == trade_date, DcMember.ts_code == sector_code)
            .distinct()
            .order_by(visible_change.desc().nulls_last(), DcMember.con_code)
            .limit(limit)
        )
        return [
            SectorMemberRow(
                stock_code=row.con_code,
                stock_name=row.name,
                change_pct=row.pct_chg,
            )
            for row in session.execute(statement)
        ]
