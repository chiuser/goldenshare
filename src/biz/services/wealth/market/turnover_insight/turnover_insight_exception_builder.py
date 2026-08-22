from __future__ import annotations

from src.biz.schemas.wealth.market.turnover_insight import TurnoverInsightExceptionDto


class TurnoverInsightExceptionBuilder:
    @staticmethod
    def build(
        *,
        code: str,
        severity: str,
        message: str,
        details: dict[str, str | int | float | None] | None = None,
    ) -> TurnoverInsightExceptionDto:
        if not code.startswith("TI_"):
            raise ValueError("turnover insight exception codes must use TI_ prefix")
        return TurnoverInsightExceptionDto(
            code=code,
            severity=severity,  # type: ignore[arg-type]
            message=message,
            details=details,
        )
