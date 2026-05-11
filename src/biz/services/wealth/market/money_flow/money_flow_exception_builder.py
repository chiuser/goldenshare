from __future__ import annotations

from src.biz.schemas.wealth.market.money_flow import ModuleExceptionItemDto


class MoneyFlowExceptionBuilder:
    """Build structured module exceptions for money-flow."""

    @staticmethod
    def source_delayed(*, message: str, expected_trade_date: str, observed_trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="moneyFlow",
            code="MF_SOURCE_DELAYED",
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
            module="moneyFlow",
            code="MF_SOURCE_EMPTY",
            severity="warn",
            message=message,
        )

    @staticmethod
    def history_incomplete(*, message: str, one_month_points: int, three_month_points: int) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="moneyFlow",
            code="MF_HISTORY_INCOMPLETE",
            severity="warn",
            message=message,
            details={
                "oneMonthPoints": one_month_points,
                "threeMonthPoints": three_month_points,
            },
        )

    @staticmethod
    def query_failed(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="moneyFlow",
            code="MF_QUERY_FAILED",
            severity="error",
            message=message,
        )
