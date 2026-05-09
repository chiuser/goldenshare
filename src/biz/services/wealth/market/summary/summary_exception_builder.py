from __future__ import annotations

from src.biz.schemas.wealth.market.summary import ModuleExceptionItemDto


class SummaryExceptionBuilder:
    """Build structured module exceptions for market summary."""

    @staticmethod
    def config_missing(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketSummary",
            code="MS_CONFIG_MISSING",
            severity="error",
            message=message,
        )

    @staticmethod
    def card_count_invalid(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketSummary",
            code="MS_CARD_COUNT_INVALID",
            severity="error",
            message=message,
        )

    @staticmethod
    def source_delayed(*, message: str, expected_trade_date: str, observed_trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketSummary",
            code="MS_SOURCE_DELAYED",
            severity="warn",
            message=message,
            details={
                "expectedTradeDate": expected_trade_date,
                "observedTradeDate": observed_trade_date,
            },
        )

    @staticmethod
    def source_empty(*, message: str, source_key: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketSummary",
            code="MS_SOURCE_EMPTY",
            severity="warn",
            message=message,
            details={"sourceKey": source_key},
        )

    @staticmethod
    def text_render_failed(*, message: str, reason: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketSummary",
            code="MS_TEXT_RENDER_FAILED",
            severity="warn",
            message=message,
            details={"reason": reason},
        )

