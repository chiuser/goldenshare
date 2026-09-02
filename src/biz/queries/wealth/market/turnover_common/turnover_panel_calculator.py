from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from math import floor, log10


YUAN_PER_YI = Decimal("100000000")


def _minute_labels(
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
) -> list[str]:
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    return [
        f"{minute // 60:02d}:{minute % 60:02d}"
        for minute in range(start, end + 1)
    ]


TURNOVER_PANEL_MINUTE_GRID = tuple(
    _minute_labels(9, 30, 11, 30) + _minute_labels(13, 1, 15, 0)
)
TURNOVER_PANEL_AXIS_LABELS = frozenset(
    {
        "09:30", "09:45", "10:00", "10:15", "10:30", "10:45",
        "11:00", "11:15", "11:30", "13:15", "13:30", "13:45",
        "14:00", "14:15", "14:30", "14:45", "15:00",
    }
)


class TurnoverPanelPointQualityError(ValueError):
    pass


class TurnoverPanelTimeGridError(TurnoverPanelPointQualityError):
    pass


@dataclass(frozen=True, slots=True)
class TurnoverPanelMinuteInput:
    time: str
    amount_yuan: Decimal


@dataclass(frozen=True, slots=True)
class TurnoverPanelAverageInput:
    avg5d_yuan: Decimal | None
    avg20d_yuan: Decimal | None
    available5d_count: int
    available20d_count: int


@dataclass(frozen=True, slots=True)
class TurnoverPanelAmount:
    amount_yi: int | None
    display_text: str
    direction: str


@dataclass(frozen=True, slots=True)
class TurnoverPanelAverage:
    amount_yi: int | None
    display_text: str
    direction: str
    reference_label: str


@dataclass(frozen=True, slots=True)
class TurnoverPanelSummary:
    current: TurnoverPanelAmount
    previous: TurnoverPanelAmount
    delta: TurnoverPanelAmount
    avg5d: TurnoverPanelAverage
    avg20d: TurnoverPanelAverage


@dataclass(frozen=True, slots=True)
class TurnoverPanelAxisTick:
    value_yi: int
    display_text: str


@dataclass(frozen=True, slots=True)
class TurnoverPanelAxis:
    min_yi: int
    max_yi: int
    zero_yi: int | None
    ticks: tuple[TurnoverPanelAxisTick, ...]


@dataclass(frozen=True, slots=True)
class TurnoverPanelSeriesPoint:
    time: str
    show_axis_label: bool
    current_amount_yi: int | None
    current_display_text: str
    previous_amount_yi: int | None
    previous_display_text: str
    delta_amount_yi: int | None
    delta_display_text: str
    delta_direction: str


@dataclass(frozen=True, slots=True)
class TurnoverPanelCalculation:
    summary: TurnoverPanelSummary
    upper_axis: TurnoverPanelAxis
    delta_axis: TurnoverPanelAxis | None
    series: tuple[TurnoverPanelSeriesPoint, ...]


class TurnoverPanelCalculator:
    def calculate(
        self,
        *,
        current: tuple[TurnoverPanelMinuteInput, ...],
        previous: tuple[TurnoverPanelMinuteInput, ...] | None,
        averages: TurnoverPanelAverageInput | None,
    ) -> TurnoverPanelCalculation:
        self._validate_points(current, label="current")
        if previous is not None:
            self._validate_points(previous, label="previous")
            if tuple(point.time for point in previous) != tuple(
                point.time for point in current
            ):
                raise TurnoverPanelTimeGridError(
                    "current and previous time grids differ"
                )

        current_cumulative = Decimal("0")
        previous_cumulative = Decimal("0")
        last_delta_exact = Decimal("0")
        current_values: list[int] = []
        previous_values: list[int] = []
        delta_values: list[int] = []
        series: list[TurnoverPanelSeriesPoint] = []

        for index, current_point in enumerate(current):
            current_cumulative += current_point.amount_yuan
            current_yi = self.round_yi(current_cumulative)
            current_values.append(current_yi)

            previous_yi: int | None = None
            delta_yi: int | None = None
            delta_direction = "flat"
            if previous is not None:
                previous_cumulative += previous[index].amount_yuan
                last_delta_exact = current_cumulative - previous_cumulative
                previous_yi = self.round_yi(previous_cumulative)
                delta_yi = self.round_yi(last_delta_exact)
                previous_values.append(previous_yi)
                delta_values.append(delta_yi)
                delta_direction = self.direction(last_delta_exact)

            series.append(
                TurnoverPanelSeriesPoint(
                    time=current_point.time,
                    show_axis_label=current_point.time in TURNOVER_PANEL_AXIS_LABELS,
                    current_amount_yi=current_yi,
                    current_display_text=self.display_amount(current_yi),
                    previous_amount_yi=previous_yi,
                    previous_display_text=self.display_amount(previous_yi),
                    delta_amount_yi=delta_yi,
                    delta_display_text=self.display_amount(delta_yi, signed=True),
                    delta_direction=delta_direction,
                )
            )

        current_summary = TurnoverPanelAmount(
            amount_yi=current_values[-1],
            display_text=self.display_amount(current_values[-1]),
            direction="neutral",
        )
        if previous is None:
            previous_summary = self.empty_amount()
            delta_summary = self.empty_amount()
            delta_axis = None
        else:
            previous_summary = TurnoverPanelAmount(
                amount_yi=previous_values[-1],
                display_text=self.display_amount(previous_values[-1]),
                direction="neutral",
            )
            delta_summary = TurnoverPanelAmount(
                amount_yi=delta_values[-1],
                display_text=self.display_amount(delta_values[-1], signed=True),
                direction=self.direction(last_delta_exact),
            )
            delta_axis = self.build_delta_axis(delta_values)

        avg5d = self.average_summary(
            days=5,
            amount_yuan=averages.avg5d_yuan if averages is not None else None,
        )
        avg20d = self.average_summary(
            days=20,
            amount_yuan=averages.avg20d_yuan if averages is not None else None,
        )
        upper_values = [
            value
            for value in (
                current_summary.amount_yi,
                previous_summary.amount_yi,
                avg5d.amount_yi,
                avg20d.amount_yi,
            )
            if value is not None
        ]
        return TurnoverPanelCalculation(
            summary=TurnoverPanelSummary(
                current=current_summary,
                previous=previous_summary,
                delta=delta_summary,
                avg5d=avg5d,
                avg20d=avg20d,
            ),
            upper_axis=self.build_cumulative_axis(upper_values),
            delta_axis=delta_axis,
            series=tuple(series),
        )

    @staticmethod
    def _validate_points(
        points: tuple[TurnoverPanelMinuteInput, ...], *, label: str
    ) -> None:
        if tuple(point.time for point in points) != TURNOVER_PANEL_MINUTE_GRID:
            raise TurnoverPanelTimeGridError(
                f"{label} minute grid must contain the exact 241-point session"
            )
        for point in points:
            if not point.amount_yuan.is_finite() or point.amount_yuan < 0:
                raise TurnoverPanelPointQualityError(
                    f"{label} contains an invalid minute amount"
                )

    @staticmethod
    def round_yi(value: Decimal) -> int:
        return int(
            (value / YUAN_PER_YI).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

    @classmethod
    def build_cumulative_axis(cls, values: list[int]) -> TurnoverPanelAxis:
        domain_max = max(values, default=0)
        if domain_max <= 0:
            ticks = [0, 1, 2, 3, 4]
        else:
            step = cls._axis_step(domain_max=domain_max, intervals=4)
            ticks = [step * index for index in range(5)]
        return cls._axis(ticks[0], ticks[-1], 0, ticks)

    @classmethod
    def build_delta_axis(cls, values: list[int]) -> TurnoverPanelAxis:
        positive_max = max((value for value in values if value > 0), default=0)
        negative_abs_max = max((-value for value in values if value < 0), default=0)
        if positive_max == 0 and negative_abs_max == 0:
            return cls._axis(-1, 1, 0, [-1, 0, 1])
        negative_ticks: list[int] = []
        if negative_abs_max > 0:
            step = cls._axis_step(domain_max=negative_abs_max, intervals=2)
            negative_ticks = [-step * 2, -step]
        positive_ticks: list[int] = []
        if positive_max > 0:
            step = cls._axis_step(domain_max=positive_max, intervals=2)
            positive_ticks = [step, step * 2]
        ticks = [*negative_ticks, 0, *positive_ticks]
        return cls._axis(ticks[0], ticks[-1], 0, ticks)

    @staticmethod
    def _axis_step(*, domain_max: int, intervals: int) -> int:
        granularity = 10 ** max(0, floor(log10(abs(domain_max))) - 1)
        raw_step = Decimal(domain_max) * Decimal("1.10") / Decimal(intervals)
        units = (raw_step / Decimal(granularity)).to_integral_value(
            rounding=ROUND_CEILING
        )
        return max(1, int(units) * granularity)

    @staticmethod
    def _axis(
        min_value: int,
        max_value: int,
        zero_value: int | None,
        ticks: list[int],
    ) -> TurnoverPanelAxis:
        return TurnoverPanelAxis(
            min_yi=min_value,
            max_yi=max_value,
            zero_yi=zero_value,
            ticks=tuple(
                TurnoverPanelAxisTick(
                    value_yi=value,
                    display_text="0" if value == 0 else f"{value:,}亿",
                )
                for value in ticks
            ),
        )

    @staticmethod
    def direction(value: Decimal) -> str:
        if value > 0:
            return "up"
        if value < 0:
            return "down"
        return "flat"

    @staticmethod
    def display_amount(value: int | None, *, signed: bool = False) -> str:
        if value is None:
            return "--"
        prefix = "+" if signed and value > 0 else ""
        return f"{prefix}{value:,}亿"

    @staticmethod
    def empty_amount() -> TurnoverPanelAmount:
        return TurnoverPanelAmount(None, "--", "neutral")

    @classmethod
    def average_summary(
        cls, *, days: int, amount_yuan: Decimal | None
    ) -> TurnoverPanelAverage:
        amount_yi = cls.round_yi(amount_yuan) if amount_yuan is not None else None
        display_text = cls.display_amount(amount_yi)
        return TurnoverPanelAverage(
            amount_yi=amount_yi,
            display_text=display_text,
            direction="neutral",
            reference_label=f"{days}日均值 {display_text}",
        )
