from __future__ import annotations

from src.biz.schemas.wealth.market.limit_up import ModuleExceptionItemDto


class LimitUpExceptionBuilder:
    """Build structured module exceptions for limit-up."""

    @staticmethod
    def source_delayed(*, message: str, expected_trade_date: str, observed_trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="limitUp",
            code="LU_SOURCE_DELAYED",
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
            module="limitUp",
            code="LU_SOURCE_EMPTY",
            severity="warn",
            message=message,
        )

    @staticmethod
    def seal_rate_denom_zero(*, message: str, non_st_limit_up: int, non_st_broken: int) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="limitUp",
            code="LU_SEAL_RATE_DENOM_ZERO",
            severity="warn",
            message=message,
            details={
                "nonStLimitUp": non_st_limit_up,
                "nonStBroken": non_st_broken,
            },
        )

    @staticmethod
    def distribution_mapping_missing(*, message: str, trade_date: str, block: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="limitUp",
            code="LU_DISTRIBUTION_MAPPING_MISSING",
            severity="warn",
            message=message,
            details={
                "tradeDate": trade_date,
                "block": block,
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
            module="limitUp",
            code="LU_HISTORY_INCOMPLETE",
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
            module="limitUp",
            code="LU_QUERY_FAILED",
            severity="error",
            message=message,
        )
