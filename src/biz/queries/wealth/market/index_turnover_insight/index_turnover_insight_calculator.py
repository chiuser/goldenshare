from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from typing import Any

from src.biz.queries.wealth.market.turnover_common.turnover_panel_calculator import (
    TURNOVER_PANEL_MINUTE_GRID,
    TurnoverPanelAverageInput,
    TurnoverPanelCalculation,
    TurnoverPanelCalculator,
    TurnoverPanelMinuteInput,
    TurnoverPanelTimeGridError,
)
from src.biz.schemas.wealth.market.index_turnover_insight import (
    IndexTurnoverInsightAmountDto,
    IndexTurnoverInsightAverageAmountDto,
    IndexTurnoverInsightAxisTickDto,
    IndexTurnoverInsightItemStatus,
    IndexTurnoverInsightPanelDto,
    IndexTurnoverInsightSeriesPointDto,
    IndexTurnoverInsightSummaryDto,
    IndexTurnoverInsightValueAxisDto,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_universe import (
    IndexTurnoverInsightIdentity,
)
from src.foundation.clients.local_lake.major_index_turnover_reader import (
    MajorIndexTurnoverMinuteRow,
)


_TIME_LABEL_BY_VALUE = {
    time.fromisoformat(label): label for label in TURNOVER_PANEL_MINUTE_GRID
}
_TURNOVER_PANEL_TIME_GRID = tuple(_TIME_LABEL_BY_VALUE)


@dataclass(frozen=True, slots=True)
class IndexTurnoverInsightCalculation:
    panel: TurnoverPanelCalculation | None
    current_available: bool
    previous_available: bool
    available5d_count: int
    available20d_count: int

    @property
    def averages_complete(self) -> bool:
        return self.available5d_count == 5 and self.available20d_count == 20


class IndexTurnoverInsightCalculator:
    def __init__(self) -> None:
        self._panel = TurnoverPanelCalculator()

    def calculate(
        self,
        *,
        ts_code: str,
        rows: tuple[MajorIndexTurnoverMinuteRow, ...],
        observed_trade_date: date,
        previous_observed_trade_date: date,
    ) -> IndexTurnoverInsightCalculation:
        grouped: dict[date, list[MajorIndexTurnoverMinuteRow]] = defaultdict(list)
        for row in rows:
            if row.ts_code == ts_code and row.trade_date <= observed_trade_date:
                grouped[row.trade_date].append(row)

        selected_points: dict[date, tuple[TurnoverPanelMinuteInput, ...]] = {}
        daily_amounts: dict[date, Decimal] = {}
        for trade_date, group in grouped.items():
            ordered = tuple(sorted(group, key=lambda row: row.trade_time))
            if tuple(row.trade_time.time() for row in ordered) != _TURNOVER_PANEL_TIME_GRID:
                raise TurnoverPanelTimeGridError(
                    f"{ts_code} {trade_date} does not match the 241-point grid"
                )
            daily_amounts[trade_date] = sum(
                (row.amount_yuan for row in ordered), Decimal("0")
            )
            if trade_date in {observed_trade_date, previous_observed_trade_date}:
                selected_points[trade_date] = tuple(
                    TurnoverPanelMinuteInput(
                        time=_TIME_LABEL_BY_VALUE[row.trade_time.time()],
                        amount_yuan=row.amount_yuan,
                    )
                    for row in ordered
                )

        current = selected_points.get(observed_trade_date)
        previous = selected_points.get(previous_observed_trade_date)
        complete_dates = tuple(sorted(daily_amounts, reverse=True))
        recent5 = complete_dates[:5]
        recent20 = complete_dates[:20]
        available5d_count = len(recent5)
        available20d_count = len(recent20)
        averages = TurnoverPanelAverageInput(
            avg5d_yuan=(
                self._average(daily_amounts, recent5)
                if available5d_count == 5
                else None
            ),
            avg20d_yuan=(
                self._average(daily_amounts, recent20)
                if available20d_count == 20
                else None
            ),
            available5d_count=available5d_count,
            available20d_count=available20d_count,
        )
        panel = (
            self._panel.calculate(
                current=current,
                previous=previous,
                averages=averages,
            )
            if current is not None
            else None
        )
        return IndexTurnoverInsightCalculation(
            panel=panel,
            current_available=current is not None,
            previous_available=previous is not None,
            available5d_count=available5d_count,
            available20d_count=available20d_count,
        )

    def build_panel_dto(
        self,
        *,
        identity: IndexTurnoverInsightIdentity,
        calculation: IndexTurnoverInsightCalculation | None,
        status: IndexTurnoverInsightItemStatus,
        message: str | None,
        exception_code: str | None,
    ) -> IndexTurnoverInsightPanelDto:
        if calculation is None or calculation.panel is None:
            return IndexTurnoverInsightPanelDto(
                tsCode=identity.ts_code,
                indexName=identity.index_name,
                status=status,
                summary=self.empty_summary(),
                series=[],
                message=message,
                exceptionCode=exception_code,
            )
        panel = calculation.panel
        return IndexTurnoverInsightPanelDto(
            tsCode=identity.ts_code,
            indexName=identity.index_name,
            status=status,
            summary=IndexTurnoverInsightSummaryDto(
                current=self._amount(panel.summary.current),
                previous=self._amount(panel.summary.previous),
                delta=self._amount(panel.summary.delta),
                avg5d=self._average_amount(panel.summary.avg5d),
                avg20d=self._average_amount(panel.summary.avg20d),
            ),
            upperAxis=self._axis(panel.upper_axis),
            deltaAxis=self._axis(panel.delta_axis) if panel.delta_axis else None,
            series=[
                IndexTurnoverInsightSeriesPointDto(
                    time=point.time,
                    showAxisLabel=point.show_axis_label,
                    currentAmountYi=point.current_amount_yi,
                    currentDisplayText=point.current_display_text,
                    previousAmountYi=point.previous_amount_yi,
                    previousDisplayText=point.previous_display_text,
                    deltaAmountYi=point.delta_amount_yi,
                    deltaDisplayText=point.delta_display_text,
                    deltaDirection=point.delta_direction,
                )
                for point in panel.series
            ],
            message=message,
            exceptionCode=exception_code,
        )

    @staticmethod
    def _average(
        daily_amounts: dict[date, Decimal], trade_dates: tuple[date, ...]
    ) -> Decimal:
        return sum(
            (daily_amounts[trade_date] for trade_date in trade_dates),
            Decimal("0"),
        ) / Decimal(len(trade_dates))

    @staticmethod
    def _amount(value: Any) -> IndexTurnoverInsightAmountDto:
        return IndexTurnoverInsightAmountDto(
            amountYi=value.amount_yi,
            displayText=value.display_text,
            direction=value.direction,
        )

    @staticmethod
    def _average_amount(value: Any) -> IndexTurnoverInsightAverageAmountDto:
        return IndexTurnoverInsightAverageAmountDto(
            amountYi=value.amount_yi,
            displayText=value.display_text,
            direction=value.direction,
            referenceLabel=value.reference_label,
        )

    @staticmethod
    def _axis(value: Any) -> IndexTurnoverInsightValueAxisDto:
        return IndexTurnoverInsightValueAxisDto(
            minYi=value.min_yi,
            maxYi=value.max_yi,
            zeroYi=value.zero_yi,
            ticks=[
                IndexTurnoverInsightAxisTickDto(
                    valueYi=tick.value_yi,
                    displayText=tick.display_text,
                )
                for tick in value.ticks
            ],
        )

    @staticmethod
    def empty_summary() -> IndexTurnoverInsightSummaryDto:
        empty = IndexTurnoverInsightAmountDto(
            amountYi=None, displayText="--", direction="neutral"
        )
        return IndexTurnoverInsightSummaryDto(
            current=empty,
            previous=empty.model_copy(),
            delta=empty.model_copy(),
            avg5d=IndexTurnoverInsightAverageAmountDto(
                amountYi=None,
                displayText="--",
                direction="neutral",
                referenceLabel="5日均值 --",
            ),
            avg20d=IndexTurnoverInsightAverageAmountDto(
                amountYi=None,
                displayText="--",
                direction="neutral",
                referenceLabel="20日均值 --",
            ),
        )
