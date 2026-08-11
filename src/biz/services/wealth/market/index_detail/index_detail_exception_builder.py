from __future__ import annotations

from src.biz.schemas.wealth.market.index_detail import IndexDetailExceptionDto


class IndexDetailExceptionBuilder:
    """Build only exception codes frozen by the index-detail contract."""

    @staticmethod
    def source_empty(*, module: str, message: str) -> IndexDetailExceptionDto:
        return IndexDetailExceptionDto(module=module, code="ID_SOURCE_EMPTY", severity="warn", message=message)  # type: ignore[arg-type]

    @staticmethod
    def source_delayed(*, module: str, message: str) -> IndexDetailExceptionDto:
        return IndexDetailExceptionDto(module=module, code="ID_SOURCE_DELAYED", severity="warn", message=message)  # type: ignore[arg-type]

    @staticmethod
    def factor_partial(*, module: str, message: str) -> IndexDetailExceptionDto:
        return IndexDetailExceptionDto(module=module, code="ID_FACTOR_PARTIAL", severity="warn", message=message)  # type: ignore[arg-type]

    @staticmethod
    def daily_basic_partial(*, message: str) -> IndexDetailExceptionDto:
        return IndexDetailExceptionDto(
            module="indexDetailPageInit",
            code="ID_BASIC_DAILY_PARTIAL",
            severity="warn",
            message=message,
        )

    @staticmethod
    def breadth_partial(*, message: str) -> IndexDetailExceptionDto:
        return IndexDetailExceptionDto(
            module="indexDetailPageInit",
            code="ID_BASIC_BREADTH_PARTIAL",
            severity="warn",
            message=message,
        )

    @staticmethod
    def weight_empty(*, module: str, message: str) -> IndexDetailExceptionDto:
        return IndexDetailExceptionDto(module=module, code="ID_WEIGHT_EMPTY", severity="warn", message=message)  # type: ignore[arg-type]

    @staticmethod
    def weight_contribution_partial(*, message: str) -> IndexDetailExceptionDto:
        return IndexDetailExceptionDto(
            module="indexDetailWeights",
            code="ID_WEIGHT_CONTRIBUTION_PARTIAL",
            severity="warn",
            message=message,
        )
