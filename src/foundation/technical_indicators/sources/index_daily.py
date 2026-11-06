"""Serve the page's existing index prices and its preceding daily history."""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import chain, islice
from typing import Any

from ..errors import SourceUnsupportedError
from .contracts import PriceReadSelection, ReadRequirement, SourceBatch, SourceDescription
from .read_context import SourceReadContext


PriceRow = Mapping[str, Any]
_DATE_FIELDS = ("trade_date", "period_start", "period_end", "source_as_of")
_PRICE_FIELDS = ("high", "low", "close")


@dataclass(frozen=True)
class _IndexDailyLocator:
    description: SourceDescription

    def describe(self) -> SourceDescription:
        return self.description

    def close(self) -> None:
        pass


class _IndexDailyStream:
    def __init__(self, rows: Iterator[PriceRow]) -> None:
        self._rows = rows
        self._delivered = 0

    def next_batch(self, max_rows: int) -> SourceBatch | None:
        import pyarrow as pa

        rows = list(islice(self._rows, max_rows))
        if not rows:
            return None
        dates = pa.array([row["trade_date"] for row in rows], type=pa.date32())
        prices = [pa.array([row[name] for row in rows], type=pa.float64()) for name in _PRICE_FIELDS]
        columns = pa.RecordBatch.from_arrays([dates] * len(_DATE_FIELDS) + prices, names=_DATE_FIELDS + _PRICE_FIELDS)
        first = self._delivered + 1
        self._delivered += len(rows)
        return SourceBatch(columns, first, self._delivered, None, len(rows), 0, 0)

    def release_current_batch(self) -> None:
        pass

    def close(self) -> None:
        self._rows = iter(())


class IndexDailyPriceSource:
    def __init__(
        self, rows: Sequence[PriceRow], read_previous: Callable[[date, int], Sequence[PriceRow]],
        *, source_origin: date, source_id: str,
    ) -> None:
        self._rows = rows
        self._read_previous = read_previous
        self._source_origin = source_origin
        self._source_id = source_id
        self._preceding: Sequence[PriceRow] = ()

    @property
    def preceding_rows(self) -> int:
        return len(self._preceding)

    def create_locator(self, executor, requirement: ReadRequirement, *, read_context: SourceReadContext):
        start, end = self._rows[0]["trade_date"], self._rows[-1]["trade_date"]
        read_context.record_price_rows(len(self._rows))
        warmup = requirement.history.warmup_rows
        if warmup:
            self._preceding = self._read_previous(start, warmup)
            read_context.record_price_rows(len(self._preceding))
        read_start = self._preceding[0]["trade_date"] if self._preceding else start
        return _IndexDailyLocator(SourceDescription(
            source_id=self._source_id, contract_version="1.0.0", input_adjustment="none",
            basis_rule=None, basis_date=None, basis_value=None, price_unit="index_point",
            volume_unit="share", amount_unit="yuan", timezone="Asia/Shanghai",
            period_label_rule="trade_date", history_origin_rule="environment_index_factor_origin",
            available_through=end, supports_partial_period=False,
            supported_adjustment_paths=(("none", "none"),), converted=False,
            selection=PriceReadSelection(
                start, end, read_start, end, len(self._rows), len(self._preceding),
                read_start == self._source_origin, (),
            ),
            standard_projection=tuple((name, name) for name in _DATE_FIELDS + _PRICE_FIELDS),
        ))

    def open(self, executor, description, requirement, *, read_context):
        return _IndexDailyStream(chain(self._preceding, self._rows))

    def prepare_basis(self, executor, description, requirement, *, table_name, read_context):
        raise SourceUnsupportedError("Index daily input uses unadjusted prices")

    def prepare_factors(self, executor, description, requirement, trade_dates, *, table_name, read_context):
        raise SourceUnsupportedError("Index daily input uses unadjusted prices")
