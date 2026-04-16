from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from decimal import ROUND_HALF_UP

from sqlalchemy import and_, desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.etf_basic import EtfBasic
from src.foundation.models.core_serving.fund_daily_bar import FundDailyBar
from src.foundation.models.core_serving.ind_kdj import IndicatorKdj
from src.foundation.models.core_serving.ind_macd import IndicatorMacd
from src.foundation.models.core_serving.index_basic import IndexBasic
from src.foundation.models.core_serving.index_daily_basic import IndexDailyBasic
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.core_serving.kpl_concept_cons import KplConceptCons
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving.stk_period_bar import StkPeriodBar
from src.foundation.models.core_serving.stk_period_bar_adj import StkPeriodBarAdj
from src.foundation.models.core_serving.ths_member import ThsMember
from src.foundation.models.core_serving.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.dc_member import DcMember
from src.foundation.models.core_serving.dc_index import DcIndex
from src.biz.schemas.quote import (
    MarketTradeCalendarItem,
    MarketTradeCalendarResponse,
    QuoteAnnouncementItem,
    QuoteAnnouncementsCapability,
    QuoteAnnouncementsResponse,
    QuoteChartHeaderDefaults,
    QuoteDefaultChart,
    QuoteInstrument,
    QuoteKlineBar,
    QuoteKlineMeta,
    QuoteKlineResponse,
    QuotePageInitResponse,
    QuotePriceSummary,
    QuoteRelatedInfoCapability,
    QuoteRelatedInfoItem,
    QuoteRelatedInfoResponse,
)


SUPPORTED_PERIODS = {"day", "week", "month"}
UNSUPPORTED_MINUTE_PERIODS = {"timeline", "minute5", "minute15", "minute30", "minute60"}
SUPPORTED_ADJUSTMENTS = {"none", "forward", "backward"}
INDICATOR_PREHEAT_BARS = 250


@dataclass
class ResolvedInstrument:
    ts_code: str
    symbol: str
    market: str
    security_type: str
    name: str | None
    exchange: str | None
    industry: str | None
    list_status: str | None

    @property
    def instrument_id(self) -> str:
        return f"{self.market}.{self.symbol}"


@dataclass
class KlinePoint:
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    pre_close: Decimal | None
    change_amount: Decimal | None
    pct_chg: Decimal | None
    vol: Decimal | None
    amount: Decimal | None
    turnover_rate: Decimal | None = None


class QuoteQueryService:
    def resolve_instrument(
        self,
        session: Session,
        *,
        ts_code: str | None,
        symbol: str | None,
        market: str | None,
        security_type: str | None,
    ) -> ResolvedInstrument:
        normalized_security_type = (security_type or "").strip().lower() or None
        normalized_ts_code = (ts_code or "").strip().upper() or None
        normalized_symbol = (symbol or "").strip().upper() or None
        normalized_market = (market or "").strip().upper() or None

        if normalized_ts_code is None:
            if normalized_symbol is None:
                raise ValueError("请提供 ts_code 或 symbol")
            if "." in normalized_symbol:
                normalized_ts_code = normalized_symbol
            else:
                if normalized_market is None:
                    raise ValueError("使用 symbol 查询时请同时提供 market")
                normalized_ts_code = f"{normalized_symbol}.{normalized_market}"

        if "." in normalized_ts_code:
            inferred_symbol, inferred_market = normalized_ts_code.split(".", 1)
        else:
            inferred_symbol, inferred_market = normalized_ts_code, (normalized_market or "")
        normalized_symbol = inferred_symbol
        normalized_market = inferred_market

        if normalized_security_type == "stock" or normalized_security_type is None:
            security = session.scalar(
                select(Security).where(Security.ts_code == normalized_ts_code).limit(1)
            )
            if security is not None:
                return ResolvedInstrument(
                    ts_code=security.ts_code,
                    symbol=security.symbol or normalized_symbol,
                    market=(security.ts_code.split(".", 1)[1] if "." in security.ts_code else normalized_market),
                    security_type="stock",
                    name=security.name,
                    exchange=security.exchange,
                    industry=security.industry,
                    list_status=security.list_status,
                )
            if normalized_security_type == "stock":
                raise ValueError(f"未找到股票标的：{normalized_ts_code}")

        if normalized_security_type == "index" or normalized_security_type is None:
            index = session.scalar(
                select(IndexBasic).where(IndexBasic.ts_code == normalized_ts_code).limit(1)
            )
            if index is not None:
                return ResolvedInstrument(
                    ts_code=index.ts_code,
                    symbol=index.ts_code.split(".", 1)[0],
                    market=(index.ts_code.split(".", 1)[1] if "." in index.ts_code else normalized_market),
                    security_type="index",
                    name=index.name,
                    exchange=index.market,
                    industry=index.category,
                    list_status=None,
                )
            if normalized_security_type == "index":
                raise ValueError(f"未找到指数标的：{normalized_ts_code}")

        if normalized_security_type == "etf" or normalized_security_type is None:
            etf = session.scalar(
                select(EtfBasic).where(EtfBasic.ts_code == normalized_ts_code).limit(1)
            )
            if etf is not None:
                return ResolvedInstrument(
                    ts_code=etf.ts_code,
                    symbol=etf.ts_code.split(".", 1)[0],
                    market=(etf.ts_code.split(".", 1)[1] if "." in etf.ts_code else normalized_market),
                    security_type="etf",
                    name=etf.cname or etf.csname or etf.extname,
                    exchange=etf.exchange,
                    industry=etf.etf_type,
                    list_status=etf.list_status,
                )
            if normalized_security_type == "etf":
                raise ValueError(f"未找到 ETF 标的：{normalized_ts_code}")

        raise ValueError(f"无法识别标的：{normalized_ts_code}")

    def build_page_init(
        self,
        session: Session,
        *,
        instrument: ResolvedInstrument,
    ) -> QuotePageInitResponse:
        summary = self._build_price_summary(session, instrument=instrument)
        default_adjustment = "forward" if instrument.security_type == "stock" else "none"
        try:
            defaults = self._build_chart_header_defaults(
                session,
                instrument=instrument,
                adjustment=default_adjustment,
            )
        except ValueError:
            # Keep page-init stable: when forward/backward factors are incomplete,
            # fallback to non-adjusted day chart for initial load.
            default_adjustment = "none"
            defaults = self._build_chart_header_defaults(
                session,
                instrument=instrument,
                adjustment=default_adjustment,
            )
        summary = self._round_price_summary(summary)
        defaults = self._round_chart_header_defaults(defaults)
        return QuotePageInitResponse(
            instrument=self._to_instrument_schema(instrument),
            price_summary=summary,
            default_chart=QuoteDefaultChart(default_period="day", default_adjustment=default_adjustment),
            chart_header_defaults=defaults,
        )

    def build_kline(
        self,
        session: Session,
        *,
        instrument: ResolvedInstrument,
        period: str,
        adjustment: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> QuoteKlineResponse:
        points = self._load_kline_points(
            session,
            instrument=instrument,
            period=period,
            adjustment=adjustment,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
        bars = self._attach_indicators_with_context(
            session,
            instrument=instrument,
            period=period,
            adjustment=adjustment,
            points=points,
        )
        bars = self._round_kline_bars_for_response(bars)
        next_start_date = None
        has_more_history = False
        if points:
            older_date = self._load_older_trade_date(
                session,
                instrument=instrument,
                period=period,
                adjustment=adjustment,
                first_trade_date=points[0].trade_date,
            )
            next_start_date = older_date
            has_more_history = older_date is not None
        return QuoteKlineResponse(
            instrument=self._to_instrument_schema(instrument),
            period=period,
            adjustment=adjustment,
            bars=bars,
            meta=QuoteKlineMeta(
                bar_count=len(bars),
                has_more_history=has_more_history,
                next_start_date=next_start_date,
            ),
        )

    def _build_chart_header_defaults(
        self,
        session: Session,
        *,
        instrument: ResolvedInstrument,
        adjustment: str,
    ) -> QuoteChartHeaderDefaults:
        points = self._load_kline_points(
            session,
            instrument=instrument,
            period="day",
            adjustment=adjustment,
            start_date=None,
            end_date=None,
            limit=250,
        )
        if not points:
            return QuoteChartHeaderDefaults()
        bars = self._attach_indicators_with_context(
            session,
            instrument=instrument,
            period="day",
            adjustment=adjustment,
            points=points,
        )
        if not bars:
            return QuoteChartHeaderDefaults()
        last = bars[-1]
        return QuoteChartHeaderDefaults(
            ma5=last.ma5,
            ma10=last.ma10,
            ma15=last.ma15,
            ma20=last.ma20,
            ma30=last.ma30,
            ma60=last.ma60,
            ma120=last.ma120,
            ma250=last.ma250,
            volume_ma5=last.volume_ma5,
            volume_ma10=last.volume_ma10,
            macd=last.macd,
            dif=last.dif,
            dea=last.dea,
            k=last.k,
            d=last.d,
            j=last.j,
        )

    def _attach_indicators_with_context(
        self,
        session: Session,
        *,
        instrument: ResolvedInstrument,
        period: str,
        adjustment: str,
        points: list[KlinePoint],
    ) -> list[QuoteKlineBar]:
        if not points:
            return []
        if instrument.security_type != "stock" or period != "day":
            return self._attach_indicators(points)

        preheat_points = self._load_stock_daily_preheat_points(
            session,
            ts_code=instrument.ts_code,
            adjustment=adjustment,
            before_trade_date=points[0].trade_date,
            limit=INDICATOR_PREHEAT_BARS,
        )
        if not preheat_points:
            bars = self._attach_indicators(points)
            self._overlay_stock_daily_indicators(
                session,
                ts_code=instrument.ts_code,
                adjustment=adjustment,
                bars=bars,
            )
            return bars

        context_points = [*preheat_points, *points]
        context_bars = self._attach_indicators(context_points)
        by_trade_date = {bar.trade_date: bar for bar in context_bars}
        bars = [by_trade_date[point.trade_date] for point in points if point.trade_date in by_trade_date]
        self._overlay_stock_daily_indicators(
            session,
            ts_code=instrument.ts_code,
            adjustment=adjustment,
            bars=bars,
        )
        return bars

    def _overlay_stock_daily_indicators(
        self,
        session: Session,
        *,
        ts_code: str,
        adjustment: str,
        bars: list[QuoteKlineBar],
    ) -> None:
        if not bars:
            return
        start_date = bars[0].trade_date
        end_date = bars[-1].trade_date

        try:
            macd_version = session.scalar(select(func.max(IndicatorMacd.version)))
            kdj_version = session.scalar(select(func.max(IndicatorKdj.version)))
        except SQLAlchemyError:
            # Some environments/tests may not have indicator tables initialized yet.
            return
        if macd_version is None and kdj_version is None:
            return

        macd_map: dict[date, tuple[Decimal | None, Decimal | None, Decimal | None]] = {}
        if macd_version is not None:
            macd_rows = session.execute(
                select(
                    IndicatorMacd.trade_date,
                    IndicatorMacd.dif,
                    IndicatorMacd.dea,
                    IndicatorMacd.macd_bar,
                ).where(
                    IndicatorMacd.ts_code == ts_code,
                    IndicatorMacd.adjustment == adjustment,
                    IndicatorMacd.version == macd_version,
                    IndicatorMacd.trade_date >= start_date,
                    IndicatorMacd.trade_date <= end_date,
                    IndicatorMacd.is_valid.is_(True),
                )
            ).all()
            macd_map = {
                trade_date: (dif, dea, macd_bar)
                for trade_date, dif, dea, macd_bar in macd_rows
            }

        kdj_map: dict[date, tuple[Decimal | None, Decimal | None, Decimal | None]] = {}
        if kdj_version is not None:
            kdj_rows = session.execute(
                select(
                    IndicatorKdj.trade_date,
                    IndicatorKdj.k,
                    IndicatorKdj.d,
                    IndicatorKdj.j,
                ).where(
                    IndicatorKdj.ts_code == ts_code,
                    IndicatorKdj.adjustment == adjustment,
                    IndicatorKdj.version == kdj_version,
                    IndicatorKdj.trade_date >= start_date,
                    IndicatorKdj.trade_date <= end_date,
                    IndicatorKdj.is_valid.is_(True),
                )
            ).all()
            kdj_map = {
                trade_date: (k_value, d_value, j_value)
                for trade_date, k_value, d_value, j_value in kdj_rows
            }

        for bar in bars:
            macd_values = macd_map.get(bar.trade_date)
            bar.dif = macd_values[0] if macd_values is not None else None
            bar.dea = macd_values[1] if macd_values is not None else None
            bar.macd = macd_values[2] if macd_values is not None else None

            kdj_values = kdj_map.get(bar.trade_date)
            bar.k = kdj_values[0] if kdj_values is not None else None
            bar.d = kdj_values[1] if kdj_values is not None else None
            bar.j = kdj_values[2] if kdj_values is not None else None

    def build_related_info(
        self,
        session: Session,
        *,
        instrument: ResolvedInstrument,
    ) -> QuoteRelatedInfoResponse:
        items: list[QuoteRelatedInfoItem] = []
        if instrument.security_type == "stock" and instrument.industry:
            items.append(
                QuoteRelatedInfoItem(
                    type="industry",
                    title="行业",
                    value=instrument.industry,
                    action_target=None,
                )
            )

        concept_names = self._load_concepts(session, ts_code=instrument.ts_code, security_type=instrument.security_type)
        for name in concept_names[:8]:
            items.append(
                QuoteRelatedInfoItem(
                    type="concept",
                    title="概念",
                    value=name,
                    action_target=f"CONCEPT:{name}",
                )
            )

        return QuoteRelatedInfoResponse(
            items=items,
            capability=QuoteRelatedInfoCapability(related_etf="not_available_in_v1"),
        )

    def build_announcements_placeholder(self) -> QuoteAnnouncementsResponse:
        return QuoteAnnouncementsResponse(
            items=[],
            capability=QuoteAnnouncementsCapability(
                status="placeholder",
                reason="announcement_source_not_ready",
            ),
        )

    def build_trade_calendar(
        self,
        session: Session,
        *,
        exchange: str,
        start_date: date,
        end_date: date,
    ) -> MarketTradeCalendarResponse:
        rows = session.scalars(
            select(TradeCalendar)
            .where(
                TradeCalendar.exchange == exchange,
                TradeCalendar.trade_date >= start_date,
                TradeCalendar.trade_date <= end_date,
            )
            .order_by(TradeCalendar.trade_date.asc())
        ).all()
        return MarketTradeCalendarResponse(
            exchange=exchange,
            items=[
                MarketTradeCalendarItem(
                    trade_date=row.trade_date,
                    is_open=row.is_open,
                    pretrade_date=row.pretrade_date,
                )
                for row in rows
            ],
        )

    def _build_price_summary(self, session: Session, *, instrument: ResolvedInstrument) -> QuotePriceSummary:
        if instrument.security_type == "stock":
            bar = session.scalar(
                select(EquityDailyBar)
                .where(EquityDailyBar.ts_code == instrument.ts_code)
                .order_by(desc(EquityDailyBar.trade_date))
                .limit(1)
            )
            if bar is None:
                return QuotePriceSummary()
            basic = session.scalar(
                select(EquityDailyBasic)
                .where(
                    EquityDailyBasic.ts_code == instrument.ts_code,
                    EquityDailyBasic.trade_date <= bar.trade_date,
                )
                .order_by(desc(EquityDailyBasic.trade_date))
                .limit(1)
            )
            return QuotePriceSummary(
                trade_date=bar.trade_date,
                latest_price=bar.close,
                pre_close=bar.pre_close,
                change_amount=bar.change_amount,
                pct_chg=bar.pct_chg,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                vol=bar.vol,
                amount=bar.amount,
                turnover_rate=basic.turnover_rate if basic else None,
                volume_ratio=basic.volume_ratio if basic else None,
                pe_ttm=basic.pe_ttm if basic else None,
                pb=basic.pb if basic else None,
                total_mv=basic.total_mv if basic else None,
                circ_mv=basic.circ_mv if basic else None,
            )

        if instrument.security_type == "index":
            bar = session.scalar(
                select(IndexDailyServing)
                .where(IndexDailyServing.ts_code == instrument.ts_code)
                .order_by(desc(IndexDailyServing.trade_date))
                .limit(1)
            )
            if bar is None:
                return QuotePriceSummary()
            basic = session.scalar(
                select(IndexDailyBasic)
                .where(
                    IndexDailyBasic.ts_code == instrument.ts_code,
                    IndexDailyBasic.trade_date <= bar.trade_date,
                )
                .order_by(desc(IndexDailyBasic.trade_date))
                .limit(1)
            )
            return QuotePriceSummary(
                trade_date=bar.trade_date,
                latest_price=bar.close,
                pre_close=bar.pre_close,
                change_amount=bar.change_amount,
                pct_chg=bar.pct_chg,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                vol=bar.vol,
                amount=bar.amount,
                turnover_rate=basic.turnover_rate if basic else None,
                pe_ttm=basic.pe_ttm if basic else None,
                pb=basic.pb if basic else None,
                total_mv=basic.total_mv if basic else None,
                circ_mv=basic.float_mv if basic else None,
            )

        bar = session.scalar(
            select(FundDailyBar)
            .where(FundDailyBar.ts_code == instrument.ts_code)
            .order_by(desc(FundDailyBar.trade_date))
            .limit(1)
        )
        if bar is None:
            return QuotePriceSummary()
        return QuotePriceSummary(
            trade_date=bar.trade_date,
            latest_price=bar.close,
            pre_close=bar.pre_close,
            change_amount=bar.change_amount,
            pct_chg=bar.pct_chg,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            vol=bar.vol,
            amount=bar.amount,
        )

    def _load_kline_points(
        self,
        session: Session,
        *,
        instrument: ResolvedInstrument,
        period: str,
        adjustment: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> list[KlinePoint]:
        clamped_limit = max(1, min(limit, 2000))
        if instrument.security_type == "stock":
            if period == "day":
                return self._load_stock_daily_points(
                    session,
                    ts_code=instrument.ts_code,
                    adjustment=adjustment,
                    start_date=start_date,
                    end_date=end_date,
                    limit=clamped_limit,
                )
            return self._load_stock_period_points(
                session,
                ts_code=instrument.ts_code,
                period=period,
                adjustment=adjustment,
                start_date=start_date,
                end_date=end_date,
                limit=clamped_limit,
            )

        if instrument.security_type == "index":
            return self._load_index_points(
                session,
                ts_code=instrument.ts_code,
                period=period,
                start_date=start_date,
                end_date=end_date,
                limit=clamped_limit,
            )

        if period != "day":
            raise ValueError("当前 ETF 仅支持日线")
        rows_stmt = (
            select(FundDailyBar)
            .where(FundDailyBar.ts_code == instrument.ts_code)
            .order_by(desc(FundDailyBar.trade_date))
            .limit(clamped_limit)
        )
        if start_date is not None:
            rows_stmt = rows_stmt.where(FundDailyBar.trade_date >= start_date)
        if end_date is not None:
            rows_stmt = rows_stmt.where(FundDailyBar.trade_date <= end_date)
        rows = list(reversed(list(session.scalars(rows_stmt).all())))
        return [
            KlinePoint(
                trade_date=row.trade_date,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                pre_close=row.pre_close,
                change_amount=row.change_amount,
                pct_chg=row.pct_chg,
                vol=row.vol,
                amount=row.amount,
            )
            for row in rows
        ]

    def _load_stock_daily_points(
        self,
        session: Session,
        *,
        ts_code: str,
        adjustment: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> list[KlinePoint]:
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
        rows = list(reversed(list(session.scalars(stmt).all())))
        if not rows:
            return []

        return self._build_stock_points_from_rows(
            session,
            ts_code=ts_code,
            adjustment=adjustment,
            rows=rows,
        )

    def _load_stock_daily_preheat_points(
        self,
        session: Session,
        *,
        ts_code: str,
        adjustment: str,
        before_trade_date: date,
        limit: int,
    ) -> list[KlinePoint]:
        rows = list(
            reversed(
                list(
                    session.scalars(
                        select(EquityDailyBar)
                        .where(
                            EquityDailyBar.ts_code == ts_code,
                            EquityDailyBar.trade_date < before_trade_date,
                        )
                        .order_by(desc(EquityDailyBar.trade_date))
                        .limit(limit)
                    ).all()
                )
            )
        )
        if not rows:
            return []
        return self._build_stock_points_from_rows(
            session,
            ts_code=ts_code,
            adjustment=adjustment,
            rows=rows,
        )

    def _build_stock_points_from_rows(
        self,
        session: Session,
        *,
        ts_code: str,
        adjustment: str,
        rows: list[EquityDailyBar],
    ) -> list[KlinePoint]:
        if not rows:
            return []
        turnover_by_date = self._load_stock_turnover_by_date(
            session,
            ts_code=ts_code,
            start=rows[0].trade_date,
            end=rows[-1].trade_date,
        )

        if adjustment == "none":
            return [
                KlinePoint(
                    trade_date=row.trade_date,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    pre_close=row.pre_close,
                    change_amount=row.change_amount,
                    pct_chg=row.pct_chg,
                    vol=row.vol,
                    amount=row.amount,
                    turnover_rate=turnover_by_date.get(row.trade_date),
                )
                for row in rows
            ]

        factor_map = self._load_stock_factor_map(
            session,
            ts_code=ts_code,
            start_date=rows[0].trade_date,
            end_date=rows[-1].trade_date,
        )
        missing_dates = [row.trade_date for row in rows if row.trade_date not in factor_map]
        if not factor_map or missing_dates:
            raise ValueError(
                self._build_adjustment_factor_incomplete_message(
                    ts_code=ts_code,
                    start_date=rows[0].trade_date,
                    end_date=rows[-1].trade_date,
                    missing_dates=missing_dates,
                )
            )

        anchor = self._load_stock_adjustment_anchor(session, ts_code=ts_code, adjustment=adjustment)
        if anchor is None or anchor == 0:
            raise ValueError(
                f"复权锚点缺失：{ts_code} {adjustment}。请先补齐复权因子后再请求复权行情。"
            )

        points: list[KlinePoint] = []
        for row in rows:
            factor = factor_map[row.trade_date]
            scale = factor / anchor
            points.append(
                KlinePoint(
                    trade_date=row.trade_date,
                    open=self._scale_price(row.open, scale),
                    high=self._scale_price(row.high, scale),
                    low=self._scale_price(row.low, scale),
                    close=self._scale_price(row.close, scale),
                    pre_close=self._scale_price(row.pre_close, scale),
                    change_amount=self._scale_price(row.change_amount, scale),
                    pct_chg=row.pct_chg,
                    vol=row.vol,
                    amount=row.amount,
                    turnover_rate=turnover_by_date.get(row.trade_date),
                )
            )
        return points

    def _load_stock_adjustment_anchor(
        self,
        session: Session,
        *,
        ts_code: str,
        adjustment: str,
    ) -> Decimal | None:
        if adjustment == "forward":
            return session.scalar(
                select(EquityAdjFactor.adj_factor)
                .where(EquityAdjFactor.ts_code == ts_code)
                .order_by(EquityAdjFactor.trade_date.desc())
                .limit(1)
            )
        return session.scalar(
            select(EquityAdjFactor.adj_factor)
            .where(EquityAdjFactor.ts_code == ts_code)
            .order_by(EquityAdjFactor.trade_date.asc())
            .limit(1)
        )

    def _load_stock_factor_map(
        self,
        session: Session,
        *,
        ts_code: str,
        start_date: date,
        end_date: date,
    ) -> dict[date, Decimal]:
        factors = session.scalars(
            select(EquityAdjFactor)
            .where(
                EquityAdjFactor.ts_code == ts_code,
                EquityAdjFactor.trade_date >= start_date,
                EquityAdjFactor.trade_date <= end_date,
            )
            .order_by(EquityAdjFactor.trade_date.asc())
        ).all()
        return {item.trade_date: item.adj_factor for item in factors if item.adj_factor is not None}

    def _load_stock_period_points(
        self,
        session: Session,
        *,
        ts_code: str,
        period: str,
        adjustment: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> list[KlinePoint]:
        freq = "week" if period == "week" else "month"
        if adjustment == "none":
            stmt = (
                select(StkPeriodBar)
                .where(
                    StkPeriodBar.ts_code == ts_code,
                    StkPeriodBar.freq == freq,
                )
                .order_by(desc(StkPeriodBar.trade_date))
                .limit(limit)
            )
            if start_date is not None:
                stmt = stmt.where(StkPeriodBar.trade_date >= start_date)
            if end_date is not None:
                stmt = stmt.where(StkPeriodBar.trade_date <= end_date)
            rows = list(reversed(list(session.scalars(stmt).all())))
            return [
                KlinePoint(
                    trade_date=row.trade_date,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    pre_close=row.pre_close,
                    change_amount=row.change_amount,
                    pct_chg=row.pct_chg,
                    vol=row.vol,
                    amount=row.amount,
                )
                for row in rows
            ]

        stmt_adj = (
            select(StkPeriodBarAdj)
            .where(
                StkPeriodBarAdj.ts_code == ts_code,
                StkPeriodBarAdj.freq == freq,
            )
            .order_by(desc(StkPeriodBarAdj.trade_date))
            .limit(limit)
        )
        if start_date is not None:
            stmt_adj = stmt_adj.where(StkPeriodBarAdj.trade_date >= start_date)
        if end_date is not None:
            stmt_adj = stmt_adj.where(StkPeriodBarAdj.trade_date <= end_date)
        rows_adj = list(reversed(list(session.scalars(stmt_adj).all())))
        points: list[KlinePoint] = []
        prev_close: Decimal | None = None
        for row in rows_adj:
            open_value = row.open_qfq if adjustment == "forward" else row.open_hfq
            high_value = row.high_qfq if adjustment == "forward" else row.high_hfq
            low_value = row.low_qfq if adjustment == "forward" else row.low_hfq
            close_value = row.close_qfq if adjustment == "forward" else row.close_hfq
            effective_pre_close = prev_close if prev_close is not None else row.pre_close
            change_amount = None
            if close_value is not None and effective_pre_close is not None:
                change_amount = (close_value - effective_pre_close).quantize(Decimal("0.0001"))
            points.append(
                KlinePoint(
                    trade_date=row.trade_date,
                    open=open_value,
                    high=high_value,
                    low=low_value,
                    close=close_value,
                    pre_close=effective_pre_close,
                    change_amount=change_amount,
                    pct_chg=row.pct_chg,
                    vol=row.vol,
                    amount=row.amount,
                )
            )
            prev_close = close_value
        return points

    def _load_index_points(
        self,
        session: Session,
        *,
        ts_code: str,
        period: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> list[KlinePoint]:
        if period == "day":
            stmt = (
                select(IndexDailyServing)
                .where(IndexDailyServing.ts_code == ts_code)
                .order_by(desc(IndexDailyServing.trade_date))
                .limit(limit)
            )
            if start_date is not None:
                stmt = stmt.where(IndexDailyServing.trade_date >= start_date)
            if end_date is not None:
                stmt = stmt.where(IndexDailyServing.trade_date <= end_date)
            rows = list(reversed(list(session.scalars(stmt).all())))
            if not rows:
                return []
            turnover_by_date = self._load_index_turnover_by_date(
                session,
                ts_code=ts_code,
                start=rows[0].trade_date,
                end=rows[-1].trade_date,
            )
            return [
                KlinePoint(
                    trade_date=row.trade_date,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    pre_close=row.pre_close,
                    change_amount=row.change_amount,
                    pct_chg=row.pct_chg,
                    vol=row.vol,
                    amount=row.amount,
                    turnover_rate=turnover_by_date.get(row.trade_date),
                )
                for row in rows
            ]

        model = IndexWeeklyServing if period == "week" else IndexMonthlyServing
        stmt = (
            select(model)
            .where(model.ts_code == ts_code)
            .order_by(desc(model.trade_date))
            .limit(limit)
        )
        if start_date is not None:
            stmt = stmt.where(model.trade_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(model.trade_date <= end_date)
        rows = list(reversed(list(session.scalars(stmt).all())))
        return [
            KlinePoint(
                trade_date=row.trade_date,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                pre_close=row.pre_close,
                change_amount=row.change_amount,
                pct_chg=row.pct_chg,
                vol=row.vol,
                amount=row.amount,
            )
            for row in rows
        ]

    def _load_stock_turnover_by_date(
        self,
        session: Session,
        *,
        ts_code: str,
        start: date,
        end: date,
    ) -> dict[date, Decimal]:
        rows = session.scalars(
            select(EquityDailyBasic)
            .where(
                EquityDailyBasic.ts_code == ts_code,
                EquityDailyBasic.trade_date >= start,
                EquityDailyBasic.trade_date <= end,
            )
        ).all()
        return {
            row.trade_date: row.turnover_rate
            for row in rows
            if row.turnover_rate is not None
        }

    def _load_index_turnover_by_date(
        self,
        session: Session,
        *,
        ts_code: str,
        start: date,
        end: date,
    ) -> dict[date, Decimal]:
        rows = session.scalars(
            select(IndexDailyBasic)
            .where(
                IndexDailyBasic.ts_code == ts_code,
                IndexDailyBasic.trade_date >= start,
                IndexDailyBasic.trade_date <= end,
            )
        ).all()
        return {
            row.trade_date: row.turnover_rate
            for row in rows
            if row.turnover_rate is not None
        }

    def _load_older_trade_date(
        self,
        session: Session,
        *,
        instrument: ResolvedInstrument,
        period: str,
        adjustment: str,
        first_trade_date: date,
    ) -> date | None:
        if instrument.security_type == "stock":
            if period == "day":
                row = session.scalar(
                    select(EquityDailyBar.trade_date)
                    .where(
                        EquityDailyBar.ts_code == instrument.ts_code,
                        EquityDailyBar.trade_date < first_trade_date,
                    )
                    .order_by(desc(EquityDailyBar.trade_date))
                    .limit(1)
                )
                return row
            freq = "week" if period == "week" else "month"
            model = StkPeriodBar if adjustment == "none" else StkPeriodBarAdj
            row = session.scalar(
                select(model.trade_date)
                .where(
                    model.ts_code == instrument.ts_code,
                    model.freq == freq,
                    model.trade_date < first_trade_date,
                )
                .order_by(desc(model.trade_date))
                .limit(1)
            )
            return row

        if instrument.security_type == "index":
            model = IndexDailyServing
            if period == "week":
                model = IndexWeeklyServing
            if period == "month":
                model = IndexMonthlyServing
            row = session.scalar(
                select(model.trade_date)
                .where(
                    model.ts_code == instrument.ts_code,
                    model.trade_date < first_trade_date,
                )
                .order_by(desc(model.trade_date))
                .limit(1)
            )
            return row

        row = session.scalar(
            select(FundDailyBar.trade_date)
            .where(
                FundDailyBar.ts_code == instrument.ts_code,
                FundDailyBar.trade_date < first_trade_date,
            )
            .order_by(desc(FundDailyBar.trade_date))
            .limit(1)
        )
        return row

    def _load_concepts(self, session: Session, *, ts_code: str, security_type: str) -> list[str]:
        if security_type != "stock":
            return []
        concepts: list[str] = []
        seen: set[str] = set()

        ths_rows = session.scalars(
            select(ThsMember)
            .where(ThsMember.ts_code == ts_code)
            .order_by(desc(ThsMember.updated_at))
            .limit(20)
        ).all()
        for row in ths_rows:
            name = (row.con_name or "").strip()
            if name and name not in seen:
                concepts.append(name)
                seen.add(name)

        latest_dc_date = session.scalar(
            select(func.max(DcMember.trade_date)).where(DcMember.ts_code == ts_code)
        )
        if latest_dc_date is not None:
            dc_rows = session.execute(
                select(DcIndex.name)
                .select_from(DcMember)
                .join(
                    DcIndex,
                    and_(
                        DcMember.con_code == DcIndex.ts_code,
                        DcMember.trade_date == DcIndex.trade_date,
                    ),
                )
                .where(
                    DcMember.ts_code == ts_code,
                    DcMember.trade_date == latest_dc_date,
                )
                .order_by(DcIndex.name.asc())
                .limit(20)
            ).all()
            for item in dc_rows:
                name = (item[0] or "").strip()
                if name and name not in seen:
                    concepts.append(name)
                    seen.add(name)

        latest_kpl_date = session.scalar(
            select(func.max(KplConceptCons.trade_date)).where(KplConceptCons.ts_code == ts_code)
        )
        if latest_kpl_date is not None:
            kpl_rows = session.scalars(
                select(KplConceptCons)
                .where(
                    KplConceptCons.ts_code == ts_code,
                    KplConceptCons.trade_date == latest_kpl_date,
                )
                .order_by(KplConceptCons.con_name.asc())
                .limit(20)
            ).all()
            for row in kpl_rows:
                name = (row.con_name or "").strip()
                if name and name not in seen:
                    concepts.append(name)
                    seen.add(name)

        return concepts

    def _attach_indicators(self, points: list[KlinePoint]) -> list[QuoteKlineBar]:
        closes = [self._to_float(item.close) for item in points]
        highs = [self._to_float(item.high) for item in points]
        lows = [self._to_float(item.low) for item in points]
        vols = [self._to_float(item.vol) for item in points]

        ma5 = self._sma(closes, 5)
        ma10 = self._sma(closes, 10)
        ma15 = self._sma(closes, 15)
        ma20 = self._sma(closes, 20)
        ma30 = self._sma(closes, 30)
        ma60 = self._sma(closes, 60)
        ma120 = self._sma(closes, 120)
        ma250 = self._sma(closes, 250)
        vol_ma5 = self._sma(vols, 5)
        vol_ma10 = self._sma(vols, 10)
        dif, dea, macd = self._macd(closes)
        k, d, j = self._kdj(highs, lows, closes)

        bars: list[QuoteKlineBar] = []
        for idx, point in enumerate(points):
            bars.append(
                QuoteKlineBar(
                    trade_date=point.trade_date,
                    open=point.open,
                    high=point.high,
                    low=point.low,
                    close=point.close,
                    pre_close=point.pre_close,
                    change_amount=point.change_amount,
                    pct_chg=point.pct_chg,
                    vol=point.vol,
                    amount=point.amount,
                    turnover_rate=point.turnover_rate,
                    ma5=self._to_decimal(ma5[idx]),
                    ma10=self._to_decimal(ma10[idx]),
                    ma15=self._to_decimal(ma15[idx]),
                    ma20=self._to_decimal(ma20[idx]),
                    ma30=self._to_decimal(ma30[idx]),
                    ma60=self._to_decimal(ma60[idx]),
                    ma120=self._to_decimal(ma120[idx]),
                    ma250=self._to_decimal(ma250[idx]),
                    volume_ma5=self._to_decimal(vol_ma5[idx], scale=2),
                    volume_ma10=self._to_decimal(vol_ma10[idx], scale=2),
                    macd=self._to_decimal(macd[idx]),
                    dif=self._to_decimal(dif[idx]),
                    dea=self._to_decimal(dea[idx]),
                    k=self._to_decimal(k[idx]),
                    d=self._to_decimal(d[idx]),
                    j=self._to_decimal(j[idx]),
                )
            )
        return bars

    @staticmethod
    def _to_instrument_schema(instrument: ResolvedInstrument) -> QuoteInstrument:
        return QuoteInstrument(
            instrument_id=instrument.instrument_id,
            ts_code=instrument.ts_code,
            symbol=instrument.symbol,
            name=instrument.name,
            market=instrument.market,
            security_type=instrument.security_type,
            exchange=instrument.exchange,
            industry=instrument.industry,
            list_status=instrument.list_status,
        )

    @staticmethod
    def _scale_price(value: Decimal | None, scale: Decimal) -> Decimal | None:
        if value is None:
            return None
        return value * scale

    @staticmethod
    def _to_float(value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _to_decimal(value: float | None, *, scale: int = 4) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    @staticmethod
    def _quantize_decimal_4(value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _build_adjustment_factor_incomplete_message(
        *,
        ts_code: str,
        start_date: date,
        end_date: date,
        missing_dates: list[date],
    ) -> str:
        if not missing_dates:
            return (
                f"复权因子缺失：{ts_code} 在 {start_date.isoformat()}~{end_date.isoformat()} "
                "区间内未找到可用复权因子。请先同步复权因子后再请求复权行情。"
            )
        missing_count = len(missing_dates)
        sample = ", ".join(item.isoformat() for item in missing_dates[:3])
        suffix = "..." if missing_count > 3 else ""
        return (
            f"复权因子不完整：{ts_code} 在 {start_date.isoformat()}~{end_date.isoformat()} "
            f"区间缺失 {missing_count} 个交易日因子（示例：{sample}{suffix}）。"
            "请先同步复权因子后再请求复权行情。"
        )

    def _round_kline_bars_for_response(self, bars: list[QuoteKlineBar]) -> list[QuoteKlineBar]:
        for bar in bars:
            bar.open = self._quantize_decimal_4(bar.open)
            bar.high = self._quantize_decimal_4(bar.high)
            bar.low = self._quantize_decimal_4(bar.low)
            bar.close = self._quantize_decimal_4(bar.close)
            bar.pre_close = self._quantize_decimal_4(bar.pre_close)
            bar.change_amount = self._quantize_decimal_4(bar.change_amount)
            bar.pct_chg = self._quantize_decimal_4(bar.pct_chg)
            bar.vol = self._quantize_decimal_4(bar.vol)
            bar.amount = self._quantize_decimal_4(bar.amount)
            bar.turnover_rate = self._quantize_decimal_4(bar.turnover_rate)
            bar.ma5 = self._quantize_decimal_4(bar.ma5)
            bar.ma10 = self._quantize_decimal_4(bar.ma10)
            bar.ma15 = self._quantize_decimal_4(bar.ma15)
            bar.ma20 = self._quantize_decimal_4(bar.ma20)
            bar.ma30 = self._quantize_decimal_4(bar.ma30)
            bar.ma60 = self._quantize_decimal_4(bar.ma60)
            bar.ma120 = self._quantize_decimal_4(bar.ma120)
            bar.ma250 = self._quantize_decimal_4(bar.ma250)
            bar.volume_ma5 = self._quantize_decimal_4(bar.volume_ma5)
            bar.volume_ma10 = self._quantize_decimal_4(bar.volume_ma10)
            bar.macd = self._quantize_decimal_4(bar.macd)
            bar.dif = self._quantize_decimal_4(bar.dif)
            bar.dea = self._quantize_decimal_4(bar.dea)
            bar.k = self._quantize_decimal_4(bar.k)
            bar.d = self._quantize_decimal_4(bar.d)
            bar.j = self._quantize_decimal_4(bar.j)
        return bars

    def _round_price_summary(self, summary: QuotePriceSummary) -> QuotePriceSummary:
        summary.latest_price = self._quantize_decimal_4(summary.latest_price)
        summary.pre_close = self._quantize_decimal_4(summary.pre_close)
        summary.change_amount = self._quantize_decimal_4(summary.change_amount)
        summary.pct_chg = self._quantize_decimal_4(summary.pct_chg)
        summary.open = self._quantize_decimal_4(summary.open)
        summary.high = self._quantize_decimal_4(summary.high)
        summary.low = self._quantize_decimal_4(summary.low)
        summary.vol = self._quantize_decimal_4(summary.vol)
        summary.amount = self._quantize_decimal_4(summary.amount)
        summary.turnover_rate = self._quantize_decimal_4(summary.turnover_rate)
        summary.volume_ratio = self._quantize_decimal_4(summary.volume_ratio)
        summary.pe_ttm = self._quantize_decimal_4(summary.pe_ttm)
        summary.pb = self._quantize_decimal_4(summary.pb)
        summary.total_mv = self._quantize_decimal_4(summary.total_mv)
        summary.circ_mv = self._quantize_decimal_4(summary.circ_mv)
        return summary

    def _round_chart_header_defaults(self, defaults: QuoteChartHeaderDefaults) -> QuoteChartHeaderDefaults:
        defaults.ma5 = self._quantize_decimal_4(defaults.ma5)
        defaults.ma10 = self._quantize_decimal_4(defaults.ma10)
        defaults.ma15 = self._quantize_decimal_4(defaults.ma15)
        defaults.ma20 = self._quantize_decimal_4(defaults.ma20)
        defaults.ma30 = self._quantize_decimal_4(defaults.ma30)
        defaults.ma60 = self._quantize_decimal_4(defaults.ma60)
        defaults.ma120 = self._quantize_decimal_4(defaults.ma120)
        defaults.ma250 = self._quantize_decimal_4(defaults.ma250)
        defaults.volume_ma5 = self._quantize_decimal_4(defaults.volume_ma5)
        defaults.volume_ma10 = self._quantize_decimal_4(defaults.volume_ma10)
        defaults.macd = self._quantize_decimal_4(defaults.macd)
        defaults.dif = self._quantize_decimal_4(defaults.dif)
        defaults.dea = self._quantize_decimal_4(defaults.dea)
        defaults.k = self._quantize_decimal_4(defaults.k)
        defaults.d = self._quantize_decimal_4(defaults.d)
        defaults.j = self._quantize_decimal_4(defaults.j)
        return defaults

    @staticmethod
    def _sma(values: list[float | None], period: int) -> list[float | None]:
        result: list[float | None] = [None] * len(values)
        window_sum = 0.0
        valid_count = 0
        for i, value in enumerate(values):
            if value is not None:
                window_sum += value
                valid_count += 1
            old_idx = i - period
            if old_idx >= 0:
                old_value = values[old_idx]
                if old_value is not None:
                    window_sum -= old_value
                    valid_count -= 1
            if i >= period - 1 and valid_count == period:
                result[i] = window_sum / period
        return result

    @staticmethod
    def _ema(values: list[float | None], period: int) -> list[float | None]:
        result: list[float | None] = []
        alpha = 2.0 / (period + 1.0)
        prev: float | None = None
        for value in values:
            if value is None:
                result.append(None)
                continue
            if prev is None:
                prev = value
            else:
                prev = alpha * value + (1.0 - alpha) * prev
            result.append(prev)
        return result

    def _macd(self, closes: list[float | None]) -> tuple[list[float | None], list[float | None], list[float | None]]:
        ema12 = self._ema(closes, 12)
        ema26 = self._ema(closes, 26)
        dif: list[float | None] = []
        for idx in range(len(closes)):
            if ema12[idx] is None or ema26[idx] is None:
                dif.append(None)
            else:
                dif.append(ema12[idx] - ema26[idx])
        dea = self._ema(dif, 9)
        macd: list[float | None] = []
        for idx in range(len(closes)):
            if dif[idx] is None or dea[idx] is None:
                macd.append(None)
            else:
                macd.append((dif[idx] - dea[idx]) * 2.0)
        return dif, dea, macd

    @staticmethod
    def _kdj(
        highs: list[float | None],
        lows: list[float | None],
        closes: list[float | None],
    ) -> tuple[list[float | None], list[float | None], list[float | None]]:
        k_values: list[float | None] = []
        d_values: list[float | None] = []
        j_values: list[float | None] = []
        prev_k = 50.0
        prev_d = 50.0
        for idx, close_value in enumerate(closes):
            start = max(0, idx - 8)
            window_highs = [item for item in highs[start: idx + 1] if item is not None]
            window_lows = [item for item in lows[start: idx + 1] if item is not None]
            if close_value is None or not window_highs or not window_lows:
                k_values.append(None)
                d_values.append(None)
                j_values.append(None)
                continue
            high_max = max(window_highs)
            low_min = min(window_lows)
            rsv = 50.0 if high_max == low_min else ((close_value - low_min) / (high_max - low_min) * 100.0)
            current_k = (2.0 / 3.0) * prev_k + (1.0 / 3.0) * rsv
            current_d = (2.0 / 3.0) * prev_d + (1.0 / 3.0) * current_k
            current_j = 3.0 * current_k - 2.0 * current_d
            k_values.append(current_k)
            d_values.append(current_d)
            j_values.append(current_j)
            prev_k, prev_d = current_k, current_d
        return k_values, d_values, j_values
