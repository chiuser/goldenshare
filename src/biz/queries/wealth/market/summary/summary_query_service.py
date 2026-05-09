from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.summary import (
    MarketSummaryDebugInfoDto,
    MarketSummaryDefinitionDto,
    MarketSummaryPayloadDto,
    MarketSummaryResponseDto,
    MarketSummaryTextCardDto,
    ModuleExceptionItemDto,
    ModuleStatusItemDto,
    PageStatusDto,
    TradingDayDto,
)
from src.biz.services.wealth.config import MajorIndicesStrategyPayload, StrategyConfigService
from src.biz.services.wealth.market.summary.summary_card_builder import SummaryCardBuilder
from src.biz.services.wealth.market.summary.summary_definition_registry import (
    MarketSummaryDefinitionError,
    SummaryDefinitionRegistry,
)
from src.biz.services.wealth.market.summary.summary_exception_builder import SummaryExceptionBuilder
from src.biz.services.wealth.market.summary.summary_status_resolver import SummaryStatusResolver
from src.biz.services.wealth.market.summary.summary_text_renderer import SummaryTextRenderer
from .summary_metrics_query import SummaryMetricsQuery
from .summary_state_query import SummaryStateQuery, TradingDayContext


class MarketSummaryQueryService:
    """Orchestrate market summary module response assembly."""

    def __init__(self) -> None:
        self._config_service = StrategyConfigService()
        self._state_query = SummaryStateQuery()
        self._metrics_query = SummaryMetricsQuery()
        self._definition_registry = SummaryDefinitionRegistry(config_service=self._config_service)
        self._card_builder = SummaryCardBuilder()
        self._text_renderer = SummaryTextRenderer()
        self._status_resolver = SummaryStatusResolver()
        self._exception_builder = SummaryExceptionBuilder()

    def build_summary(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> MarketSummaryResponseDto:
        exceptions = []

        trading_day_context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        major_index_codes = self._load_major_index_codes(market=market)
        source_state = self._state_query.load_source_state(session, index_codes=major_index_codes)
        status_result = self._status_resolver.resolve(
            expected_trade_date=trading_day_context.expected_trade_date,
            source_state=source_state,
            as_of_time=trading_day_context.as_of_time,
        )

        for source_key in status_result.missing_sources:
            exceptions.append(
                self._exception_builder.source_empty(
                    message=f"{source_key} source is empty",
                    source_key=source_key,
                )
            )
        if status_result.module_status.status == "DELAYED" and status_result.module_status.observedTradeDate is not None:
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="summary key source is delayed",
                    expected_trade_date=status_result.module_status.expectedTradeDate.isoformat(),
                    observed_trade_date=status_result.module_status.observedTradeDate.isoformat(),
                )
            )

        try:
            definition = self._definition_registry.get_definition(market=market)
        except MarketSummaryDefinitionError as exc:
            exceptions.append(self._exception_builder.config_missing(message=str(exc)))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                module_status=status_result.module_status,
                debug=debug,
                exceptions=exceptions,
            )

        metrics = self._metrics_query.load(
            session,
            trade_date=trading_day_context.expected_trade_date,
            prev_trade_date=trading_day_context.prev_trade_date,
            index_codes=major_index_codes,
        )
        card_result = self._card_builder.build(card_keys=definition.enabled_card_keys, metrics=metrics)
        if len(card_result.cards) != definition.card_count:
            exceptions.append(
                self._exception_builder.card_count_invalid(
                    message="cardCount and built cards mismatch",
                )
            )
            return self._build_error_response(
                trading_day_context=trading_day_context,
                module_status=ModuleStatusItemDto(
                    moduleKey="marketSummary",
                    expectedTradeDate=trading_day_context.expected_trade_date,
                    observedTradeDate=status_result.module_status.observedTradeDate,
                    lagDays=status_result.module_status.lagDays,
                    status="ERROR",
                    note="card count mismatch",
                ),
                debug=debug,
                exceptions=exceptions,
            )

        text_result = self._text_renderer.render(
            definition=definition,
            session_status=trading_day_context.session_status,
            variables=card_result.template_variables,
        )
        if text_result.used_fallback:
            exceptions.append(
                self._exception_builder.text_render_failed(
                    message="summary text render fallback applied",
                    reason=text_result.failure_reason or "unknown",
                )
            )

        module_status = status_result.module_status
        if module_status.status == "READY" and text_result.used_fallback:
            module_status = ModuleStatusItemDto(
                moduleKey=module_status.moduleKey,
                expectedTradeDate=module_status.expectedTradeDate,
                observedTradeDate=module_status.observedTradeDate,
                lagDays=module_status.lagDays,
                status="PARTIAL",
                note="text template fallback applied",
            )

        payload = MarketSummaryPayloadDto(
            definition=MarketSummaryDefinitionDto(
                definitionKey=definition.definition_key,
                version=definition.version,
                cardCount=definition.card_count,
                layoutVariant=definition.layout_variant,
            ),
            cards=card_result.cards,
            textCard=MarketSummaryTextCardDto(
                title=text_result.title,
                content=text_result.content,
                templateKey=text_result.template_key,
            ),
        )

        response = MarketSummaryResponseDto(
            tradingDay=TradingDayDto(
                tradeDate=trading_day_context.expected_trade_date,
                prevTradeDate=trading_day_context.prev_trade_date,
                market="CN_A",
                isTradingDay=trading_day_context.is_trading_day,
                sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
                timezone="Asia/Shanghai",
            ),
            pageStatus=status_result.page_status,
            marketSummary=payload,
            debugInfo=(
                MarketSummaryDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )
        return response

    def _build_error_response(
        self,
        *,
        trading_day_context: TradingDayContext,
        module_status: ModuleStatusItemDto,
        debug: bool,
        exceptions: list[ModuleExceptionItemDto],
    ) -> MarketSummaryResponseDto:
        return MarketSummaryResponseDto(
            tradingDay=TradingDayDto(
                tradeDate=trading_day_context.expected_trade_date,
                prevTradeDate=trading_day_context.prev_trade_date,
                market="CN_A",
                isTradingDay=trading_day_context.is_trading_day,
                sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
                timezone="Asia/Shanghai",
            ),
            pageStatus=PageStatusDto(
                status="ERROR",
                displayText="模块加载失败",
                asOfTime=trading_day_context.as_of_time,
            ),
            marketSummary=MarketSummaryPayloadDto(
                definition=MarketSummaryDefinitionDto(
                    definitionKey="CN_A_SUMMARY_V1",
                    version="0.0.0",
                    cardCount=5,
                    layoutVariant="FIVE_SINGLE_ROW",
                ),
                cards=[],
                textCard=MarketSummaryTextCardDto(
                    title="今日市场客观总结",
                    content="当前可用数据不足，暂仅展示已确认的客观事实。",
                    templateKey="fallback",
                ),
            ),
            debugInfo=(
                MarketSummaryDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )

    def _load_major_index_codes(self, *, market: str) -> list[str]:
        payload = self._config_service.get_payload(module_key="majorIndices", market=market)
        if isinstance(payload, MajorIndicesStrategyPayload):
            return list(payload.index_codes)
        return []
