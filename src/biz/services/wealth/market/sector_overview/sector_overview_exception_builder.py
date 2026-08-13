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
    def hierarchy_unavailable(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="sectorOverview",
            code="SO_HIERARCHY_UNAVAILABLE",
            severity="error",
            message=message,
        )

    @staticmethod
    def selection_invalid(*, message: str, requested_code: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="sectorOverview",
            code="SO_SELECTION_INVALID",
            severity="warn",
            message=message,
            details={"requestedCode": requested_code},
        )

    @staticmethod
    def heat_not_ready(*, message: str, trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="sectorOverview",
            code="SO_HEAT_NOT_READY",
            severity="warn",
            message=message,
            details={"tradeDate": trade_date},
        )

    @staticmethod
    def heat_source_mismatch(*, message: str, trade_date: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="sectorOverview",
            code="SO_HEAT_SOURCE_MISMATCH",
            severity="error",
            message=message,
            details={"tradeDate": trade_date},
        )

    @staticmethod
    def member_coverage_low(*, message: str, sector_code: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="sectorOverview",
            code="SO_MEMBER_COVERAGE_LOW",
            severity="warn",
            message=message,
            details={"sectorCode": sector_code},
        )

    @staticmethod
    def query_failed(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="sectorOverview",
            code="SO_QUERY_FAILED",
            severity="error",
            message=message,
        )
