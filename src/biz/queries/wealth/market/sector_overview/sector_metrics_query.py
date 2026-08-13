from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.board_moneyflow_dc import BoardMoneyflowDc
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember


SectorView = Literal["INDUSTRY", "CONCEPT", "REGION"]

_VIEW_SOURCE_LABELS: dict[SectorView, tuple[str, str]] = {
    "INDUSTRY": ("行业板块", "行业"),
    "CONCEPT": ("概念板块", "概念"),
    "REGION": ("地域板块", "地域"),
}


@dataclass(frozen=True, slots=True)
class SectorMetricRow:
    sector_code: str
    sector_name: str | None
    change_pct: Decimal | None
    turnover_amount: Decimal | None
    main_net_inflow: Decimal | None
    up_count: int | None
    down_count: int | None
    leading_code: str | None
    leading_name: str | None
    leading_pct: Decimal | None
    has_daily: bool
    has_index: bool
    has_moneyflow: bool
    has_members: bool


class SectorMetricsQuery:
    """Load one view's same-day board metrics and leader facts in one query."""

    def load(
        self,
        session: Session,
        *,
        trade_date: date,
        view: SectorView,
        sector_codes: tuple[str, ...] | None = None,
    ) -> dict[str, SectorMetricRow]:
        daily_category, moneyflow_type = _VIEW_SOURCE_LABELS[view]
        candidate_union = (
            select(DcDaily.ts_code.label("sector_code")).where(
                DcDaily.trade_date == trade_date,
                DcDaily.category == daily_category,
            )
            .union(
                select(DcIndex.ts_code.label("sector_code")).where(
                    DcIndex.trade_date == trade_date,
                    DcIndex.idx_type == daily_category,
                ),
                select(BoardMoneyflowDc.ts_code.label("sector_code")).where(
                    BoardMoneyflowDc.trade_date == trade_date,
                    BoardMoneyflowDc.content_type == moneyflow_type,
                    BoardMoneyflowDc.ts_code.is_not(None),
                ),
            )
        )
        candidate_rows = candidate_union.subquery("sector_candidate_rows")
        candidates = select(candidate_rows.c.sector_code).distinct().subquery("sector_candidates")
        moneyflow = (
            select(
                BoardMoneyflowDc.trade_date.label("trade_date"),
                BoardMoneyflowDc.ts_code.label("sector_code"),
                func.max(BoardMoneyflowDc.net_amount).label("net_amount"),
            )
            .where(
                BoardMoneyflowDc.trade_date == trade_date,
                BoardMoneyflowDc.content_type == moneyflow_type,
                BoardMoneyflowDc.ts_code.is_not(None),
            )
            .group_by(BoardMoneyflowDc.trade_date, BoardMoneyflowDc.ts_code)
            .subquery("sector_moneyflow")
        )
        statement = (
            select(
                candidates.c.sector_code,
                DcIndex.name,
                DcDaily.pct_change,
                DcDaily.amount,
                moneyflow.c.net_amount,
                DcIndex.up_num,
                DcIndex.down_num,
                DcIndex.leading_code,
                DcIndex.leading,
                DcIndex.leading_pct,
                DcDaily.ts_code.label("daily_code"),
                DcIndex.ts_code.label("index_code"),
                exists(
                    select(1).where(
                        DcMember.trade_date == trade_date,
                        DcMember.ts_code == candidates.c.sector_code,
                    )
                ).label("has_members"),
            )
            .select_from(candidates)
            .outerjoin(
                DcDaily,
                and_(
                    DcDaily.trade_date == trade_date,
                    DcDaily.category == daily_category,
                    DcDaily.ts_code == candidates.c.sector_code,
                ),
            )
            .outerjoin(
                DcIndex,
                and_(
                    DcIndex.trade_date == trade_date,
                    DcIndex.ts_code == candidates.c.sector_code,
                    DcIndex.idx_type == daily_category,
                ),
            )
            .outerjoin(
                moneyflow,
                and_(
                    moneyflow.c.trade_date == trade_date,
                    moneyflow.c.sector_code == candidates.c.sector_code,
                ),
            )
            .order_by(candidates.c.sector_code)
        )
        if sector_codes is not None:
            if not sector_codes:
                return {}
            statement = statement.where(candidates.c.sector_code.in_(sector_codes))

        return {
            row.sector_code: SectorMetricRow(
                sector_code=row.sector_code,
                sector_name=row.name,
                change_pct=row.pct_change,
                turnover_amount=row.amount,
                main_net_inflow=row.net_amount,
                up_count=row.up_num,
                down_count=row.down_num,
                leading_code=row.leading_code,
                leading_name=row.leading,
                leading_pct=row.leading_pct,
                has_daily=row.daily_code is not None,
                has_index=row.index_code is not None,
                has_moneyflow=row.net_amount is not None,
                has_members=bool(row.has_members),
            )
            for row in session.execute(statement)
        }
