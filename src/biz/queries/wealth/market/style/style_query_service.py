from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.style import (
    MarketStyleCardDto,
    MarketStyleDebugInfoDto,
    MarketStyleDefinitionDto,
    MarketStyleHistoryPointDto,
    MarketStylePayloadDto,
    MarketStyleResponseDto,
    ModuleStatusItemDto,
    PageStatusDto,
    TradingDayDto,
)
from src.biz.services.wealth.config import (
    MarketStyleStrategyPayload,
    StrategyConfigNotFoundError,
    StrategyConfigService,
    StrategyConfigValidationError,
)
from src.biz.services.wealth.market.style.style_exception_builder import MarketStyleExceptionBuilder
from src.biz.services.wealth.market.style.style_status_resolver import MarketStyleStatusResolver
from .style_query import MarketStyleCurrentSnapshot, MarketStyleHistoryPoint, MarketStyleQuery
from .style_state_query import MarketStyleSourceState, MarketStyleStateQuery, MarketStyleTradingDayContext


_DEFAULT_DEFINITION_KEY = "CN_A_MARKET_STYLE_V1"


@dataclass(frozen=True, slots=True)
class MarketStyleDefinition:
    definition_key: str
    version: str
    one_month_days: int
    three_month_days: int
    large_index_code: str
    small_index_code: str
    large_label: str
    small_label: str
    median_label: str
    large_source_text: str
    small_source_text: str
    median_source_text: str


class MarketStyleQueryService:
    """Orchestrate market style module response assembly."""

    def __init__(self) -> None:
        self._config_service = StrategyConfigService()
        self._state_query = MarketStyleStateQuery()
        self._query = MarketStyleQuery()
        self._status_resolver = MarketStyleStatusResolver()
        self._exception_builder = MarketStyleExceptionBuilder()

    def build_style(
        self,
        session: Session,
        *,
        market: str,
        trade_date: date | None,
        debug: bool,
    ) -> MarketStyleResponseDto:
        exceptions = []
        trading_day_context = self._state_query.resolve_trading_day(
            session,
            market=market,
            requested_trade_date=trade_date,
        )
        try:
            definition = self._load_definition(market=market)
        except StrategyConfigNotFoundError as exc:
            exceptions.append(self._exception_builder.config_missing(message=str(exc)))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                source_state=MarketStyleSourceState(index_source_date=None, equity_source_date=None),
                debug=debug,
                exceptions=exceptions,
            )
        except StrategyConfigValidationError as exc:
            exceptions.append(self._exception_builder.config_invalid(message=str(exc)))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                source_state=MarketStyleSourceState(index_source_date=None, equity_source_date=None),
                debug=debug,
                exceptions=exceptions,
            )

        source_state = self._state_query.load_source_state(
            session,
            index_codes=[definition.large_index_code, definition.small_index_code],
        )
        try:
            current_snapshot = self._query.load_current_snapshot(
                session,
                trade_date=trading_day_context.expected_trade_date,
                large_index_code=definition.large_index_code,
                small_index_code=definition.small_index_code,
            )
            history_three_month_dates = self._query.load_recent_trade_dates(
                session,
                end_trade_date=trading_day_context.expected_trade_date,
                limit_days=definition.three_month_days,
            )
            history_three_month = self._query.load_history_points(
                session,
                trade_dates=history_three_month_dates,
                large_index_code=definition.large_index_code,
                small_index_code=definition.small_index_code,
            )
            one_month_date_set = set(history_three_month_dates[-definition.one_month_days :])
            history_one_month = [item for item in history_three_month if item.trade_date in one_month_date_set]
        except Exception as exc:  # noqa: BLE001
            exceptions.append(self._exception_builder.query_failed(message=f"market style query failed: {exc}"))
            return self._build_error_response(
                trading_day_context=trading_day_context,
                source_state=source_state,
                debug=debug,
                exceptions=exceptions,
            )

        has_history_values = any(
            point.large_pct is not None or point.small_pct is not None or point.median_pct is not None
            for point in history_three_month
        )
        status_result = self._status_resolver.resolve(
            expected_trade_date=trading_day_context.expected_trade_date,
            observed_trade_date=source_state.observed_trade_date,
            has_current_values=current_snapshot.has_any_value,
            has_history_values=has_history_values,
            as_of_time=trading_day_context.as_of_time,
        )
        if status_result.module_status.status == "DELAYED" and source_state.observed_trade_date is not None:
            exceptions.append(
                self._exception_builder.source_delayed(
                    message="style source date lagged",
                    expected_trade_date=trading_day_context.expected_trade_date.isoformat(),
                    observed_trade_date=source_state.observed_trade_date.isoformat(),
                )
            )
        if status_result.module_status.status == "EMPTY":
            exceptions.append(
                self._exception_builder.source_empty(
                    message="style source has no usable rows",
                )
            )

        response = MarketStyleResponseDto(
            tradingDay=TradingDayDto(
                tradeDate=trading_day_context.expected_trade_date,
                prevTradeDate=trading_day_context.prev_trade_date,
                market="CN_A",
                isTradingDay=trading_day_context.is_trading_day,
                sessionStatus=trading_day_context.session_status,  # type: ignore[arg-type]
                timezone="Asia/Shanghai",
            ),
            pageStatus=status_result.page_status,
            style=MarketStylePayloadDto(
                definition=MarketStyleDefinitionDto(
                    definitionKey=definition.definition_key,
                    version=definition.version,
                    fixedCardCount=3,
                ),
                cards=self._build_cards(snapshot=current_snapshot, definition=definition),
                historyByRange={
                    "oneMonth": self._to_history_rows(history_one_month),
                    "threeMonth": self._to_history_rows(history_three_month),
                },
            ),
            debugInfo=(
                MarketStyleDebugInfoDto(
                    modules=[status_result.module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )
        return response

    def _load_definition(self, *, market: str) -> MarketStyleDefinition:
        payload = self._config_service.get_payload(module_key="marketStyle", market=market)
        version = self._config_service.get_version(module_key="marketStyle", market=market)
        if not isinstance(payload, MarketStyleStrategyPayload):
            raise StrategyConfigValidationError("marketStyle payload model mismatch")
        return MarketStyleDefinition(
            definition_key=_DEFAULT_DEFINITION_KEY,
            version=version,
            one_month_days=payload.ranges.one_month_trading_days,
            three_month_days=payload.ranges.three_month_trading_days,
            large_index_code=payload.card_sources.large_cap.index_code,
            small_index_code=payload.card_sources.small_cap.index_code,
            large_label=payload.card_sources.large_cap.label,
            small_label=payload.card_sources.small_cap.label,
            median_label=payload.card_sources.median.label,
            large_source_text=payload.card_sources.large_cap.source_text,
            small_source_text=payload.card_sources.small_cap.source_text,
            median_source_text=payload.card_sources.median.source_text,
        )

    def _build_cards(
        self,
        *,
        snapshot: MarketStyleCurrentSnapshot,
        definition: MarketStyleDefinition,
    ) -> list[MarketStyleCardDto]:
        return [
            MarketStyleCardDto(
                cardKey="largeCap",
                label=definition.large_label,
                valuePct=snapshot.large_pct,
                sourceText=definition.large_source_text,
                direction=self._resolve_direction(snapshot.large_pct),
            ),
            MarketStyleCardDto(
                cardKey="smallCap",
                label=definition.small_label,
                valuePct=snapshot.small_pct,
                sourceText=definition.small_source_text,
                direction=self._resolve_direction(snapshot.small_pct),
            ),
            MarketStyleCardDto(
                cardKey="median",
                label=definition.median_label,
                valuePct=snapshot.median_pct,
                sourceText=definition.median_source_text,
                direction=self._resolve_direction(snapshot.median_pct),
            ),
        ]

    @staticmethod
    def _to_history_rows(points: list[MarketStyleHistoryPoint]) -> list[MarketStyleHistoryPointDto]:
        return [
            MarketStyleHistoryPointDto(
                tradeDate=point.trade_date,
                largePct=point.large_pct,
                smallPct=point.small_pct,
                medianPct=point.median_pct,
            )
            for point in points
        ]

    @staticmethod
    def _resolve_direction(value: float | None) -> str:
        if value is None:
            return "UNKNOWN"
        if value > 0:
            return "UP"
        if value < 0:
            return "DOWN"
        return "FLAT"

    def _build_error_response(
        self,
        *,
        trading_day_context: MarketStyleTradingDayContext,
        source_state: MarketStyleSourceState,
        debug: bool,
        exceptions: list,
    ) -> MarketStyleResponseDto:
        lag_days = None
        if source_state.observed_trade_date is not None:
            lag_days = (trading_day_context.expected_trade_date - source_state.observed_trade_date).days
            if lag_days < 0:
                lag_days = 0
        module_status = ModuleStatusItemDto(
            moduleKey="marketStyle",
            expectedTradeDate=trading_day_context.expected_trade_date,
            observedTradeDate=source_state.observed_trade_date,
            lagDays=lag_days,
            status="ERROR",
            note="module failed to load",
        )
        return MarketStyleResponseDto(
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
            style=MarketStylePayloadDto(
                definition=MarketStyleDefinitionDto(
                    definitionKey=_DEFAULT_DEFINITION_KEY,
                    version="0.0.0",
                    fixedCardCount=3,
                ),
                cards=[
                    MarketStyleCardDto(cardKey="largeCap", label="大盘股平均涨跌幅", valuePct=None, sourceText="沪深300口径", direction="UNKNOWN"),
                    MarketStyleCardDto(cardKey="smallCap", label="小盘股平均涨跌幅", valuePct=None, sourceText="中证1000口径", direction="UNKNOWN"),
                    MarketStyleCardDto(cardKey="median", label="涨跌中位数", valuePct=None, sourceText="全市场样本", direction="UNKNOWN"),
                ],
                historyByRange={"oneMonth": [], "threeMonth": []},
            ),
            debugInfo=(
                MarketStyleDebugInfoDto(
                    modules=[module_status],
                    exceptions=exceptions,
                )
                if debug
                else None
            ),
        )
