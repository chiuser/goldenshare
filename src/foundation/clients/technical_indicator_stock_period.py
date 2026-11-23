"""Choose and deliver already adjusted stock candles for either runtime."""

from dataclasses import dataclass
from datetime import date, timedelta

from goldenshare_technical_indicators.contracts import PeriodBarMetadata
from goldenshare_technical_indicators.errors import ResourceLimitError, SourceContractError, SourceUnsupportedError
from goldenshare_technical_indicators.sources.contracts import PriceReadSelection, SourceBatch, SourceDescription

from .technical_indicator_index_period import period_bounds, preceding_limit


STOCK_PERIOD_DATASETS = {"week": "stock_weekly", "month": "stock_monthly"}
FIRST_STOCK_WEEK = date(2013, 12, 30)  # The week containing 2014-01-02.
STOCK_PERIOD_PAGE_FIELDS = ("end_date", "pct_chg")
_PRICE_FIELDS = (
    *((f"{name}_qfq", name) for name in ("open", "high", "low", "close")),
    ("vol", "volume"), ("amount", "amount"),
)


def require_stock_period(requirement, backend):
    if (requirement.target.backend != backend or requirement.target_adjustment != "qfq"
            or STOCK_PERIOD_DATASETS.get(requirement.period) != requirement.target.dataset_id):
        raise SourceUnsupportedError("This reader requires a forward-adjusted stock week or month")


def stock_period_projection(requirement):
    fields = requirement.history.fields
    value_columns = tuple((column, field) for column, field in _PRICE_FIELDS if field in fields)
    bar_date = 'b."trade_date"'
    start = f"CAST(date_trunc('{requirement.period}', {bar_date}) AS DATE)"
    end = f"({start} + 4)" if requirement.period == "week" else f"last_day({bar_date})"
    physical = ("trade_date", *(column for column, _ in value_columns))
    standard = (("trade_date", bar_date), ("period_start", start), ("period_end", end),
                ("source_as_of", bar_date),
                *((field, f'CAST(b."{column}" AS DOUBLE)') for column, field in value_columns))
    return physical, standard


@dataclass(frozen=True, slots=True)
class StockPeriodInput:
    rows: tuple[dict, ...]
    positions: tuple[date, ...]


def describe_stock_period(requirement, context, read_rows):
    """Read disjoint target and prehistory windows, each in descending order."""
    period = requirement.period
    physical, standard = stock_period_projection(requirement)
    origin = FIRST_STOCK_WEEK if period == "week" else date.min
    start = max(origin, period_bounds(requirement.start, period)[0])
    end = period_bounds(requirement.end, period)[1]
    limit = requirement.output_limit(context.config)
    targets = read_rows(start, end, limit + 1, (*physical, *STOCK_PERIOD_PAGE_FIELDS)) if start <= end else []
    context.record_locator_rows(len(targets))
    if len(targets) > limit:
        raise ResourceLimitError("Target positions exceed max_output_rows")
    selection = PriceReadSelection(None, None, None, None, 0, 0, True, ())
    metadata = ()
    if targets:
        wanted, needs_origin = preceding_limit(context.config, requirement, len(targets))
        previous = []
        if start > origin and (wanted or needs_origin):
            previous = read_rows(origin, start - timedelta(days=1), wanted + int(needs_origin), physical)
        context.record_locator_rows(len(previous))
        if len(previous) > wanted:
            raise ResourceLimitError("The required warmup cannot fit without reaching the source origin")
        rows = (*reversed(previous), *reversed(targets))
        positions = tuple(period_bounds(row["trade_date"], period)[0] for row in rows)
        if any(left >= right for left, right in zip(positions, positions[1:])):
            raise SourceContractError("Stock period positions are duplicated or out of order")
        preceding = len(previous)
        selection = PriceReadSelection(
            positions[preceding], positions[-1], positions[0], positions[-1], len(targets), preceding,
            positions[0] == origin or needs_origin or (wanted > 0 and preceding < wanted), (),
        )
        context.source_state = StockPeriodInput(rows, positions)
        metadata = tuple(PeriodBarMetadata(position, row["end_date"],
                                           None if row["pct_chg"] is None else float(row["pct_chg"]))
                         for position, row in zip(positions[preceding:], reversed(targets), strict=True))
    return SourceDescription(
        source_id=requirement.target.dataset_id, contract_version="1", input_adjustment="qfq",
        basis_rule=None, basis_date=None, basis_value=None, price_unit="CNY", volume_unit="lot",
        amount_unit="thousand_CNY", timezone="Asia/Shanghai", period_label_rule="period_start",
        history_origin_rule="earliest_available_formal_partition", available_through=None,
        supports_partial_period=True, supported_adjustment_paths=(("qfq", "qfq"),), converted=False,
        selection=selection, source_projection=physical, standard_projection=standard, period_bars=metadata,
    )


class StockPeriodStream:
    def __init__(self, description, requirement, context, control):
        import pyarrow as pa

        fields = {"trade_date": pa.date32(), "vol": pa.decimal128(20, 4), "amount": pa.decimal128(20, 4)}
        schema = pa.schema((name, fields.get(name, pa.decimal128(18, 4))) for name in description.source_projection)
        try:
            table = pa.Table.from_pylist(context.source_state.rows, schema=schema)
        except (pa.ArrowException, TypeError, ValueError) as exc:
            raise SourceContractError("Stock period prices do not match their declared fields") from exc
        self._reader = table.to_reader(max_chunksize=requirement.batch_rows)
        context.source_state = None
        self._context, self._control = context, control
        self._delivered = 0

    def next_batch(self, max_rows):
        self._control.check_active()
        batch = next(self._reader, None)
        if batch is None:
            return None
        count = batch.num_rows
        self._context.record_price_rows(count)
        first = self._delivered + 1
        self._delivered += count
        return SourceBatch(batch, first, self._delivered, count, count, 0, 0)

    def release_current_batch(self):
        pass  # The stream keeps no reference to the returned batch.

    def close(self):
        self._reader.close()
