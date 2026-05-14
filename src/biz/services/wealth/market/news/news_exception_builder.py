from __future__ import annotations

from src.biz.schemas.wealth.market.news_briefs import ModuleExceptionItemDto


class MarketNewsExceptionBuilder:
    """Build structured module exceptions for market news panels."""

    @staticmethod
    def config_missing(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketNews",
            code="NEWS_CONFIG_MISSING",
            severity="error",
            message=message,
        )

    @staticmethod
    def config_invalid(*, message: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketNews",
            code="NEWS_CONFIG_INVALID",
            severity="error",
            message=message,
        )

    @staticmethod
    def source_empty(*, message: str, panel_key: str, window_start_at: str, window_end_at: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module=panel_key,
            code="NEWS_SOURCE_EMPTY",
            severity="warn",
            message=message,
            details={"panelKey": panel_key, "windowStartAt": window_start_at, "windowEndAt": window_end_at},
        )

    @staticmethod
    def source_delayed(
        *,
        message: str,
        panel_key: str,
        window_start_at: str,
        observed_at: str,
    ) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module=panel_key,
            code="NEWS_SOURCE_DELAYED",
            severity="warn",
            message=message,
            details={
                "panelKey": panel_key,
                "windowStartAt": window_start_at,
                "observedAt": observed_at,
            },
        )

    @staticmethod
    def query_failed(*, message: str, panel_key: str) -> ModuleExceptionItemDto:
        return ModuleExceptionItemDto(
            module="marketNews",
            code="NEWS_QUERY_FAILED",
            severity="error",
            message=message,
            details={"panelKey": panel_key},
        )
