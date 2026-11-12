"""Accept existing stock qfq prices; fetch only the missing preceding history."""

from dataclasses import dataclass
from itertools import chain, islice

from ..errors import SourceUnsupportedError
from .contracts import PriceReadSelection, SourceBatch, SourceDescription


_DATE_FIELDS = ("trade_date", "period_start", "period_end", "source_as_of")
_PRICE_FIELDS = ("high", "low", "close")


@dataclass(frozen=True)
class _StockDailyLocator:
    description: SourceDescription

    def describe(self):
        return self.description

    def close(self):
        pass


class _StockDailyStream:
    def __init__(self, rows, source):
        self._rows, self._source = rows, source
        self._delivered = 0

    def next_batch(self, max_rows):
        import pyarrow as pa

        rows = list(islice(self._rows, max_rows))
        if not rows:
            return None
        dates = pa.array([row["trade_date"] for row in rows], type=pa.date32())
        prices = [pa.array([row[name] for row in rows], type=pa.float64()) for name in _PRICE_FIELDS]
        columns = pa.RecordBatch.from_arrays(
            [dates] * len(_DATE_FIELDS) + prices, names=_DATE_FIELDS + _PRICE_FIELDS,
        )
        first = self._delivered + 1
        self._delivered += len(rows)
        return SourceBatch(columns, first, self._delivered, None, len(rows), 0, 0)

    def release_current_batch(self):
        pass

    def close(self):
        self._rows = iter(())
        self._source.close()
        self._source = None


class StockDailyPriceSource:
    def __init__(self, rows, read_previous, *, source_id):
        self._rows = rows
        self._read_previous = read_previous
        self._source_id = source_id
        self._preceding = ()

    def create_locator(self, executor, requirement, *, read_context):
        start, end = self._rows[0]["trade_date"], self._rows[-1]["trade_date"]
        warmup = requirement.history.warmup_rows
        read_context.record_price_rows(len(self._rows))
        if warmup:
            self._preceding = self._read_previous(start, warmup)
            read_context.record_price_rows(len(self._preceding))
        read_start = self._preceding[0]["trade_date"] if self._preceding else start
        return _StockDailyLocator(SourceDescription(
            source_id=self._source_id, contract_version="1.0.0", input_adjustment="qfq",
            basis_rule=None, basis_date=None, basis_value=None, price_unit="CNY",
            volume_unit="lot", amount_unit="thousand_CNY", timezone="Asia/Shanghai",
            period_label_rule="trade_date", history_origin_rule="available_stock_factor_pro_rows",
            available_through=end, supports_partial_period=False,
            supported_adjustment_paths=(("qfq", "qfq"),), converted=False,
            selection=PriceReadSelection(start, end, read_start, end, len(self._rows),
                                         len(self._preceding), len(self._preceding) < warmup, ()),
            standard_projection=tuple((name, name) for name in _DATE_FIELDS + _PRICE_FIELDS),
        ))

    def open(self, executor, description, requirement, *, read_context):
        return _StockDailyStream(chain(self._preceding, self._rows), self)

    def prepare_basis(self, executor, description, requirement, *, table_name, read_context):
        raise SourceUnsupportedError("Stock daily input already uses the target qfq prices")

    def prepare_factors(self, executor, description, requirement, trade_dates, *, table_name, read_context):
        raise SourceUnsupportedError("Stock daily input already uses the target qfq prices")

    def close(self):
        self._rows = self._preceding = ()
        self._read_previous = None
