from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.news_common import NewsCategoryValue, NewsPanelKeyValue
from src.biz.schemas.wealth.market.news_briefs import (
    MarketNewsDebugInfoDto,
    NewsWindowDto,
    NewsBriefsResponseDto,
    NewsListPanelDto,
    NewsPanelItemDto,
    PageStatusDto,
)
from src.biz.schemas.wealth.market.news_communications import NewsCommunicationsResponseDto
from src.biz.services.wealth.config import StrategyConfigNotFoundError, StrategyConfigValidationError
from src.biz.services.wealth.market.news.news_exception_builder import MarketNewsExceptionBuilder
from src.biz.services.wealth.market.news.news_status_resolver import MarketNewsStatusResolver
from src.biz.services.wealth.market.news.news_strategy_config_resolver import (
    MarketNewsStrategyConfig,
    MarketNewsStrategyConfigResolver,
)

from .market_news_query import MarketNewsQuery, NewsQueryResult
from .major_news_query import MajorNewsQuery
from .news_state_query import NewsStateQuery, NewsWindowContext


@dataclass(frozen=True, slots=True)
class _PanelRequest:
    panel_key: NewsPanelKeyValue
    module_key: str
    category: NewsCategoryValue


class MarketNewsQueryService:
    """Orchestrate news briefs and long-form communications responses."""

    def __init__(self) -> None:
        self._state_query = NewsStateQuery()
        self._market_news_query = MarketNewsQuery()
        self._major_news_query = MajorNewsQuery()
        self._strategy_resolver = MarketNewsStrategyConfigResolver()
        self._status_resolver = MarketNewsStatusResolver()
        self._exception_builder = MarketNewsExceptionBuilder()

    def build_news_briefs(
        self,
        session: Session,
        *,
        market: str,
        debug: bool,
    ) -> NewsBriefsResponseDto:
        panel_request = _PanelRequest(panel_key="newsBriefs", module_key="newsBriefs", category="brief")
        news_window_context = self._state_query.resolve_news_window(
            market=market,
        )
        panel, page_status, debug_info = self._build_panel(
            session,
            panel_request=panel_request,
            news_window_context=news_window_context,
            debug=debug,
        )
        return NewsBriefsResponseDto(
            newsWindow=self._build_news_window(news_window_context),
            pageStatus=page_status,
            newsBriefs=panel,
            debugInfo=debug_info if debug else None,
        )

    def build_news_communications(
        self,
        session: Session,
        *,
        market: str,
        debug: bool,
    ) -> NewsCommunicationsResponseDto:
        panel_request = _PanelRequest(
            panel_key="newsCommunications",
            module_key="newsCommunications",
            category="communication",
        )
        news_window_context = self._state_query.resolve_news_window(
            market=market,
        )
        panel, page_status, debug_info = self._build_panel(
            session,
            panel_request=panel_request,
            news_window_context=news_window_context,
            debug=debug,
        )
        return NewsCommunicationsResponseDto(
            newsWindow=self._build_news_window(news_window_context),
            pageStatus=page_status,
            newsCommunications=panel,
            debugInfo=debug_info if debug else None,
        )

    def _build_panel(
        self,
        session: Session,
        *,
        panel_request: _PanelRequest,
        news_window_context: NewsWindowContext,
        debug: bool,
    ) -> tuple[NewsListPanelDto, PageStatusDto, MarketNewsDebugInfoDto | None]:
        exceptions = []
        try:
            strategy = self._strategy_resolver.resolve(market=news_window_context.market)
        except StrategyConfigNotFoundError as exc:
            exceptions.append(self._exception_builder.config_missing(message=str(exc)))
            return self._build_error_panel(
                panel_request=panel_request,
                news_window_context=news_window_context,
                message="news config missing",
                exceptions=exceptions,
                debug=debug,
            )
        except StrategyConfigValidationError as exc:
            exceptions.append(self._exception_builder.config_invalid(message=str(exc)))
            return self._build_error_panel(
                panel_request=panel_request,
                news_window_context=news_window_context,
                message="news config invalid",
                exceptions=exceptions,
                debug=debug,
            )

        try:
            query_result = self._load_query_result(
                session,
                panel_key=panel_request.panel_key,
                window_start_at=news_window_context.window_start_at,
                window_end_at=news_window_context.window_end_at,
                strategy=strategy,
            )
        except Exception as exc:  # noqa: BLE001
            exceptions.append(
                self._exception_builder.query_failed(message=f"news query failed: {exc}", panel_key=panel_request.panel_key)
            )
            return self._build_error_panel(
                panel_request=panel_request,
                news_window_context=news_window_context,
                message="news query failed",
                exceptions=exceptions,
                debug=debug,
            )

        status_result = self._status_resolver.resolve(
            module_key=panel_request.module_key,
            window_start_at=news_window_context.window_start_at,
            window_end_at=news_window_context.window_end_at,
            observed_at=query_result.observed_at,
            row_count=len(query_result.rows),
            as_of_time=news_window_context.as_of_time,
        )
        if status_result.module_status.status == "EMPTY":
            exceptions.append(
                self._exception_builder.source_empty(
                    message="news window has no displayable news",
                    panel_key=panel_request.panel_key,
                    window_start_at=news_window_context.window_start_at.isoformat(),
                    window_end_at=news_window_context.window_end_at.isoformat(),
                )
            )
        elif status_result.module_status.status == "DELAYED" and query_result.observed_at is not None:
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="news source date lagged",
                    panel_key=panel_request.panel_key,
                    window_start_at=news_window_context.window_start_at.isoformat(),
                    observed_at=query_result.observed_at.isoformat(),
                )
            )

        panel = self._build_panel_dto(
            panel_request=panel_request,
            news_window_context=news_window_context,
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
        panel_key: NewsPanelKeyValue,
        window_start_at: datetime,
        window_end_at: datetime,
        strategy: MarketNewsStrategyConfig,
    ) -> NewsQueryResult:
        if panel_key == "newsBriefs":
            return self._market_news_query.load_rows(
                session,
                window_start_at=window_start_at,
                window_end_at=window_end_at,
                limit=strategy.query_limit,
            )
        if panel_key == "newsCommunications":
            return self._major_news_query.load_rows(
                session,
                window_start_at=window_start_at,
                window_end_at=window_end_at,
                limit=strategy.query_limit,
            )
        raise AssertionError(f"unsupported news panel key: {panel_key}")

    def _build_panel_dto(
        self,
        *,
        panel_request: _PanelRequest,
        news_window_context: NewsWindowContext,
        strategy: MarketNewsStrategyConfig,
        query_result: NewsQueryResult,
    ) -> NewsListPanelDto:
        return NewsListPanelDto(
            windowStartAt=news_window_context.window_start_at,
            windowEndAt=news_window_context.window_end_at,
            panelKey=panel_request.panel_key,
            visibleItemCount=strategy.visible_item_count,
            updatedAt=news_window_context.as_of_time,
            items=[
                NewsPanelItemDto(
                    newsId=row.news_id,
                    contentSource=row.content_source,
                    publishTime=row.publish_time,
                    displayTime=row.publish_time.strftime("%m-%d %H:%M:%S"),
                    title=row.title,
                    category=panel_request.category,
                    source=row.source,
                    readerMode=row.reader_mode,
                    clickable=True,
                )
                for row in query_result.rows
            ],
        )

    def _build_error_panel(
        self,
        *,
        panel_request: _PanelRequest,
        news_window_context: NewsWindowContext,
        message: str,
        exceptions: list,
        debug: bool,
    ) -> tuple[NewsListPanelDto, PageStatusDto, MarketNewsDebugInfoDto | None]:
        module_status = self._status_resolver.resolve(
            module_key=panel_request.module_key,
            window_start_at=news_window_context.window_start_at,
            window_end_at=news_window_context.window_end_at,
            observed_at=None,
            row_count=0,
            as_of_time=news_window_context.as_of_time,
        ).module_status.model_copy(update={"status": "ERROR", "note": message})
        panel = NewsListPanelDto(
            windowStartAt=news_window_context.window_start_at,
            windowEndAt=news_window_context.window_end_at,
            panelKey=panel_request.panel_key,
            visibleItemCount=10,
            updatedAt=news_window_context.as_of_time,
            items=[],
        )
        return (
            panel,
            PageStatusDto(status="ERROR", displayText="模块查询失败", asOfTime=news_window_context.as_of_time),
            MarketNewsDebugInfoDto(modules=[module_status], exceptions=exceptions) if debug else None,
        )

    @staticmethod
    def _build_news_window(news_window_context: NewsWindowContext) -> NewsWindowDto:
        return NewsWindowDto(
            market="CN_A",
            startAt=news_window_context.window_start_at,
            endAt=news_window_context.window_end_at,
            timezone="Asia/Shanghai",
        )
