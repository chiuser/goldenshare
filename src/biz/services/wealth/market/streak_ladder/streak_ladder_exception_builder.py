from __future__ import annotations

from src.biz.schemas.wealth.market.streak_ladder import ModuleExceptionItemDto


class StreakLadderExceptionBuilder:
    """Build structured exceptions for streak ladder module."""

    @staticmethod
    def source_delayed(*, message: str, expected_trade_date: str, observed_trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="streakLadder",
            code="SL_SOURCE_DELAYED",
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
            module="streakLadder",
            code="SL_SOURCE_EMPTY",
            severity="warn",
            message=message,
        )

    @staticmethod
    def invalid_board_count(*, message: str, sample_ts_code: str | None, raw_value: str | None) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="streakLadder",
            code="SL_INVALID_BOARD_COUNT",
            severity="warn",
            message=message,
            details={
                "sampleTsCode": sample_ts_code,
                "rawValue": raw_value,
            },
        )

    @staticmethod
    def join_metric_missing(*, message: str, sample_ts_code: str | None) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="streakLadder",
            code="SL_JOIN_METRIC_MISSING",
            severity="warn",
            message=message,
            details={
                "sampleTsCode": sample_ts_code,
            },
        )

    @staticmethod
    def query_failed(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="streakLadder",
            code="SL_QUERY_FAILED",
            severity="error",
            message=message,
        )
