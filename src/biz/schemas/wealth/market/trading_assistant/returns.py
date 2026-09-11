"""Curve and calendar output contracts, design §4.30 and §4.35.

No clock, quote lookup or calculation occurs here. All dates and results are
supplied by the caller; validators reject inconsistent output, never fill it.
"""

from datetime import date, timedelta
import calendar
from typing import Literal

from pydantic import StrictBool, StrictStr, model_validator

from .common import Contract, Coverage, Page, ReadContext, ReadState, ReturnTriple, Scope, StockRef
from .positions import AccountRound
from .scopes import DateRange, DayScope, RecordsScope
from .value_types import BusinessDate, Count, Instant, Money, Month, ReturnPct


class CurvePoint(Coverage, ReturnTriple):
    periodStartDate: BusinessDate
    periodEndDate: BusinessDate
    isPeriodEnded: StrictBool

    @model_validator(mode="after")
    def valid_period(self):
        if self.periodStartDate > self.periodEndDate:
            raise ValueError("Inverted curve period")
        if self.dataStatus == "Ready" and self.profitAmount is None:
            raise ValueError("Ready curve point requires a complete return")
        if self.dataStatus in ("Empty", "Delayed", "Error", "Recalculating") and self.profitAmount is not None:
            raise ValueError("Unavailable curve point cannot contain return values")
        return self


class CurveResponse(Contract):
    scope: Scope
    requestedStartDate: BusinessDate
    requestedEndDate: BusinessDate
    granularity: Literal["DAY", "WEEK", "MONTH"]
    readContext: ReadContext
    coverage: Coverage
    points: list[CurvePoint]

    @model_validator(mode="after")
    def ordered_periods(self):
        if self.requestedStartDate > self.requestedEndDate:
            raise ValueError("Inverted requested range")
        previous_end = None
        for point in self.points:
            if previous_end is not None and point.periodStartDate <= previous_end:
                raise ValueError("Overlapping or unordered curve periods")
            previous_end = point.periodEndDate
        return self


class CalendarDay(ReturnTriple):
    date: BusinessDate
    inSelectedMonth: StrictBool
    temporalState: Literal["PAST", "TODAY", "FUTURE"]
    calculationState: ReadState | None
    reason: StrictStr | None
    valuationAt: Instant | None
    readContext: ReadContext | None

    @model_validator(mode="after")
    def valid_day_result(self):
        if self.temporalState == "FUTURE":
            if any(value is not None for value in (
                self.profitAmount, self.calculationState, self.reason, self.valuationAt, self.readContext
            )):
                raise ValueError("Future calendar cells cannot have results")
        else:
            if self.calculationState is None:
                raise ValueError("Nonfuture cell requires calculation state")
            if (self.calculationState == "Ready") != (self.profitAmount is not None):
                raise ValueError("Only complete Ready days have return values")
            if self.profitAmount is None and (self.reason is None or not self.reason.strip()):
                raise ValueError("Unavailable day requires a safe reason")
            if self.calculationState == "Ready" and self.readContext is None:
                raise ValueError("Ready day requires read context")
        return self


class MonthSummary(Contract):
    periodProfitAmount: Money | None
    periodCapitalAmount: Money | None
    periodReturnPct: ReturnPct | None
    positiveDayCount: Count
    negativeDayCount: Count
    flatDayCount: Count
    computedDayCount: Count
    minDailyReturnPct: ReturnPct | None
    minDailyReturnDates: list[BusinessDate]
    closedTradeCount: Count | None
    closedProfitAmount: Money | None
    periodCoverage: Coverage
    dailyStatsCoverage: Coverage
    closedCoverage: Coverage

    @model_validator(mode="after")
    def summary_combinations(self):
        ReturnTriple(profitAmount=self.periodProfitAmount, capitalAmount=self.periodCapitalAmount,
                     returnPct=self.periodReturnPct)
        if self.computedDayCount != self.positiveDayCount + self.negativeDayCount + self.flatDayCount:
            raise ValueError("Computed day count mismatch")
        if (self.closedTradeCount is None) != (self.closedProfitAmount is None):
            raise ValueError("Incomplete closed trade summary")
        dates = self.minDailyReturnDates
        if dates != sorted(set(dates)):
            raise ValueError("Extreme dates must be sorted and unique")
        if (self.minDailyReturnPct is None) != (not dates):
            raise ValueError("Extreme value and dates must agree")
        if self.computedDayCount == 0 and self.minDailyReturnPct is not None:
            raise ValueError("No computed days, no extreme")
        return self


class CalendarResponse(Contract):
    month: Month
    today: BusinessDate
    calculatedThrough: BusinessDate | None
    days: list[CalendarDay]
    monthSummary: MonthSummary
    readContext: ReadContext

    @model_validator(mode="after")
    def validate_grid(self):
        first = date.fromisoformat(self.month + "-01")
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        start = first - timedelta(days=first.weekday())
        # Weekends are not emitted; avoiding the unused trailing Sunday also
        # allows December 9999 without overflowing Python's date range.
        end = last + timedelta(days=max(0, 4 - last.weekday()))
        expected = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                expected.append(current.isoformat())
            if current == end:
                break
            current += timedelta(days=1)
        if [day.date for day in self.days] != expected:
            raise ValueError("Calendar must contain the complete ordered weekday grid")
        for day in self.days:
            temporal = "PAST" if day.date < self.today else "FUTURE" if day.date > self.today else "TODAY"
            if day.temporalState != temporal or day.inSelectedMonth != (day.date[:7] == self.month):
                raise ValueError("Calendar cell date identity mismatch")
        if any(value[:7] != self.month for value in self.monthSummary.minDailyReturnDates):
            raise ValueError("Month extreme cannot include an adjacent month")
        return self


class DayDetail(ReturnTriple):
    scope: Scope
    date: BusinessDate
    readContext: ReadContext
    coverage: Coverage
    closedTradeCount: Count | None
    closedProfitAmount: Money | None
    commissionAmount: Money | None
    stampTaxAmount: Money | None
    closedDataStatus: ReadState
    feeDataStatus: ReadState
    contributionsScope: DayScope
    recordsScope: RecordsScope

    @model_validator(mode="after")
    def day_identity(self):
        if self.date != self.contributionsScope.date or self.scope != self.contributionsScope.scope:
            raise ValueError("Contribution scope does not match selected day")
        if self.coverage.dataStatus == "Ready" and self.profitAmount is None:
            raise ValueError("Ready day requires a complete return")
        if self.coverage.dataStatus != "Ready" and self.profitAmount is not None:
            raise ValueError("Incomplete day cannot expose a full-day return")
        if (self.closedTradeCount is None) != (self.closedProfitAmount is None):
            raise ValueError("Incomplete closed trade summary")
        if (self.commissionAmount is None) != (self.stampTaxAmount is None):
            raise ValueError("Incomplete actual fee summary")
        return self


class DayContribution(ReturnTriple):
    stockRef: StockRef
    accountRounds: list[AccountRound]
    dataStatus: ReadState
    reason: StrictStr | None


class DayContributions(Page[DayContribution]):
    scope: Scope
    date: BusinessDate
    readContext: ReadContext
    coverage: Coverage
    totalCount: Count | None
    totalProfitAmount: Money | None


class DailyReturnExtreme(Contract):
    returnPct: ReturnPct
    dates: list[BusinessDate]

    @model_validator(mode="after")
    def ordered_dates(self):
        if not self.dates or self.dates != sorted(set(self.dates)):
            raise ValueError("An extreme requires all ordered unique dates")
        return self


class DailyStats(Contract):
    positiveDayCount: Count | None
    negativeDayCount: Count | None
    flatDayCount: Count | None
    computedDayCount: Count | None
    maxDailyReturn: DailyReturnExtreme | None
    minDailyReturn: DailyReturnExtreme | None
    dataStatus: ReadState
    resultKind: Literal["HAS_VALID_DAYS", "NO_VALID_DAYS", "UNDETERMINED"]
    isFinal: StrictBool
    reason: StrictStr | None

    @model_validator(mode="after")
    def valid_results(self):
        counts = (self.positiveDayCount, self.negativeDayCount, self.flatDayCount, self.computedDayCount)
        if self.resultKind == "UNDETERMINED":
            if any(item is not None for item in (*counts, self.maxDailyReturn, self.minDailyReturn)):
                raise ValueError("Undetermined statistics cannot invent counts or extremes")
        else:
            if any(item is None for item in counts) or sum(counts[:3]) != counts[3]:
                raise ValueError("Complete day classification required")
            if self.resultKind == "NO_VALID_DAYS":
                if self.computedDayCount != 0 or self.maxDailyReturn is not None or self.minDailyReturn is not None:
                    raise ValueError("No valid days must have zero counts and no extremes")
            elif self.computedDayCount == 0 or self.maxDailyReturn is None or self.minDailyReturn is None:
                raise ValueError("Valid days require counts and both extremes")
        if self.dataStatus == "Partial" and self.isFinal:
            raise ValueError("Partial statistics cannot be final")
        return self


class ClosedTradesReview(Contract):
    closedTradeCount: Count | None
    dataStatus: ReadState
    reason: StrictStr | None


class CompletedRoundsReview(Contract):
    completedRoundCount: Count | None
    dataStatus: ReadState
    reason: StrictStr | None


class ReviewResponse(DateRange):
    scope: Scope
    readContext: ReadContext
    coverage: Coverage
    dailyStats: DailyStats
    closedTrades: ClosedTradesReview
    completedRounds: CompletedRoundsReview

    @model_validator(mode="after")
    def extremes_in_selected_range(self):
        for extreme in (self.dailyStats.maxDailyReturn, self.dailyStats.minDailyReturn):
            if extreme is not None and any(
                not self.requestedStartDate <= day <= self.requestedEndDate for day in extreme.dates
            ):
                raise ValueError("Review extreme outside selected dates")
        return self
