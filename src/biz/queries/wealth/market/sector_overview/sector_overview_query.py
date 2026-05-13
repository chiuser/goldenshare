from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.board_moneyflow_dc import BoardMoneyflowDc
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_index import DcIndex


DC_DAILY_CATEGORIES = ("行业板块", "概念板块", "地域板块")
BOARD_MONEYFLOW_CONTENT_TYPES = ("行业", "概念", "地域")


@dataclass(frozen=True, slots=True)
class SectorDailyRow:
    ts_code: str
    category: str
    pct_change: Decimal | None
    turnover_rate: Decimal | None
    amount: Decimal | None


@dataclass(frozen=True, slots=True)
class SectorIndexRow:
    ts_code: str
    name: str | None
    idx_type: str | None
    leading: str | None
    leading_code: str | None
    leading_pct: Decimal | None
    up_num: int | None
    down_num: int | None


@dataclass(frozen=True, slots=True)
class SectorMoneyflowRow:
    ts_code: str
    name: str
    content_type: str
    net_amount: Decimal | None
    net_amount_rate: Decimal | None


class SectorOverviewQuery:
    """Load DC board facts for sector overview."""

    def load_daily_rows(self, session: Session, *, trade_date: date) -> list[SectorDailyRow]:
        rows = session.execute(
            select(
                DcDaily.ts_code,
                DcDaily.category,
                DcDaily.pct_change,
                DcDaily.turnover_rate,
                DcDaily.amount,
            ).where(
                DcDaily.trade_date == trade_date,
                DcDaily.category.in_(DC_DAILY_CATEGORIES),
                DcDaily.ts_code.is_not(None),
            )
        ).all()
        return [
            SectorDailyRow(
                ts_code=row.ts_code,
                category=row.category,
                pct_change=row.pct_change,
                turnover_rate=row.turnover_rate,
                amount=row.amount,
            )
            for row in rows
        ]

    def load_index_rows(self, session: Session, *, trade_date: date) -> dict[str, SectorIndexRow]:
        rows = session.execute(
            select(
                DcIndex.ts_code,
                DcIndex.name,
                DcIndex.idx_type,
                DcIndex.leading,
                DcIndex.leading_code,
                DcIndex.leading_pct,
                DcIndex.up_num,
                DcIndex.down_num,
            ).where(
                DcIndex.trade_date == trade_date,
                DcIndex.idx_type.in_(DC_DAILY_CATEGORIES),
                DcIndex.ts_code.is_not(None),
            )
        ).all()
        return {
            row.ts_code: SectorIndexRow(
                ts_code=row.ts_code,
                name=row.name,
                idx_type=row.idx_type,
                leading=row.leading,
                leading_code=row.leading_code,
                leading_pct=row.leading_pct,
                up_num=row.up_num,
                down_num=row.down_num,
            )
            for row in rows
        }

    def load_moneyflow_rows(self, session: Session, *, trade_date: date) -> list[SectorMoneyflowRow]:
        rows = session.execute(
            select(
                BoardMoneyflowDc.ts_code,
                BoardMoneyflowDc.name,
                BoardMoneyflowDc.content_type,
                BoardMoneyflowDc.net_amount,
                BoardMoneyflowDc.net_amount_rate,
            ).where(
                BoardMoneyflowDc.trade_date == trade_date,
                BoardMoneyflowDc.content_type.in_(BOARD_MONEYFLOW_CONTENT_TYPES),
                BoardMoneyflowDc.ts_code.is_not(None),
            )
        ).all()
        return [
            SectorMoneyflowRow(
                ts_code=row.ts_code,
                name=row.name,
                content_type=row.content_type,
                net_amount=row.net_amount,
                net_amount_rate=row.net_amount_rate,
            )
            for row in rows
        ]
