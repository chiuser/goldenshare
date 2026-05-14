from __future__ import annotations

from src.biz.schemas.wealth.market.news_briefs import ModuleExceptionItemDto


class MarketNewsExceptionBuilder:
    """Build structured module exceptions for market news panels."""

    @staticmethod
    def config_missing(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketNews",
            code="NEWS_CONFIG_MISSING",
            severity="error",
            message=message,
        )

    @staticmethod
    def config_invalid(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketNews",
            code="NEWS_CONFIG_INVALID",
            severity="error",
            message=message,
        )

    @staticmethod
    def source_empty(*, message: str, panel_key: str, target_trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketNews",
            code="NEWS_SOURCE_EMPTY",
            severity="warn",
            message=message,
            details={"panelKey": panel_key, "targetTradeDate": target_trade_date},
        )

    @staticmethod
    def source_delayed(
        *,
        message: str,
        panel_key: str,
        expected_trade_date: str,
        observed_trade_date: str,
    ) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketNews",
            code="NEWS_SOURCE_DELAYED",
            severity="warn",
            message=message,
            details={
                "panelKey": panel_key,
                "expectedTradeDate": expected_trade_date,
                "observedTradeDate": observed_trade_date,
            },
        )

    @staticmethod
    def query_failed(*, message: str, panel_key: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketNews",
            code="NEWS_QUERY_FAILED",
            severity="error",
            message=message,
            details={"panelKey": panel_key},
        )
