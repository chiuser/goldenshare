"""Date selection and calendar validation shared by the index period readers."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from goldenshare_technical_indicators.errors import ResourceLimitError, SourceContractError, SourceUnsupportedError
from goldenshare_technical_indicators.sources.contracts import PriceReadSelection, SourceDescription

from .technical_indicator_stock_daily import DAILY_PRICE_FIELDS, scheduled_open_days


INDEX_PERIOD_KEYS = ("ts_code", "period_start_date", "trade_date")
INDEX_PERIOD_DATASETS = {"week": "index_weekly", "month": "index_monthly"}


@dataclass(frozen=True, slots=True)
class IndexPeriodDates:
    keys: tuple[tuple[date, date], ...]
    calendar_start: date
    calendar_end: date
    file_version: tuple[int, int, int, int] | None = None

    def check_delivery(self, offset, keys):
        if tuple(keys) != self.keys[offset:offset + len(keys)]:
            raise SourceContractError("Delivered index period dates differ from the selected dates")


def require_index_period(requirement, backend):
    if (requirement.target.backend != backend
            or requirement.target.dataset_id != INDEX_PERIOD_DATASETS.get(requirement.period)
            or requirement.target_adjustment != "none"):
        raise SourceUnsupportedError("This reader supports unadjusted index weekly and monthly bars")


def period_bounds(day, period):
    if period == "week":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=4)
    return day.replace(day=1), day.replace(day=monthrange(day.year, day.month)[1])


def period_request_start(requirement):
    start, end = period_bounds(requirement.start, requirement.period)
    return start if requirement.start <= end else start + timedelta(days=7)


def check_period_key(key, period):
    start, cutoff = key
    if type(start) is not date or type(cutoff) is not date:
        raise SourceContractError("Index period source has an invalid date")
    label, end = period_bounds(start, period)
    if not start <= cutoff <= end:
        raise SourceContractError(f"Index period cutoff {cutoff} does not belong to the period starting {label}")
    return label


def check_index_period_cutoff(cutoff, requirement, period_end):
    if requirement.end < period_end and cutoff > requirement.end:
        raise SourceUnsupportedError("Source has only a later version of the unfinished period")


def preceding_limit(config, requirement, target_rows):
    available = config.max_input_rows - target_rows
    if available < 0:
        raise ResourceLimitError("Selected input exceeds max_input_rows")
    history = requirement.history
    needs_origin = history.requires_source_origin or history.warmup_rows > available
    return (available if needs_origin else history.warmup_rows), needs_origin


def index_period_projection(requirement):
    fields = requirement.history.fields
    if not fields <= set(DAILY_PRICE_FIELDS):
        raise SourceContractError("The source cannot supply the requested fields")
    day = 'b."period_start_date"'
    start = f"CAST(date_trunc('{requirement.period}', {day}) AS DATE)"
    end = f"({start} + 4)" if requirement.period == "week" else f"last_day({day})"
    cutoff = 'CAST(b."trade_date" AS DATE)'
    value_columns = tuple(("vol" if field == "volume" else field, field)
                          for field in DAILY_PRICE_FIELDS if field in fields)
    return (
        (*INDEX_PERIOD_KEYS, *(column for column, _ in value_columns)),
        (("trade_date", cutoff), ("period_start", start), ("period_end", end), ("source_as_of", cutoff),
         *((field, f'CAST(b."{column}" AS DOUBLE)') for column, field in value_columns)),
    )


def describe_index_period(requirement, context, targets, preceding, source_first, source_latest,
                          *, path=None, row_groups=(), file_version=None):
    """Receive ascending date pairs, including at most one extra preceding pair."""
    physical, standard = index_period_projection(requirement)
    selection = PriceReadSelection(None, None, None, None, 0, 0, True, ())
    if len(targets) > context.config.max_output_rows:
        raise ResourceLimitError("Target positions exceed max_output_rows")
    if targets:
        wanted, needs_origin = preceding_limit(context.config, requirement, len(targets))
        reached_origin = len(preceding) <= wanted
        if needs_origin and not reached_origin:
            raise ResourceLimitError("The required warmup cannot fit without reaching the source origin")
        history_rows = min(len(preceding), wanted)
        keys = (*preceding[len(preceding) - history_rows:], *targets)
        positions = tuple(check_period_key(key, requirement.period) for key in keys)
        if (any(a >= b for a, b in zip(positions, positions[1:]))
                or not reached_origin and check_period_key(
                    preceding[-history_rows - 1], requirement.period) >= positions[0]):
            raise SourceContractError("Index period positions are duplicated or out of order")
        selection = PriceReadSelection(
            positions[history_rows], positions[-1], positions[0], positions[-1],
            len(targets), history_rows, reached_origin, (row_groups,) if path else (),
        )
        calendar_start = max(check_period_key(source_first, requirement.period),
                             min(positions[0], period_request_start(requirement)))
        calendar_end = min(requirement.end, source_latest[1])
        context.source_state = IndexPeriodDates(keys, calendar_start, calendar_end, file_version)
    return SourceDescription(
        source_id=requirement.target.dataset_id, contract_version="1", input_adjustment="none",
        basis_rule=None, basis_date=None, basis_value=None, price_unit="index_point",
        volume_unit="lot" if path else "share", amount_unit="thousand_CNY" if path else "CNY",
        timezone="Asia/Shanghai", period_label_rule="period_start", history_origin_rule="earliest_available_formal_row",
        available_through=source_latest[1] if source_latest else None, supports_partial_period=True,
        supported_adjustment_paths=(("none", "none"),), converted=False, selection=selection,
        price_paths=(path,) if path and targets else (), source_projection=physical, standard_projection=standard,
    )


def index_period_positions(calendar, dates, period):
    expected = {}
    for day in scheduled_open_days(calendar, dates.calendar_start, dates.calendar_end):
        expected[period_bounds(day, period)[0]] = day
    actual = {period_bounds(start, period)[0]: cutoff for start, cutoff in dates.keys}
    for label, cutoff in expected.items():
        if label not in actual:
            raise SourceContractError(f"Missing scheduled index period starting {label}")
        if actual[label] != cutoff:
            raise SourceContractError(f"Index period {label} ends on {actual[label]}, expected {cutoff}")
    if len(actual) != len(expected):
        raise SourceContractError("Index period was delivered outside the trading calendar")
    return tuple(expected)
