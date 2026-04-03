from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.models.core.equity_adj_factor import EquityAdjFactor
from src.models.core.equity_daily_bar import EquityDailyBar
from src.models.core.equity_daily_basic import EquityDailyBasic
from src.models.core.equity_dividend import EquityDividend
from src.models.core.equity_holder_number import EquityHolderNumber
from src.models.core.equity_top_list import EquityTopList
from src.models.core.security import Security
from src.web.schemas.share_terminal import (
    ShareKlineItem,
    ShareKlineResponse,
    ShareNewsItem,
    ShareNewsResponse,
    ShareQuoteResponse,
    ShareSecuritySuggestionItem,
    ShareSecuritySuggestionsResponse,
)


class ShareTerminalQueryService:
    def search_securities(self, session: Session, *, query: str, limit: int) -> ShareSecuritySuggestionsResponse:
        text_query = query.strip().upper()
        capped_limit = max(1, min(limit, 30))
        if not text_query:
            return ShareSecuritySuggestionsResponse(query=query, items=[])

        like = f"%{text_query}%"
        rows = session.scalars(
            select(Security)
            .where(
                (func.upper(Security.ts_code).like(like))
                | (func.upper(func.coalesce(Security.symbol, "")).like(like))
                | (func.upper(Security.name).like(like))
                | (func.upper(func.coalesce(Security.cnspell, "")).like(like))
            )
            .order_by(Security.ts_code.asc())
            .limit(capped_limit)
        ).all()
        return ShareSecuritySuggestionsResponse(
            query=query,
            items=[
                ShareSecuritySuggestionItem(
                    ts_code=item.ts_code,
                    symbol=item.symbol,
                    name=item.name,
                    cnspell=item.cnspell,
                    market=item.market,
                )
                for item in rows
            ],
        )

    def build_kline(
        self,
        session: Session,
        *,
        ts_code: str,
        period: str,
        adjust_mode: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> ShareKlineResponse:
        stmt = (
            select(EquityDailyBar)
            .where(EquityDailyBar.ts_code == ts_code)
            .order_by(desc(EquityDailyBar.trade_date))
            .limit(limit)
        )
        if start_date is not None:
            stmt = stmt.where(EquityDailyBar.trade_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(EquityDailyBar.trade_date <= end_date)

        daily_rows = list(reversed(list(session.scalars(stmt).all())))
        if not daily_rows:
            return ShareKlineResponse(ts_code=ts_code, period=period, adjust_mode=adjust_mode, items=[])

        turnover_rate_by_date = self._load_turnover_rate_by_date(
            session,
            ts_code=ts_code,
            start_date=daily_rows[0].trade_date,
            end_date=daily_rows[-1].trade_date,
        )

        if adjust_mode == "qfq":
            daily_rows = self._apply_qfq(session, ts_code=ts_code, rows=daily_rows, end_date=end_date)

        if period == "d":
            items = [
                ShareKlineItem(
                    trade_date=row.trade_date,
                    open=self._to_decimal(row.open),
                    high=self._to_decimal(row.high),
                    low=self._to_decimal(row.low),
                    close=self._to_decimal(row.close),
                    pre_close=row.pre_close,
                    pct_chg=row.pct_chg,
                    volume=row.vol,
                    amount=row.amount,
                    turnover_rate=turnover_rate_by_date.get(row.trade_date),
                )
                for row in daily_rows
            ]
            return ShareKlineResponse(ts_code=ts_code, period=period, adjust_mode=adjust_mode, items=items)

        aggregated = self._aggregate_by_period(daily_rows, period=period)
        return ShareKlineResponse(ts_code=ts_code, period=period, adjust_mode=adjust_mode, items=aggregated)

    def build_quote(self, session: Session, *, ts_code: str) -> ShareQuoteResponse:
        security = session.scalar(
            select(Security).where(Security.ts_code == ts_code).limit(1)
        )
        latest_bar = session.scalar(
            select(EquityDailyBar)
            .where(EquityDailyBar.ts_code == ts_code)
            .order_by(desc(EquityDailyBar.trade_date))
            .limit(1)
        )
        latest_basic = session.scalar(
            select(EquityDailyBasic)
            .where(EquityDailyBasic.ts_code == ts_code)
            .order_by(desc(EquityDailyBasic.trade_date))
            .limit(1)
        )

        if latest_bar is None:
            return ShareQuoteResponse(ts_code=ts_code, name=security.name if security else None)

        return ShareQuoteResponse(
            ts_code=ts_code,
            name=security.name if security else None,
            trade_date=latest_bar.trade_date,
            prev_close=latest_bar.pre_close,
            open=latest_bar.open,
            high=latest_bar.high,
            low=latest_bar.low,
            close=latest_bar.close,
            change_amount=latest_bar.change_amount,
            change_pct=latest_bar.pct_chg,
            volume=latest_bar.vol,
            amount=latest_bar.amount,
            turnover_rate=latest_basic.turnover_rate if latest_basic else None,
            turnover_rate_f=latest_basic.turnover_rate_f if latest_basic else None,
            volume_ratio=latest_basic.volume_ratio if latest_basic else None,
            pe_ttm=latest_basic.pe_ttm if latest_basic else None,
            dv_ratio=latest_basic.dv_ratio if latest_basic else None,
            dv_ttm=latest_basic.dv_ttm if latest_basic else None,
            total_share=latest_basic.total_share if latest_basic else None,
            float_share=latest_basic.float_share if latest_basic else None,
            free_share=latest_basic.free_share if latest_basic else None,
            pb=latest_basic.pb if latest_basic else None,
            total_mv=latest_basic.total_mv if latest_basic else None,
            circ_mv=latest_basic.circ_mv if latest_basic else None,
        )

    def build_news(self, session: Session, *, ts_code: str, limit: int) -> ShareNewsResponse:
        capped_limit = max(1, min(limit, 100))
        items: list[ShareNewsItem] = []
        next_id = 1

        top_list_rows = session.scalars(
            select(EquityTopList)
            .where(EquityTopList.ts_code == ts_code)
            .order_by(desc(EquityTopList.trade_date))
            .limit(capped_limit)
        ).all()
        for row in top_list_rows:
            title = f"龙虎榜：{row.reason}"
            summary = (
                f"收盘 {row.close if row.close is not None else '-'}，"
                f"涨跌幅 {row.pct_chg if row.pct_chg is not None else '-'}%"
            )
            items.append(
                ShareNewsItem(
                    id=f"top_list_{next_id}",
                    occurred_at=row.trade_date,
                    tag="龙虎榜",
                    title=title,
                    summary=summary,
                )
            )
            next_id += 1

        dividend_rows = session.scalars(
            select(EquityDividend)
            .where(EquityDividend.ts_code == ts_code)
            .order_by(desc(EquityDividend.ann_date))
            .limit(capped_limit)
        ).all()
        for row in dividend_rows:
            if row.ann_date is None:
                continue
            title = f"分红送转：{row.div_proc or '方案更新'}"
            summary = (
                f"每股税前分红 {row.cash_div if row.cash_div is not None else '-'}，"
                f"除权日 {row.ex_date.isoformat() if row.ex_date else '-'}"
            )
            items.append(
                ShareNewsItem(
                    id=f"dividend_{next_id}",
                    occurred_at=row.ann_date,
                    tag="分红送转",
                    title=title,
                    summary=summary,
                )
            )
            next_id += 1

        holder_rows = session.scalars(
            select(EquityHolderNumber)
            .where(EquityHolderNumber.ts_code == ts_code)
            .order_by(desc(func.coalesce(EquityHolderNumber.ann_date, EquityHolderNumber.end_date)))
            .limit(capped_limit)
        ).all()
        for row in holder_rows:
            occurred_at = row.ann_date or row.end_date
            if occurred_at is None:
                continue
            title = "股东户数更新"
            summary = f"报告期 {row.end_date.isoformat() if row.end_date else '-'}，户数 {row.holder_num if row.holder_num is not None else '-'}"
            items.append(
                ShareNewsItem(
                    id=f"holder_{next_id}",
                    occurred_at=occurred_at,
                    tag="股东户数",
                    title=title,
                    summary=summary,
                )
            )
            next_id += 1

        items.sort(key=lambda item: item.occurred_at, reverse=True)
        return ShareNewsResponse(ts_code=ts_code, items=items[:capped_limit])

    def _apply_qfq(
        self,
        session: Session,
        *,
        ts_code: str,
        rows: list[EquityDailyBar],
        end_date: date | None,
    ) -> list[EquityDailyBar]:
        adj_rows = session.scalars(
            select(EquityAdjFactor)
            .where(EquityAdjFactor.ts_code == ts_code)
            .order_by(EquityAdjFactor.trade_date.asc())
        ).all()
        if not adj_rows:
            return rows

        factor_map: dict[date, Decimal] = {
            item.trade_date: item.adj_factor
            for item in adj_rows
        }
        end_factor_row = None
        if end_date is not None:
            end_factor_row = session.scalar(
                select(EquityAdjFactor)
                .where(EquityAdjFactor.ts_code == ts_code, EquityAdjFactor.trade_date <= end_date)
                .order_by(desc(EquityAdjFactor.trade_date))
                .limit(1)
            )
        if end_factor_row is None:
            end_factor_row = session.scalar(
                select(EquityAdjFactor)
                .where(EquityAdjFactor.ts_code == ts_code)
                .order_by(desc(EquityAdjFactor.trade_date))
                .limit(1)
            )
        if end_factor_row is None or end_factor_row.adj_factor in (None, Decimal("0")):
            return rows

        end_factor = end_factor_row.adj_factor
        converted: list[EquityDailyBar] = []
        for row in rows:
            factor = factor_map.get(row.trade_date)
            if factor is None:
                converted.append(row)
                continue
            converted.append(
                EquityDailyBar(
                    ts_code=row.ts_code,
                    trade_date=row.trade_date,
                    open=self._qfq_price(row.open, factor, end_factor),
                    high=self._qfq_price(row.high, factor, end_factor),
                    low=self._qfq_price(row.low, factor, end_factor),
                    close=self._qfq_price(row.close, factor, end_factor),
                    pre_close=self._qfq_price(row.pre_close, factor, end_factor),
                    change_amount=self._qfq_price(row.change_amount, factor, end_factor),
                    pct_chg=row.pct_chg,
                    vol=row.vol,
                    amount=row.amount,
                    source=row.source,
                )
            )
        return converted

    @staticmethod
    def _qfq_price(
        value: Decimal | None,
        factor: Decimal,
        end_factor: Decimal,
    ) -> Decimal | None:
        if value is None or end_factor == Decimal("0"):
            return value
        return (value * factor / end_factor).quantize(Decimal("0.0001"))

    @staticmethod
    def _to_decimal(value: Decimal | None) -> Decimal:
        if value is None:
            return Decimal("0")
        return value

    def _aggregate_by_period(self, rows: list[EquityDailyBar], *, period: str) -> list[ShareKlineItem]:
        grouped: dict[tuple[int, int], list[EquityDailyBar]] = defaultdict(list)
        for row in rows:
            if period == "w":
                iso_year, iso_week, _ = row.trade_date.isocalendar()
                grouped[(iso_year, iso_week)].append(row)
            else:
                grouped[(row.trade_date.year, row.trade_date.month)].append(row)

        result: list[ShareKlineItem] = []
        previous_close: Decimal | None = None
        for _, bucket in sorted(grouped.items(), key=lambda item: item[0]):
            ordered = sorted(bucket, key=lambda item: item.trade_date)
            first = ordered[0]
            last = ordered[-1]
            highs = [item.high for item in ordered if item.high is not None]
            lows = [item.low for item in ordered if item.low is not None]
            volumes = [item.vol for item in ordered if item.vol is not None]
            amounts = [item.amount for item in ordered if item.amount is not None]
            close_value = self._to_decimal(last.close)
            pre_close = previous_close if previous_close is not None else first.pre_close
            pct_chg = None
            if pre_close not in (None, Decimal("0")):
                pct_chg = ((close_value - pre_close) / pre_close * Decimal("100")).quantize(Decimal("0.0001"))
            result.append(
                ShareKlineItem(
                    trade_date=last.trade_date,
                    open=self._to_decimal(first.open),
                    high=max(highs) if highs else self._to_decimal(last.close),
                    low=min(lows) if lows else self._to_decimal(last.close),
                    close=close_value,
                    pre_close=pre_close,
                    pct_chg=pct_chg,
                    volume=sum(volumes, Decimal("0")) if volumes else None,
                    amount=sum(amounts, Decimal("0")) if amounts else None,
                    turnover_rate=None,
                )
            )
            previous_close = close_value
        return result

    def _load_turnover_rate_by_date(
        self,
        session: Session,
        *,
        ts_code: str,
        start_date: date,
        end_date: date,
    ) -> dict[date, Decimal | None]:
        rows = session.scalars(
            select(EquityDailyBasic)
            .where(
                EquityDailyBasic.ts_code == ts_code,
                EquityDailyBasic.trade_date >= start_date,
                EquityDailyBasic.trade_date <= end_date,
            )
        ).all()
        return {row.trade_date: row.turnover_rate for row in rows}
