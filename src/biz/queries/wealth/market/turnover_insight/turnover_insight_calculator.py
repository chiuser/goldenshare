from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.biz.queries.wealth.market.turnover_common.turnover_daily_average_query import (
    TurnoverDailyAverageSnapshot,
)
from src.biz.queries.wealth.market.turnover_common.turnover_panel_calculator import (
    TURNOVER_PANEL_AXIS_LABELS,
    TURNOVER_PANEL_MINUTE_GRID,
    TurnoverPanelAverageInput,
    TurnoverPanelAxis,
    TurnoverPanelCalculation,
    TurnoverPanelCalculator,
    TurnoverPanelMinuteInput,
    TurnoverPanelPointQualityError,
    TurnoverPanelTimeGridError,
)
from src.biz.schemas.wealth.market.turnover_insight import (
    TurnoverInsightAmountDto,
    TurnoverInsightAverageAmountDto,
    TurnoverInsightAxisTickDto,
    TurnoverInsightSeriesPointDto,
    TurnoverInsightSummaryDto,
    TurnoverInsightValueAxisDto,
)

from .turnover_insight_query import TurnoverInsightSnapshotRow


_THOUSAND_YUAN_MULTIPLIER = Decimal("1000")
_POINT_SUM_TOLERANCE = Decimal("0.10")
_TIME_TOKEN = re.compile(r"(?<!\d)([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?!\d)")

TURNOVER_INSIGHT_MINUTE_GRID = TURNOVER_PANEL_MINUTE_GRID
TURNOVER_INSIGHT_AXIS_LABELS = TURNOVER_PANEL_AXIS_LABELS


class TurnoverInsightPointQualityError(ValueError):
    pass


class TurnoverInsightTimeGridError(TurnoverInsightPointQualityError):
    pass


@dataclass(frozen=True, slots=True)
class ExactMinuteAmount:
    time: str
    amount_thousand_yuan: Decimal


@dataclass(frozen=True, slots=True)
class TurnoverInsightCalculation:
    summary: TurnoverInsightSummaryDto
    upper_axis: TurnoverInsightValueAxisDto
    delta_axis: TurnoverInsightValueAxisDto | None
    series: tuple[TurnoverInsightSeriesPointDto, ...]


class TurnoverInsightCalculator:
    def __init__(self) -> None:
        self._panel = TurnoverPanelCalculator()

    def parse_snapshot(
        self, snapshot: TurnoverInsightSnapshotRow
    ) -> tuple[ExactMinuteAmount, ...]:
        parsed: list[ExactMinuteAmount] = []
        for index, raw_point in enumerate(snapshot.points):
            if not isinstance(raw_point, dict):
                raise TurnoverInsightPointQualityError(
                    f"point {index} is not an object"
                )
            raw_time = raw_point.get("tradeTime")
            if not isinstance(raw_time, str):
                raise TurnoverInsightTimeGridError(
                    f"point {index} has no tradeTime"
                )
            try:
                amount = Decimal(str(raw_point.get("amount")))
            except (InvalidOperation, ValueError) as exc:
                raise TurnoverInsightPointQualityError(
                    f"point {index} has invalid amount"
                ) from exc
            if not amount.is_finite() or amount < 0:
                raise TurnoverInsightPointQualityError(
                    f"point {index} has invalid amount"
                )
            parsed.append(
                ExactMinuteAmount(
                    time=self._normalize_time(raw_time),
                    amount_thousand_yuan=amount,
                )
            )

        if tuple(point.time for point in parsed) != TURNOVER_INSIGHT_MINUTE_GRID:
            raise TurnoverInsightTimeGridError(
                "snapshot minute grid must contain the exact 241-point session"
            )
        point_sum = sum(
            (point.amount_thousand_yuan for point in parsed), Decimal("0")
        )
        if abs(point_sum - snapshot.total_amount_thousand_yuan) > _POINT_SUM_TOLERANCE:
            raise TurnoverInsightPointQualityError(
                "snapshot point sum does not match total amount"
            )
        return tuple(parsed)

    def calculate_pair(
        self,
        *,
        current_snapshot: TurnoverInsightSnapshotRow,
        previous_snapshot: TurnoverInsightSnapshotRow | None,
        daily_averages: TurnoverDailyAverageSnapshot | None = None,
    ) -> TurnoverInsightCalculation:
        current = self.parse_snapshot(current_snapshot)
        previous = (
            self.parse_snapshot(previous_snapshot)
            if previous_snapshot is not None
            else None
        )
        try:
            panel = self._panel.calculate(
                current=self._to_panel_minutes(current),
                previous=(
                    self._to_panel_minutes(previous)
                    if previous is not None
                    else None
                ),
                averages=self._to_panel_averages(daily_averages),
            )
        except TurnoverPanelTimeGridError as exc:
            raise TurnoverInsightTimeGridError(str(exc)) from exc
        except TurnoverPanelPointQualityError as exc:
            raise TurnoverInsightPointQualityError(str(exc)) from exc
        return self._to_dto(panel)

    def with_daily_averages(
        self,
        calculation: TurnoverInsightCalculation,
        daily_averages: TurnoverDailyAverageSnapshot | None,
    ) -> TurnoverInsightCalculation:
        averages = self._to_panel_averages(daily_averages)
        avg5d = self._panel.average_summary(
            days=5,
            amount_yuan=averages.avg5d_yuan if averages is not None else None,
        )
        avg20d = self._panel.average_summary(
            days=20,
            amount_yuan=averages.avg20d_yuan if averages is not None else None,
        )
        axis_values = [
            value
            for value in (
                calculation.summary.current.amountYi,
                calculation.summary.previous.amountYi,
                avg5d.amount_yi,
                avg20d.amount_yi,
            )
            if value is not None
        ]
        return TurnoverInsightCalculation(
            summary=TurnoverInsightSummaryDto(
                current=calculation.summary.current,
                previous=calculation.summary.previous,
                delta=calculation.summary.delta,
                avg5d=self._average_dto(avg5d),
                avg20d=self._average_dto(avg20d),
            ),
            upper_axis=self._axis_dto(self._panel.build_cumulative_axis(axis_values)),
            delta_axis=calculation.delta_axis,
            series=calculation.series,
        )

    @staticmethod
    def _to_panel_minutes(
        points: tuple[ExactMinuteAmount, ...],
    ) -> tuple[TurnoverPanelMinuteInput, ...]:
        return tuple(
            TurnoverPanelMinuteInput(
                time=point.time,
                amount_yuan=point.amount_thousand_yuan * _THOUSAND_YUAN_MULTIPLIER,
            )
            for point in points
        )

    @staticmethod
    def _to_panel_averages(
        snapshot: TurnoverDailyAverageSnapshot | None,
    ) -> TurnoverPanelAverageInput | None:
        if snapshot is None:
            return None
        return TurnoverPanelAverageInput(
            avg5d_yuan=(
                snapshot.avg5d_amount * _THOUSAND_YUAN_MULTIPLIER
                if snapshot.avg5d_amount is not None
                else None
            ),
            avg20d_yuan=(
                snapshot.avg20d_amount * _THOUSAND_YUAN_MULTIPLIER
                if snapshot.avg20d_amount is not None
                else None
            ),
            available5d_count=snapshot.available5d_count,
            available20d_count=snapshot.available20d_count,
        )

    @classmethod
    def _to_dto(
        cls, panel: TurnoverPanelCalculation
    ) -> TurnoverInsightCalculation:
        def amount(value: Any) -> TurnoverInsightAmountDto:
            return TurnoverInsightAmountDto(
                amountYi=value.amount_yi,
                displayText=value.display_text,
                direction=value.direction,
            )

        return TurnoverInsightCalculation(
            summary=TurnoverInsightSummaryDto(
                current=amount(panel.summary.current),
                previous=amount(panel.summary.previous),
                delta=amount(panel.summary.delta),
                avg5d=cls._average_dto(panel.summary.avg5d),
                avg20d=cls._average_dto(panel.summary.avg20d),
            ),
            upper_axis=cls._axis_dto(panel.upper_axis),
            delta_axis=(
                cls._axis_dto(panel.delta_axis)
                if panel.delta_axis is not None
                else None
            ),
            series=tuple(
                TurnoverInsightSeriesPointDto(
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
            ),
        )

    @staticmethod
    def _average_dto(value: Any) -> TurnoverInsightAverageAmountDto:
        return TurnoverInsightAverageAmountDto(
            amountYi=value.amount_yi,
            displayText=value.display_text,
            direction=value.direction,
            referenceLabel=value.reference_label,
        )

    @staticmethod
    def _axis_dto(value: TurnoverPanelAxis) -> TurnoverInsightValueAxisDto:
        return TurnoverInsightValueAxisDto(
            minYi=value.min_yi,
            maxYi=value.max_yi,
            zeroYi=value.zero_yi,
            ticks=[
                TurnoverInsightAxisTickDto(
                    valueYi=tick.value_yi,
                    displayText=tick.display_text,
                )
                for tick in value.ticks
            ],
        )

    @classmethod
    def round_yi(cls, value: Decimal) -> int:
        return TurnoverPanelCalculator.round_yi(value * _THOUSAND_YUAN_MULTIPLIER)

    @classmethod
    def build_cumulative_axis(cls, values: list[int]) -> TurnoverInsightValueAxisDto:
        return cls._axis_dto(TurnoverPanelCalculator.build_cumulative_axis(values))

    @classmethod
    def build_delta_axis(cls, values: list[int]) -> TurnoverInsightValueAxisDto:
        return cls._axis_dto(TurnoverPanelCalculator.build_delta_axis(values))

    @staticmethod
    def _normalize_time(raw_time: str) -> str:
        match = _TIME_TOKEN.search(raw_time.strip())
        if match is None:
            raise TurnoverInsightTimeGridError("tradeTime must contain HH:MM")
        return match.group(0)[:5]
