from __future__ import annotations

from src.biz.schemas.wealth.market.leaderboards import ModuleExceptionItemDto


class LeaderboardExceptionBuilder:
    """Build structured module exceptions for leaderboards."""

    @staticmethod
    def source_empty(*, message: str, board_key: str, trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="leaderboards",
            code="LB_SOURCE_EMPTY",
            severity="warn",
            message=message,
            details={
                "boardKey": board_key,
                "tradeDate": trade_date,
            },
        )

    @staticmethod
    def source_delayed(
        *,
        message: str,
        board_key: str,
        expected_trade_date: str,
        observed_trade_date: str | None,
    ) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="leaderboards",
            code="LB_SOURCE_DELAYED",
            severity="warn",
            message=message,
            details={
                "boardKey": board_key,
                "expectedTradeDate": expected_trade_date,
                "observedTradeDate": observed_trade_date,
            },
        )

    @staticmethod
    def join_metric_missing(*, message: str, board_key: str, subject_code: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="leaderboards",
            code="LB_JOIN_METRIC_MISSING",
            severity="warn",
            message=message,
            details={
                "boardKey": board_key,
                "subjectCode": subject_code,
            },
        )

    @staticmethod
    def subject_name_missing(*, message: str, board_key: str, subject_code: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="leaderboards",
            code="LB_SUBJECT_NAME_MISSING",
            severity="info",
            message=message,
            details={
                "boardKey": board_key,
                "subjectCode": subject_code,
            },
        )

    @staticmethod
    def query_failed(*, message: str, board_key: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="leaderboards",
            code="LB_QUERY_FAILED",
            severity="error",
            message=message,
            details={"boardKey": board_key},
        )

