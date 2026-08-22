from __future__ import annotations

from dataclasses import dataclass

from src.biz.schemas.wealth.market.turnover_insight import TurnoverInsightStatus


@dataclass(frozen=True, slots=True)
class TurnoverInsightStatusResolution:
    status: TurnoverInsightStatus
    message: str | None
    exception_code: str | None


class TurnoverInsightStatusResolver:
    @staticmethod
    def ready() -> TurnoverInsightStatusResolution:
        return TurnoverInsightStatusResolution(status="READY", message=None, exception_code=None)

    @staticmethod
    def delayed() -> TurnoverInsightStatusResolution:
        return TurnoverInsightStatusResolution(
            status="DELAYED",
            message="当前交易日数据尚未就绪，正在展示最近完整交易日对比。",
            exception_code="TI_SOURCE_DELAYED",
        )

    @staticmethod
    def partial() -> TurnoverInsightStatusResolution:
        return TurnoverInsightStatusResolution(
            status="PARTIAL",
            message="上一交易日数据暂不完整，仅展示当日累计成交额。",
            exception_code="TI_PREVIOUS_SNAPSHOT_MISSING",
        )

    @staticmethod
    def empty() -> TurnoverInsightStatusResolution:
        return TurnoverInsightStatusResolution(
            status="EMPTY",
            message="当前暂无可展示的成交额数据。",
            exception_code="TI_CURRENT_SNAPSHOT_MISSING",
        )

    @staticmethod
    def error() -> TurnoverInsightStatusResolution:
        return TurnoverInsightStatusResolution(
            status="ERROR",
            message="成交额数据读取失败，请稍后重试。",
            exception_code="TI_QUERY_FAILED",
        )
