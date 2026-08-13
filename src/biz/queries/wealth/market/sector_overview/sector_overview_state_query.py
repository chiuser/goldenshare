from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.board_moneyflow_dc import BoardMoneyflowDc
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.trade_calendar import TradeCalendar


_CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SESSION_OPEN = time(hour=9, minute=30)
_SESSION_MORNING_CLOSE = time(hour=11, minute=30)
_SESSION_AFTERNOON_OPEN = time(hour=13, minute=0)
_SESSION_CLOSE = time(hour=15, minute=0)
_EOD_EXPECTED_SWITCH_HOUR = 20

SectorView = Literal["INDUSTRY", "CONCEPT", "REGION"]
_VIEW_SOURCE_LABELS: dict[SectorView, tuple[str, str]] = {
    "INDUSTRY": ("行业板块", "行业"),
    "CONCEPT": ("概念板块", "概念"),
    "REGION": ("地域板块", "地域"),
}


@dataclass(frozen=True, slots=True)
class SectorOverviewTradingDayContext:
    market: str
    expected_trade_date: date
    prev_trade_date: date | None
    is_trading_day: bool
    session_status: str
    as_of_time: datetime


@dataclass(frozen=True, slots=True)
class SectorOverviewSourceState:
    common_base_date: date | None
    dc_daily_date: date | None
    board_moneyflow_date: date | None
    dc_index_date: date | None

    @property
    def observed_trade_date(self) -> date | None:
        return self.common_base_date

    def all_sources_on(self, trade_date: date) -> bool:
        return self.common_base_date == trade_date


class SectorOverviewStateQuery:
    """Resolve one trading-day context and one view-specific source-state snapshot."""

    def resolve_trading_day(
        self,
        session: Session,
        *,
        market: str,
        requested_trade_date: date | None,
    ) -> SectorOverviewTradingDayContext:
        if market != "CN_A":
            raise ValueError(f"unsupported market: {market}")

        local_now = datetime.now(_CN_TIMEZONE)
        latest_open_sq = (
            select(func.max(TradeCalendar.trade_date))
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= local_now.date(),
            )
            .scalar_subquery()
        )
        today_open_sq = (
            select(TradeCalendar.is_open)
            .where(TradeCalendar.exchange == "SSE", TradeCalendar.trade_date == local_now.date())
            .scalar_subquery()
        )
        requested_open_sq = (
            select(TradeCalendar.is_open)
            .where(TradeCalendar.exchange == "SSE", TradeCalendar.trade_date == requested_trade_date)
            .scalar_subquery()
            if requested_trade_date is not None
            else select(TradeCalendar.is_open).where(False).scalar_subquery()
        )
        resolved_seed = requested_trade_date or local_now.date()
        previous_open_sq = (
            select(func.max(TradeCalendar.trade_date))
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date < resolved_seed,
            )
            .scalar_subquery()
        )
        row = session.execute(
            select(
                latest_open_sq.label("latest_open"),
                today_open_sq.label("today_open"),
                requested_open_sq.label("requested_open"),
                previous_open_sq.label("previous_open"),
            )
        ).one()

        if requested_trade_date is not None:
            resolved_trade_date = requested_trade_date
            is_trading_day = bool(row.requested_open)
        else:
            latest_open = row.latest_open or local_now.date()
            if bool(row.today_open) and local_now.hour < _EOD_EXPECTED_SWITCH_HOUR and row.previous_open is not None:
                resolved_trade_date = row.previous_open
            else:
                resolved_trade_date = latest_open
            is_trading_day = row.latest_open is not None

        prev_trade_date = session.scalar(
            select(func.max(TradeCalendar.trade_date)).where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date < resolved_trade_date,
            )
        )
        return SectorOverviewTradingDayContext(
            market=market,
            expected_trade_date=resolved_trade_date,
            prev_trade_date=prev_trade_date,
            is_trading_day=is_trading_day,
            session_status=self._resolve_session_status(
                local_now=local_now,
                is_trading_day=is_trading_day and resolved_trade_date == local_now.date(),
            ),
            as_of_time=local_now,
        )

    def load_source_state(
        self,
        session: Session,
        *,
        expected_trade_date: date,
        view: SectorView,
    ) -> SectorOverviewSourceState:
        daily_category, moneyflow_type = _VIEW_SOURCE_LABELS[view]
        daily_date_sq = (
            select(func.max(DcDaily.trade_date))
            .where(DcDaily.trade_date <= expected_trade_date, DcDaily.category == daily_category)
            .scalar_subquery()
        )
        index_date_sq = (
            select(func.max(DcIndex.trade_date))
            .where(DcIndex.trade_date <= expected_trade_date, DcIndex.idx_type == daily_category)
            .scalar_subquery()
        )
        moneyflow_date_sq = (
            select(func.max(BoardMoneyflowDc.trade_date))
            .where(
                BoardMoneyflowDc.trade_date <= expected_trade_date,
                BoardMoneyflowDc.content_type == moneyflow_type,
                BoardMoneyflowDc.ts_code.is_not(None),
            )
            .scalar_subquery()
        )
        common_date_sq = (
            select(func.max(DcDaily.trade_date))
            .where(
                DcDaily.trade_date <= expected_trade_date,
                DcDaily.category == daily_category,
                exists(
                    select(1).where(
                        and_(
                            DcIndex.trade_date == DcDaily.trade_date,
                            DcIndex.idx_type == daily_category,
                        )
                    )
                ),
                exists(
                    select(1).where(
                        and_(
                            BoardMoneyflowDc.trade_date == DcDaily.trade_date,
                            BoardMoneyflowDc.content_type == moneyflow_type,
                            BoardMoneyflowDc.ts_code.is_not(None),
                        )
                    )
                ),
            )
            .scalar_subquery()
        )
        row = session.execute(
            select(
                common_date_sq.label("common_date"),
                daily_date_sq.label("daily_date"),
                index_date_sq.label("index_date"),
                moneyflow_date_sq.label("moneyflow_date"),
            )
        ).one()
        return SectorOverviewSourceState(
            common_base_date=row.common_date,
            dc_daily_date=row.daily_date,
            board_moneyflow_date=row.moneyflow_date,
            dc_index_date=row.index_date,
        )

    @staticmethod
    def _resolve_session_status(*, local_now: datetime, is_trading_day: bool) -> str:
        if not is_trading_day:
            return "CLOSED"
        current_time = local_now.timetz().replace(tzinfo=None)
        if current_time < _SESSION_OPEN:
            return "PRE_OPEN"
        if current_time < _SESSION_MORNING_CLOSE:
            return "TRADING"
        if current_time < _SESSION_AFTERNOON_OPEN:
            return "BREAK"
        if current_time < _SESSION_CLOSE:
            return "TRADING"
        return "CLOSED"
