from __future__ import annotations

from types import MappingProxyType
from typing import Final

from src.biz.schemas.wealth.market.index_turnover_insight import (
    IndexTurnoverInsightExceptionDto,
)


INDEX_TURNOVER_INSIGHT_EXCEPTION_SEVERITY: Final = MappingProxyType(
    {
        "ITI_SOURCE_NOT_READY": "warn",
        "ITI_SOURCE_DELAYED": "warn",
        "ITI_SOURCE_CONTRACT_MISMATCH": "error",
        "ITI_CODE_SCOPE_MISMATCH": "error",
        "ITI_TIME_GRID_MISMATCH": "error",
        "ITI_POINT_QUALITY_INVALID": "error",
        "ITI_AVERAGE_WINDOW_INCOMPLETE": "warn",
        "ITI_QUERY_FAILED": "error",
    }
)

_PRIORITY: Final = {
    "ITI_QUERY_FAILED": 0,
    "ITI_SOURCE_CONTRACT_MISMATCH": 1,
    "ITI_CODE_SCOPE_MISMATCH": 2,
    "ITI_POINT_QUALITY_INVALID": 3,
    "ITI_TIME_GRID_MISMATCH": 3,
    "ITI_SOURCE_NOT_READY": 4,
    "ITI_SOURCE_DELAYED": 5,
    "ITI_AVERAGE_WINDOW_INCOMPLETE": 6,
}


class IndexTurnoverInsightExceptionBuilder:
    @staticmethod
    def build(
        *,
        code: str,
        message: str,
        details: dict[str, str | int | float | None] | None = None,
    ) -> IndexTurnoverInsightExceptionDto:
        severity = INDEX_TURNOVER_INSIGHT_EXCEPTION_SEVERITY.get(code)
        if severity is None:
            raise ValueError("unknown index turnover insight exception code")
        return IndexTurnoverInsightExceptionDto(
            code=code,
            severity=severity,  # type: ignore[arg-type]
            message=message,
            details=details,
        )

    @staticmethod
    def select_primary(codes: list[str]) -> str | None:
        if not codes:
            return None
        unknown = set(codes).difference(INDEX_TURNOVER_INSIGHT_EXCEPTION_SEVERITY)
        if unknown:
            raise ValueError("unknown index turnover insight exception code")
        return min(codes, key=lambda code: (_PRIORITY[code], code))
