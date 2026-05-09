from __future__ import annotations

from src.biz.schemas.wealth.market.style import ModuleExceptionItemDto


class MarketStyleExceptionBuilder:
    """Build structured module exceptions for market style."""

    @staticmethod
    def config_missing(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="style",
            code="ST_CONFIG_MISSING",
            severity="error",
            message=message,
        )

    @staticmethod
    def config_invalid(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="style",
            code="ST_CONFIG_INVALID",
            severity="error",
            message=message,
        )

    @staticmethod
    def source_delayed(*, message: str, expected_trade_date: str, observed_trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="style",
            code="ST_SOURCE_DELAYED",
            severity="warn",
            message=message,
            details={
                "expectedTradeDate": expected_trade_date,
                "observedTradeDate": observed_trade_date,
            },
        )

    @staticmethod
    def source_empty(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="style",
            code="ST_SOURCE_EMPTY",
            severity="warn",
            message=message,
        )

    @staticmethod
    def query_failed(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="style",
            code="ST_QUERY_FAILED",
            severity="error",
            message=message,
        )
