from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from math import floor, log10
import re

from src.biz.schemas.wealth.market.turnover_insight import (
    TurnoverInsightAmountDto,
    TurnoverInsightAverageAmountDto,
    TurnoverInsightAxisTickDto,
    TurnoverInsightSeriesPointDto,
    TurnoverInsightSummaryDto,
    TurnoverInsightValueAxisDto,
)
from src.biz.queries.wealth.market.turnover_common.turnover_daily_average_query import (
    TurnoverDailyAverageSnapshot,
)

from .turnover_insight_query import TurnoverInsightSnapshotRow


_THOUSAND_YUAN_PER_YI = Decimal("100000")
_POINT_SUM_TOLERANCE = Decimal("0.10")
_TIME_TOKEN = re.compile(r"(?<!\d)([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?!\d)")


def _minute_labels(start_hour: int, start_minute: int, end_hour: int, end_minute: int) -> list[str]:
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    return [f"{minute // 60:02d}:{minute % 60:02d}" for minute in range(start, end + 1)]


TURNOVER_INSIGHT_MINUTE_GRID = tuple(
    _minute_labels(9, 30, 11, 30) + _minute_labels(13, 1, 15, 0)
)
TURNOVER_INSIGHT_AXIS_LABELS = frozenset(
    (
        "09:30",
        "09:45",
        "10:00",
        "10:15",
        "10:30",
        "10:45",
        "11:00",
        "11:15",
        "11:30",
        "13:15",
        "13:30",
        "13:45",
        "14:00",
        "14:15",
        "14:30",
        "14:45",
        "15:00",
    )
)


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
    def parse_snapshot(self, snapshot: TurnoverInsightSnapshotRow) -> tuple[ExactMinuteAmount, ...]:
        parsed: list[ExactMinuteAmount] = []
        for index, raw_point in enumerate(snapshot.points):
            if not isinstance(raw_point, dict):
                raise TurnoverInsightPointQualityError(f"point {index} is not an object")
            raw_time = raw_point.get("tradeTime")
            if not isinstance(raw_time, str):
                raise TurnoverInsightTimeGridError(f"point {index} has no tradeTime")
            normalized_time = self._normalize_time(raw_time)
            try:
                amount = Decimal(str(raw_point.get("amount")))
            except (InvalidOperation, ValueError) as exc:
                raise TurnoverInsightPointQualityError(f"point {index} has invalid amount") from exc
            if not amount.is_finite() or amount < 0:
                raise TurnoverInsightPointQualityError(f"point {index} has invalid amount")
            parsed.append(ExactMinuteAmount(time=normalized_time, amount_thousand_yuan=amount))

        actual_grid = tuple(point.time for point in parsed)
        if actual_grid != TURNOVER_INSIGHT_MINUTE_GRID:
            raise TurnoverInsightTimeGridError("snapshot minute grid must contain the exact 241-point session")
        point_sum = sum((point.amount_thousand_yuan for point in parsed), Decimal("0"))
        if abs(point_sum - snapshot.total_amount_thousand_yuan) > _POINT_SUM_TOLERANCE:
            raise TurnoverInsightPointQualityError("snapshot point sum does not match total amount")
        return tuple(parsed)

    def calculate_pair(
        self,
        *,
        current_snapshot: TurnoverInsightSnapshotRow,
        previous_snapshot: TurnoverInsightSnapshotRow | None,
        daily_averages: TurnoverDailyAverageSnapshot | None = None,
    ) -> TurnoverInsightCalculation:
        current_points = self.parse_snapshot(current_snapshot)
        previous_points = self.parse_snapshot(previous_snapshot) if previous_snapshot is not None else None
        if previous_points is not None and tuple(point.time for point in previous_points) != tuple(
            point.time for point in current_points
        ):
            raise TurnoverInsightTimeGridError("current and previous time grids differ")

        current_cumulative = Decimal("0")
        previous_cumulative = Decimal("0")
        series: list[TurnoverInsightSeriesPointDto] = []
        current_values: list[int] = []
        previous_values: list[int] = []
        delta_values: list[int] = []
        last_delta_exact = Decimal("0")

        for index, current_point in enumerate(current_points):
            current_cumulative += current_point.amount_thousand_yuan
            current_yi = self.round_yi(current_cumulative)
            current_values.append(current_yi)

            previous_yi: int | None = None
            delta_yi: int | None = None
            delta_direction = "flat"
            if previous_points is not None:
                previous_cumulative += previous_points[index].amount_thousand_yuan
                last_delta_exact = current_cumulative - previous_cumulative
                previous_yi = self.round_yi(previous_cumulative)
                delta_yi = self.round_yi(last_delta_exact)
                previous_values.append(previous_yi)
                delta_values.append(delta_yi)
                delta_direction = self._direction(last_delta_exact)

            series.append(
                TurnoverInsightSeriesPointDto(
                    time=current_point.time,
                    showAxisLabel=current_point.time in TURNOVER_INSIGHT_AXIS_LABELS,
                    currentAmountYi=current_yi,
                    currentDisplayText=self._display_amount(current_yi),
                    previousAmountYi=previous_yi,
                    previousDisplayText=self._display_amount(previous_yi),
                    deltaAmountYi=delta_yi,
                    deltaDisplayText=self._display_amount(delta_yi, signed=True),
                    deltaDirection=delta_direction,
                )
            )

        current_summary = TurnoverInsightAmountDto(
            amountYi=current_values[-1],
            displayText=self._display_amount(current_values[-1]),
            direction="neutral",
        )
        if previous_points is None:
            previous_summary = TurnoverInsightAmountDto(amountYi=None, displayText="--", direction="neutral")
            delta_summary = TurnoverInsightAmountDto(amountYi=None, displayText="--", direction="neutral")
            delta_axis = None
        else:
            previous_summary = TurnoverInsightAmountDto(
                amountYi=previous_values[-1],
                displayText=self._display_amount(previous_values[-1]),
                direction="neutral",
            )
            delta_summary = TurnoverInsightAmountDto(
                amountYi=delta_values[-1],
                displayText=self._display_amount(delta_values[-1], signed=True),
                direction=self._direction(last_delta_exact),
            )
            delta_axis = self.build_delta_axis(delta_values)

        calculation = TurnoverInsightCalculation(
            summary=TurnoverInsightSummaryDto(
                current=current_summary,
                previous=previous_summary,
                delta=delta_summary,
                avg5d=self._average_summary(days=5, amount_thousand_yuan=None),
                avg20d=self._average_summary(days=20, amount_thousand_yuan=None),
            ),
            upper_axis=self.build_cumulative_axis([*current_values, *previous_values]),
            delta_axis=delta_axis,
            series=tuple(series),
        )
        return self.with_daily_averages(calculation, daily_averages)

    def with_daily_averages(
        self,
        calculation: TurnoverInsightCalculation,
        daily_averages: TurnoverDailyAverageSnapshot | None,
    ) -> TurnoverInsightCalculation:
        avg5d = self._average_summary(
            days=5,
            amount_thousand_yuan=daily_averages.avg5d_amount if daily_averages is not None else None,
        )
        avg20d = self._average_summary(
            days=20,
            amount_thousand_yuan=daily_averages.avg20d_amount if daily_averages is not None else None,
        )
        axis_values = [
            value
            for value in (
                calculation.summary.current.amountYi,
                calculation.summary.previous.amountYi,
                avg5d.amountYi,
                avg20d.amountYi,
            )
            if value is not None
        ]
        return TurnoverInsightCalculation(
            summary=TurnoverInsightSummaryDto(
                current=calculation.summary.current,
                previous=calculation.summary.previous,
                delta=calculation.summary.delta,
                avg5d=avg5d,
                avg20d=avg20d,
            ),
            upper_axis=self.build_cumulative_axis(axis_values),
            delta_axis=calculation.delta_axis,
            series=calculation.series,
        )

    @staticmethod
    def round_yi(value: Decimal) -> int:
        return int((value / _THOUSAND_YUAN_PER_YI).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @classmethod
    def build_cumulative_axis(cls, values: list[int]) -> TurnoverInsightValueAxisDto:
        domain_max = max(values, default=0)
        if domain_max <= 0:
            ticks = [0, 1, 2, 3, 4]
        else:
            step = cls._axis_step(domain_max=domain_max, intervals=4)
            ticks = [step * index for index in range(5)]
        return cls._axis(min_value=ticks[0], max_value=ticks[-1], zero_value=0, ticks=ticks)

    @classmethod
    def build_delta_axis(cls, values: list[int]) -> TurnoverInsightValueAxisDto:
        positive_max = max((value for value in values if value > 0), default=0)
        negative_abs_max = max((-value for value in values if value < 0), default=0)
        if positive_max == 0 and negative_abs_max == 0:
            return cls._axis(min_value=-1, max_value=1, zero_value=0, ticks=[-1, 0, 1])

        negative_ticks: list[int] = []
        if negative_abs_max > 0:
            negative_step = cls._axis_step(domain_max=negative_abs_max, intervals=2)
            negative_ticks = [-negative_step * 2, -negative_step]
        positive_ticks: list[int] = []
        if positive_max > 0:
            positive_step = cls._axis_step(domain_max=positive_max, intervals=2)
            positive_ticks = [positive_step, positive_step * 2]
        ticks = [*negative_ticks, 0, *positive_ticks]
        return cls._axis(min_value=ticks[0], max_value=ticks[-1], zero_value=0, ticks=ticks)

    @staticmethod
    def _axis_step(*, domain_max: int, intervals: int) -> int:
        granularity = 10 ** max(0, floor(log10(abs(domain_max))) - 1)
        raw_step = Decimal(domain_max) * Decimal("1.10") / Decimal(intervals)
        units = (raw_step / Decimal(granularity)).to_integral_value(rounding=ROUND_CEILING)
        return max(1, int(units) * granularity)

    @classmethod
    def _axis(
        cls,
        *,
        min_value: int,
        max_value: int,
        zero_value: int | None,
        ticks: list[int],
    ) -> TurnoverInsightValueAxisDto:
        return TurnoverInsightValueAxisDto(
            minYi=min_value,
            maxYi=max_value,
            zeroYi=zero_value,
            ticks=[
                TurnoverInsightAxisTickDto(
                    valueYi=value,
                    displayText="0" if value == 0 else f"{value:,}亿",
                )
                for value in ticks
            ],
        )

    @staticmethod
    def _normalize_time(raw_time: str) -> str:
        value = raw_time.strip()
        match = _TIME_TOKEN.search(value)
        if match is None:
            raise TurnoverInsightTimeGridError("tradeTime must contain HH:MM")
        return match.group(0)[:5]

    @staticmethod
    def _direction(value: Decimal) -> str:
        if value > 0:
            return "up"
        if value < 0:
            return "down"
        return "flat"

    @staticmethod
    def _display_amount(value: int | None, *, signed: bool = False) -> str:
        if value is None:
            return "--"
        prefix = "+" if signed and value > 0 else ""
        return f"{prefix}{value:,}亿"

    @classmethod
    def _average_summary(
        cls,
        *,
        days: int,
        amount_thousand_yuan: Decimal | None,
    ) -> TurnoverInsightAverageAmountDto:
        amount_yi = cls.round_yi(amount_thousand_yuan) if amount_thousand_yuan is not None else None
        display_text = cls._display_amount(amount_yi)
        return TurnoverInsightAverageAmountDto(
            amountYi=amount_yi,
            displayText=display_text,
            direction="neutral",
            referenceLabel=f"{days}日均值 {display_text}",
        )
