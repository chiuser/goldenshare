from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.news_briefs import (
    MarketNewsDebugInfoDto,
    NewsBriefsResponseDto,
    NewsListPanelDto,
    NewsPanelItemDto,
    PageStatusDto,
    TradingDayDto,
)
from src.biz.schemas.wealth.market.stock_news import StockNewsResponseDto
from src.biz.services.wealth.config import StrategyConfigNotFoundError, StrategyConfigValidationError
from src.biz.services.wealth.market.news.news_exception_builder import MarketNewsExceptionBuilder
from src.biz.services.wealth.market.news.news_status_resolver import MarketNewsStatusResolver
from src.biz.services.wealth.market.news.news_strategy_config_resolver import (
    MarketNewsStrategyConfig,
    MarketNewsStrategyConfigResolver,
)

from .market_news_query import MarketNewsQuery, NewsQueryResult
from .news_state_query import NewsStateQuery, NewsTradingDayContext
from .stock_news_query import StockNewsQuery


PanelKey = Literal["newsBriefs", "stockNews"]
Category = Literal["market", "stock"]


@dataclass(frozen=True, slots=True)
class _PanelRequest:
    panel_key: PanelKey
    module_key: str
    category: Category


class MarketNewsQueryService:
    """Orchestrate news briefs and stock news responses."""

    def __init__(self) -> None:
        self._state_query = NewsStateQuery()
        self._market_news_query = MarketNewsQuery()
        self._stock_news_query = StockNewsQuery()
        self._strategy_resolver = MarketNewsStrategyConfigResolver()
        self._status_resolver = MarketNewsStatusResolver()
        self._exception_builder = MarketNewsExceptionBuilder()

    def build_news_briefs(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> NewsBriefsResponseDto:
        panel_request = _PanelRequest(panel_key="newsBriefs", module_key="newsBriefs", category="market")
        trading_day_context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        panel, page_status, debug_info = self._build_panel(
            session,
            panel_request=panel_request,
            trading_day_context=trading_day_context,
            debug=debug,
        )
        return NewsBriefsResponseDto(
            tradingDay=self._build_trading_day(trading_day_context),
            pageStatus=page_status,
            newsBriefs=panel,
            debugInfo=debug_info if debug else None,
        )

    def build_stock_news(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> StockNewsResponseDto:
        panel_request = _PanelRequest(panel_key="stockNews", module_key="stockNews", category="stock")
        trading_day_context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        panel, page_status, debug_info = self._build_panel(
            session,
            panel_request=panel_request,
            trading_day_context=trading_day_context,
            debug=debug,
        )
        return StockNewsResponseDto(
            tradingDay=self._build_trading_day(trading_day_context),
            pageStatus=page_status,
            stockNews=panel,
            debugInfo=debug_info if debug else None,
        )

    def _build_panel(
        self,
        session: Session,
        *,
        panel_request: _PanelRequest,
        trading_day_context: NewsTradingDayContext,
        debug: bool,
    ) -> tuple[NewsListPanelDto, PageStatusDto, MarketNewsDebugInfoDto | None]:
        exceptions = []
        try:
            strategy = self._strategy_resolver.resolve(market=trading_day_context.market)
        except StrategyConfigNotFoundError as exc:
            exceptions.append(self._exception_builder.config_missing(message=str(exc)))
            return self._build_error_panel(
                panel_request=panel_request,
                trading_day_context=trading_day_context,
                message="news config missing",
                exceptions=exceptions,
                debug=debug,
            )
        except StrategyConfigValidationError as exc:
            exceptions.append(self._exception_builder.config_invalid(message=str(exc)))
            return self._build_error_panel(
                panel_request=panel_request,
                trading_day_context=trading_day_context,
                message="news config invalid",
                exceptions=exceptions,
                debug=debug,
            )

        try:
            query_result = self._load_query_result(
                session,
                panel_key=panel_request.panel_key,
                trade_date=trading_day_context.expected_trade_date,
                strategy=strategy,
            )
        except Exception as exc:  # noqa: BLE001
            exceptions.append(
                self._exception_builder.query_failed(message=f"news query failed: {exc}", panel_key=panel_request.panel_key)
            )
            return self._build_error_panel(
                panel_request=panel_request,
                trading_day_context=trading_day_context,
                message="news query failed",
                exceptions=exceptions,
                debug=debug,
            )

        status_result = self._status_resolver.resolve(
            module_key=panel_request.module_key,
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=query_result.observed_trade_date,
            row_count=len(query_result.rows),
            as_of_time=trading_day_context.as_of_time,
        )
        if status_result.module_status.status == "EMPTY":
            exceptions.append(
                self._exception_builder.source_empty(
                    message="target date has no displayable news",
                    panel_key=panel_request.panel_key,
                    target_trade_date=str(trading_day_context.expected_trade_date),
                )
            )
        elif status_result.module_status.status == "DELAYED" and query_result.observed_trade_date is not None:
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="news source date lagged",
                    panel_key=panel_request.panel_key,
                    expected_trade_date=str(trading_day_context.expected_trade_date),
                    observed_trade_date=str(query_result.observed_trade_date),
                )
            )

        panel = self._build_panel_dto(
            panel_request=panel_request,
            trading_day_context=trading_day_context,
            strategy=strategy,
            query_result=query_result,
        )
        return (
            panel,
            status_result.page_status,
            MarketNewsDebugInfoDto(modules=[status_result.module_status], exceptions=exceptions) if debug else None,
        )

    def _load_query_result(
        self,
        session: Session,
        *,
        panel_key: PanelKey,
        trade_date: date,
        strategy: MarketNewsStrategyConfig,
    ) -> NewsQueryResult:
        if panel_key == "newsBriefs":
            return self._market_news_query.load_rows(session, trade_date=trade_date, limit=strategy.query_limit)
        return self._stock_news_query.load_rows(session, trade_date=trade_date, limit=strategy.query_limit)

    def _build_panel_dto(
        self,
        *,
        panel_request: _PanelRequest,
        trading_day_context: NewsTradingDayContext,
        strategy: MarketNewsStrategyConfig,
        query_result: NewsQueryResult,
    ) -> NewsListPanelDto:
        return NewsListPanelDto(
            tradeDate=trading_day_context.expected_trade_date,
            panelKey=panel_request.panel_key,
            visibleItemCount=strategy.visible_item_count,
            updatedAt=trading_day_context.as_of_time,
            items=[
                NewsPanelItemDto(
                    newsId=row.news_id,
                    publishTime=row.publish_time,
                    displayTime=row.publish_time.strftime("%m-%d %H:%M:%S"),
                    title=row.title,
                    category=panel_request.category,
                    source=row.source,
                    subject=None,
                    priority=0,
                    url=None,
                    clickable=False,
                )
                for row in query_result.rows
            ],
        )

    def _build_error_panel(
        self,
        *,
        panel_request: _PanelRequest,
        trading_day_context: NewsTradingDayContext,
        message: str,
        exceptions: list,
        debug: bool,
    ) -> tuple[NewsListPanelDto, PageStatusDto, MarketNewsDebugInfoDto | None]:
        module_status = self._status_resolver.resolve(
            module_key=panel_request.module_key,
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=None,
            row_count=0,
            as_of_time=trading_day_context.as_of_time,
        ).module_status.model_copy(update={"status": "ERROR", "note": message})
        panel = NewsListPanelDto(
            tradeDate=trading_day_context.expected_trade_date,
            panelKey=panel_request.panel_key,
            visibleItemCount=10,
            updatedAt=trading_day_context.as_of_time,
            items=[],
        )
        return (
            panel,
            PageStatusDto(status="ERROR", displayText="模块查询失败", asOfTime=trading_day_context.as_of_time),
            MarketNewsDebugInfoDto(modules=[module_status], exceptions=exceptions) if debug else None,
        )

    @staticmethod
    def _build_trading_day(trading_day_context: NewsTradingDayContext) -> TradingDayDto:
        return TradingDayDto(
            tradeDate=trading_day_context.expected_trade_date,
            prevTradeDate=trading_day_context.prev_trade_date,
            market="CN_A",
            isTradingDay=trading_day_context.is_trading_day,
            sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
            timezone="Asia/Shanghai",
        )
