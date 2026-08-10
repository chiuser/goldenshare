from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Protocol, Sequence


FORMULA_KEY = "high-low-ema-hysteresis"
FORMULA_VERSION = "sse-daily-trend-channel-v1"
SHORT_PERIOD = 25
LONG_PERIOD = 90
SHORT_ALPHA = 2.0 / 26.0
LONG_ALPHA = 2.0 / 91.0
SHORT_DECAY = 1.0 - SHORT_ALPHA
LONG_DECAY = 1.0 - LONG_ALPHA
MAX_SOURCE_ROWS = 10_000
PRICE_QUANTUM = Decimal("0.0001")

PositionValue = Literal["ABOVE", "INSIDE", "BELOW"]
StateValue = Literal["UNKNOWN", "UP", "DOWN"]
CombinedStateValue = Literal[
    "UNKNOWN",
    "UP_UP",
    "UP_DOWN",
    "DOWN_UP",
    "DOWN_DOWN",
]


class TrendChannelInputRow(Protocol):
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ComputedTrendChannelBand:
    upper_raw: float
    lower_raw: float
    upper: Decimal
    lower: Decimal
    position: PositionValue
    state: StateValue


@dataclass(frozen=True, slots=True)
class ComputedTrendChannelRow:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    short_channel: ComputedTrendChannelBand
    long_channel: ComputedTrendChannelBand
    combined_state: CombinedStateValue


class TrendChannelInputError(ValueError):
    def __init__(
        self,
        *,
        reason_code: str,
        trade_date: date | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.trade_date = trade_date
        message = (
            reason_code
            if trade_date is None
            else f"{reason_code}: {trade_date.isoformat()}"
        )
        super().__init__(message)


class TrendChannelInvariantError(RuntimeError):
    def __init__(
        self,
        *,
        reason_code: str,
        trade_date: date | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.trade_date = trade_date
        message = (
            reason_code
            if trade_date is None
            else f"{reason_code}: {trade_date.isoformat()}"
        )
        super().__init__(message)


class TrendChannelCalculator:
    def calculate(
        self,
        rows: Sequence[TrendChannelInputRow],
    ) -> tuple[ComputedTrendChannelRow, ...]:
        _validate_rows(rows)
        if not rows:
            return ()

        output: list[ComputedTrendChannelRow] = []
        short_upper = 0.0
        short_lower = 0.0
        long_upper = 0.0
        long_lower = 0.0
        short_state: StateValue = "UNKNOWN"
        long_state: StateValue = "UNKNOWN"
        band_type = ComputedTrendChannelBand
        row_type = ComputedTrendChannelRow
        quantize_price = _quantize_price

        for index, row in enumerate(rows):
            high_float = float(row.high)
            low_float = float(row.low)
            close_float = float(row.close)
            if index == 0:
                short_upper = high_float
                short_lower = low_float
                long_upper = high_float
                long_lower = low_float
            else:
                short_upper = SHORT_ALPHA * high_float + SHORT_DECAY * short_upper
                short_lower = SHORT_ALPHA * low_float + SHORT_DECAY * short_lower
                long_upper = LONG_ALPHA * high_float + LONG_DECAY * long_upper
                long_lower = LONG_ALPHA * low_float + LONG_DECAY * long_lower

            if short_upper < short_lower:
                raise TrendChannelInvariantError(
                    reason_code="short_channel_inverted",
                    trade_date=row.trade_date,
                )
            if long_upper < long_lower:
                raise TrendChannelInvariantError(
                    reason_code="long_channel_inverted",
                    trade_date=row.trade_date,
                )

            if close_float > short_upper:
                short_position: PositionValue = "ABOVE"
                short_state = "UP"
            elif close_float < short_lower:
                short_position = "BELOW"
                short_state = "DOWN"
            else:
                short_position = "INSIDE"

            if close_float > long_upper:
                long_position: PositionValue = "ABOVE"
                long_state = "UP"
            elif close_float < long_lower:
                long_position = "BELOW"
                long_state = "DOWN"
            else:
                long_position = "INSIDE"

            if short_state == "UNKNOWN" or long_state == "UNKNOWN":
                combined_state: CombinedStateValue = "UNKNOWN"
            elif short_state == "UP":
                combined_state = "UP_UP" if long_state == "UP" else "UP_DOWN"
            else:
                combined_state = "DOWN_UP" if long_state == "UP" else "DOWN_DOWN"

            output.append(
                row_type(
                    trade_date=row.trade_date,
                    open=row.open,  # type: ignore[arg-type]
                    high=row.high,  # type: ignore[arg-type]
                    low=row.low,  # type: ignore[arg-type]
                    close=row.close,  # type: ignore[arg-type]
                    short_channel=band_type(
                        upper_raw=short_upper,
                        lower_raw=short_lower,
                        upper=quantize_price(short_upper),
                        lower=quantize_price(short_lower),
                        position=short_position,
                        state=short_state,
                    ),
                    long_channel=band_type(
                        upper_raw=long_upper,
                        lower_raw=long_lower,
                        upper=quantize_price(long_upper),
                        lower=quantize_price(long_lower),
                        position=long_position,
                        state=long_state,
                    ),
                    combined_state=combined_state,
                )
            )

        return tuple(output)


def _validate_rows(
    rows: Sequence[TrendChannelInputRow],
) -> None:
    if len(rows) > MAX_SOURCE_ROWS:
        raise TrendChannelInputError(reason_code="source_row_limit_exceeded")

    seen_dates: set[date] = set()
    previous_date: date | None = None

    for row in rows:
        trade_date = row.trade_date
        if trade_date in seen_dates:
            raise TrendChannelInputError(
                reason_code="duplicate_trade_date",
                trade_date=trade_date,
            )
        if previous_date is not None and trade_date < previous_date:
            raise TrendChannelInputError(
                reason_code="trade_date_not_strictly_ascending",
                trade_date=trade_date,
            )
        seen_dates.add(trade_date)
        previous_date = trade_date

        if row.open is None or row.high is None or row.low is None or row.close is None:
            raise TrendChannelInputError(
                reason_code="missing_ohlc",
                trade_date=trade_date,
            )

        open_float = float(row.open)
        high_float = float(row.high)
        low_float = float(row.low)
        close_float = float(row.close)

        if not (
            math.isfinite(open_float)
            and math.isfinite(high_float)
            and math.isfinite(low_float)
            and math.isfinite(close_float)
        ):
            raise TrendChannelInputError(
                reason_code="non_finite_ohlc",
                trade_date=trade_date,
            )
        if (
            open_float <= 0.0
            or high_float <= 0.0
            or low_float <= 0.0
            or close_float <= 0.0
        ):
            raise TrendChannelInputError(
                reason_code="non_positive_ohlc",
                trade_date=trade_date,
            )
        if not (
            low_float
            <= min(open_float, close_float)
            <= max(open_float, close_float)
            <= high_float
        ):
            raise TrendChannelInputError(
                reason_code="invalid_ohlc_range",
                trade_date=trade_date,
            )


def _quantize_price(value: float) -> Decimal:
    return Decimal(str(value)).quantize(
        PRICE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
