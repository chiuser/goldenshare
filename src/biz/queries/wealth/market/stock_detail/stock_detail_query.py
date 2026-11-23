from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from src.foundation.models.core.equity_factor_pro import EquityFactorPro
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.clients.reference_data import SecurityReferenceRow, local_reference_data
from src.foundation.models.core_serving.security_serving import Security


_FACTOR_FIELD_NAMES: tuple[str, ...] = (
    "ts_code",
    "trade_date",
    "open_qfq",
    "high_qfq",
    "low_qfq",
    "close_qfq",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)
FACTOR_COLUMNS = tuple(getattr(EquityFactorPro, field_name) for field_name in _FACTOR_FIELD_NAMES)
STOCK_DAILY_BASIC_FIELDS = ("turnover_rate", "volume_ratio")


def stock_daily_dates(ts_code, *, start, end, limit, before=None):
    statement = select(EquityDailyBar.trade_date).where(
        EquityDailyBar.ts_code == ts_code, EquityDailyBar.trade_date <= end,
    )
    if start is not None:
        statement = statement.where(EquityDailyBar.trade_date >= start)
    if before is not None:
        statement = statement.where(EquityDailyBar.trade_date < before)
    return statement.order_by(EquityDailyBar.trade_date.desc()).limit(limit)


class StockDetailQuery:
    """Read stock detail facts from the current serving tables."""

    def load_security(
        self, session: Session, *, ts_code: str, timeout_seconds: float | None = None,
    ) -> Security | SecurityReferenceRow | None:
        reference = local_reference_data(session)
        if reference is not None:
            return reference.security.get(ts_code=ts_code, timeout_seconds=timeout_seconds)
        return session.get(Security, ts_code)

    def load_latest_factor_row(
        self,
        session: Session,
        *,
        ts_code: str,
        expected_trade_date: date,
    ) -> dict[str, Any] | None:
        statement = (
            select(*FACTOR_COLUMNS)
            .where(
                EquityFactorPro.ts_code == ts_code,
                EquityFactorPro.trade_date <= expected_trade_date,
            )
            .order_by(desc(EquityFactorPro.trade_date))
            .limit(1)
        )
        row = session.execute(statement).mappings().first()
        return dict(row) if row is not None else None

    def load_daily_basic(self, session: Session, *, ts_code: str, trade_date: date):
        return session.execute(select(EquityDailyBasic.turnover_rate, EquityDailyBasic.volume_ratio).where(
            EquityDailyBasic.ts_code == ts_code, EquityDailyBasic.trade_date == trade_date,
        )).mappings().one_or_none()

    def load_kline_rows(self, session: Session, *, ts_code, end_date, start_date, limit):
        dates = stock_daily_dates(ts_code, start=start_date, end=end_date, limit=limit).cte("page_dates")
        statement = select(
            EquityDailyBar.trade_date, EquityDailyBar.pre_close, EquityDailyBar.change_amount.label("change"),
            EquityDailyBar.pct_chg, EquityDailyBasic.turnover_rate, EquityDailyBasic.volume_ratio,
        ).select_from(EquityDailyBar).join(
            dates, and_(EquityDailyBar.ts_code == ts_code, EquityDailyBar.trade_date == dates.c.trade_date)
        ).outerjoin(EquityDailyBasic, and_(
            EquityDailyBasic.ts_code == ts_code, EquityDailyBasic.trade_date == dates.c.trade_date,
        )).order_by(EquityDailyBar.trade_date)
        return session.execute(statement).mappings().all()
