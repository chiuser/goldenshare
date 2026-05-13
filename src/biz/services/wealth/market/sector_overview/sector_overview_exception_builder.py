from __future__ import annotations

from src.biz.schemas.wealth.market.sector_overview import ModuleExceptionItemDto


class SectorOverviewExceptionBuilder:
    """Build structured module exceptions for sector overview."""

    @staticmethod
    def source_delayed(*, message: str, expected_trade_date: str, observed_trade_date: str | None) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="sectorOverview",
            code="SO_SOURCE_DELAYED",
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
            module="sectorOverview",
            code="SO_SOURCE_EMPTY",
            severity="warn",
            message=message,
        )

    @staticmethod
    def column_metric_unavailable(*, message: str, column_key: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="sectorOverview",
            code="SO_COLUMN_METRIC_UNAVAILABLE",
            severity="error",
            message=message,
            details={"columnKey": column_key},
        )

    @staticmethod
    def query_failed(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="sectorOverview",
            code="SO_QUERY_FAILED",
            severity="error",
            message=message,
        )
