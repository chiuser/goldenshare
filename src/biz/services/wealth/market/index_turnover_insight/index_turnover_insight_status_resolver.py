from __future__ import annotations

from dataclasses import dataclass

from src.biz.schemas.wealth.market.index_turnover_insight import (
    IndexTurnoverInsightItemStatus,
    IndexTurnoverInsightStatus,
)


@dataclass(frozen=True, slots=True)
class IndexTurnoverInsightStatusResolution:
    status: IndexTurnoverInsightStatus
    message: str | None
    exception_code: str | None


@dataclass(frozen=True, slots=True)
class IndexTurnoverInsightItemResolution:
    status: IndexTurnoverInsightItemStatus
    message: str | None
    exception_code: str | None


class IndexTurnoverInsightStatusResolver:
    @staticmethod
    def resolve_group(
        *,
        delayed: bool,
        item_statuses: tuple[IndexTurnoverInsightItemStatus, ...],
    ) -> IndexTurnoverInsightStatusResolution:
        if not any(status in {"READY", "PARTIAL"} for status in item_statuses):
            return IndexTurnoverInsightStatusResolution(
                "EMPTY", "当前暂无可展示的指数成交额数据。", "ITI_SOURCE_NOT_READY"
            )
        if delayed:
            return IndexTurnoverInsightStatusResolution(
                "DELAYED",
                "当前交易日数据尚未就绪，正在展示最近完整交易日对比。",
                "ITI_SOURCE_DELAYED",
            )
        if any(status != "READY" for status in item_statuses):
            return IndexTurnoverInsightStatusResolution(
                "PARTIAL", "部分指数成交额数据暂不完整。", None
            )
        return IndexTurnoverInsightStatusResolution("READY", None, None)

    @staticmethod
    def global_error(code: str) -> IndexTurnoverInsightStatusResolution:
        return IndexTurnoverInsightStatusResolution(
            "ERROR", "指数成交额数据读取失败，请稍后重试。", code
        )

    @staticmethod
    def item_ready() -> IndexTurnoverInsightItemResolution:
        return IndexTurnoverInsightItemResolution("READY", None, None)

    @staticmethod
    def item_average_partial() -> IndexTurnoverInsightItemResolution:
        return IndexTurnoverInsightItemResolution(
            "PARTIAL", "历史窗口暂不完整，部分均值暂不可用。", "ITI_AVERAGE_WINDOW_INCOMPLETE"
        )

    @staticmethod
    def item_current_only(code: str) -> IndexTurnoverInsightItemResolution:
        return IndexTurnoverInsightItemResolution(
            "PARTIAL", "上一交易日数据暂不完整，仅展示当日累计成交额。", code
        )

    @staticmethod
    def item_empty() -> IndexTurnoverInsightItemResolution:
        return IndexTurnoverInsightItemResolution(
            "EMPTY", "当前指数暂无可展示的成交额数据。", "ITI_SOURCE_NOT_READY"
        )

    @staticmethod
    def item_error(code: str) -> IndexTurnoverInsightItemResolution:
        return IndexTurnoverInsightItemResolution(
            "ERROR", "当前指数分钟数据质量校验失败。", code
        )
