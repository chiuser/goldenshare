from __future__ import annotations

from src.biz.schemas.wealth.market.turnover import ModuleExceptionItemDto


class TurnoverExceptionBuilder:
    """Build structured module exceptions for turnover."""

    @staticmethod
    def source_delayed(*, message: str, expected_trade_date: str, observed_trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="turnover",
            code="TO_SOURCE_DELAYED",
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
            module="turnover",
            code="TO_SOURCE_EMPTY",
            severity="warn",
            message=message,
        )

    @staticmethod
    def intraday_missing(*, message: str, trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="turnover",
            code="TO_INTRADAY_MISSING",
            severity="warn",
            message=message,
            details={"tradeDate": trade_date},
        )

    @staticmethod
    def query_failed(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="turnover",
            code="TO_QUERY_FAILED",
            severity="error",
            message=message,
        )
