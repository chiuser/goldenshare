from __future__ import annotations

from src.biz.schemas.wealth.market.breadth import ModuleExceptionItemDto


class BreadthExceptionBuilder:
    """Build structured module exceptions for breadth module."""

    @staticmethod
    def source_empty(*, message: str, target_trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="breadth",
            code="BR_SOURCE_EMPTY",
            severity="warn",
            message=message,
            details={"targetTradeDate": target_trade_date},
        )

    @staticmethod
    def source_delayed(*, message: str, expected_trade_date: str, observed_trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="breadth",
            code="BR_SOURCE_DELAYED",
            severity="warn",
            message=message,
            details={
                "expectedTradeDate": expected_trade_date,
                "observedTradeDate": observed_trade_date,
            },
        )

    @staticmethod
    def history_incomplete(
        *,
        message: str,
        actual_points_1m: int,
        expected_points_1m: int,
        actual_points_3m: int,
        expected_points_3m: int,
    ) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="breadth",
            code="BR_HISTORY_INCOMPLETE",
            severity="warn",
            message=message,
            details={
                "actualPoints1m": actual_points_1m,
                "expectedPoints1m": expected_points_1m,
                "actualPoints3m": actual_points_3m,
                "expectedPoints3m": expected_points_3m,
            },
        )

    @staticmethod
    def query_failed(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="breadth",
            code="BR_QUERY_FAILED",
            severity="error",
            message=message,
        )

    @staticmethod
    def fact_duplicated(*, message: str, trade_date: str, row_count: int) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="breadth",
            code="BR_FACT_DUPLICATED",
            severity="error",
            message=message,
            details={
                "tradeDate": trade_date,
                "rowCount": row_count,
            },
        )
