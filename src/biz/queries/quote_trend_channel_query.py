from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing


TREND_CHANNEL_TS_CODE = "000001.SH"


@dataclass(frozen=True, slots=True)
class TrendChannelInstrumentRow:
    ts_code: str
    name: str | None


@dataclass(frozen=True, slots=True)
class TrendChannelWatermark:
    row_count: int
    max_trade_date: date | None
    max_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class TrendChannelSourceRow:
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    updated_at: datetime


class QuoteTrendChannelQueryError(RuntimeError):
    pass


class QuoteTrendChannelQuery:
    def load_instrument(self, session: Session) -> TrendChannelInstrumentRow | None:
        try:
            row = session.execute(
                select(IndexBasic.ts_code, IndexBasic.name)
                .where(IndexBasic.ts_code == TREND_CHANNEL_TS_CODE)
                .limit(1)
            ).one_or_none()
        except SQLAlchemyError as exc:
            raise QuoteTrendChannelQueryError("trend channel instrument query failed") from exc

        if row is None:
            return None
        return TrendChannelInstrumentRow(ts_code=row.ts_code, name=row.name)

    def load_watermark(self, session: Session) -> TrendChannelWatermark:
        try:
            row_count, max_trade_date, max_updated_at = session.execute(
                select(
                    func.count(IndexDailyServing.trade_date),
                    func.max(IndexDailyServing.trade_date),
                    func.max(IndexDailyServing.updated_at),
                ).where(IndexDailyServing.ts_code == TREND_CHANNEL_TS_CODE)
            ).one()
        except SQLAlchemyError as exc:
            raise QuoteTrendChannelQueryError("trend channel watermark query failed") from exc

        return TrendChannelWatermark(
            row_count=int(row_count),
            max_trade_date=max_trade_date,
            max_updated_at=max_updated_at,
        )

    def load_all_rows(self, session: Session) -> tuple[TrendChannelSourceRow, ...]:
        try:
            rows = session.execute(
                select(
                    IndexDailyServing.trade_date,
                    IndexDailyServing.open,
                    IndexDailyServing.high,
                    IndexDailyServing.low,
                    IndexDailyServing.close,
                    IndexDailyServing.updated_at,
                )
                .where(IndexDailyServing.ts_code == TREND_CHANNEL_TS_CODE)
                .order_by(IndexDailyServing.trade_date.asc())
            ).all()
        except SQLAlchemyError as exc:
            raise QuoteTrendChannelQueryError("trend channel history query failed") from exc

        return tuple(
            TrendChannelSourceRow(
                trade_date=row.trade_date,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                updated_at=row.updated_at,
            )
            for row in rows
        )
