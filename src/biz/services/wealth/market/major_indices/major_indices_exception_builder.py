from __future__ import annotations

from src.biz.schemas.wealth.market.major_indices import ModuleExceptionItemDto


class MajorIndicesExceptionBuilder:
    """Build structured module exceptions for major indices."""

    @staticmethod
    def config_missing(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="majorIndices",
            code="MI_CONFIG_MISSING",
            severity="error",
            message=message,
        )

    @staticmethod
    def config_invalid(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="majorIndices",
            code="MI_CONFIG_INVALID",
            severity="error",
            message=message,
        )

    @staticmethod
    def source_delayed(*, message: str, expected_trade_date: str, observed_trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="majorIndices",
            code="MI_SOURCE_DELAYED",
            severity="warn",
            message=message,
            details={
                "expectedTradeDate": expected_trade_date,
                "observedTradeDate": observed_trade_date,
            },
        )

    @staticmethod
    def source_empty(*, message: str, missing_count: int) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="majorIndices",
            code="MI_SOURCE_EMPTY",
            severity="warn",
            message=message,
            details={"missingCount": missing_count},
        )

    @staticmethod
    def query_failed(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="majorIndices",
            code="MI_QUERY_FAILED",
            severity="error",
            message=message,
        )

