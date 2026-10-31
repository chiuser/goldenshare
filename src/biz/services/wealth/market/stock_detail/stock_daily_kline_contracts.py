"""Immutable stock daily request and detached database rows (integration LLD §04)."""

from dataclasses import dataclass
from datetime import date

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContext


@dataclass(frozen=True, slots=True)
class StockDailyKlineRequest:
    ts_code: str
    period: str
    adjustment: str
    trade_date: date | None
    start_date: date | None
    end_date: date | None
    limit: int
    debug: bool

    def __post_init__(self) -> None:
        if any(type(value) is not str for value in (self.ts_code, self.period, self.adjustment)):
            raise TypeError("Stock daily request requires string identifiers")
        if any(value is not None and type(value) is not date
               for value in (self.trade_date, self.start_date, self.end_date)):
            raise TypeError("Stock daily request dates require date or None")
        if type(self.limit) is not int or type(self.debug) is not bool:
            raise TypeError("Stock daily request requires integer limit and boolean debug")


@dataclass(frozen=True, slots=True)
class StockDailyKlineRow:
    trade_date: date
    open_qfq: float | None
    high_qfq: float | None
    low_qfq: float | None
    close_qfq: float | None
    pre_close: float | None
    change: float | None
    pct_chg: float | None
    vol: float | None
    amount: float | None
    turnover_rate: float | None
    volume_ratio: float | None

    def __post_init__(self) -> None:
        if type(self.trade_date) is not date:
            raise TypeError("Stock daily row requires date")
        values = (
            self.open_qfq, self.high_qfq, self.low_qfq, self.close_qfq,
            self.pre_close, self.change, self.pct_chg, self.vol, self.amount,
            self.turnover_rate, self.volume_ratio,
        )
        if any(value is not None and type(value) not in (int, float) for value in values):
            raise TypeError("Stock daily row requires numeric scalars or None")


@dataclass(frozen=True, slots=True)
class StockDailyKlineInput:
    request: StockDailyKlineRequest
    context: MarketPageContext
    ts_code: str
    name: str
    query_end_date: date
    bars: tuple[StockDailyKlineRow, ...]

    def __post_init__(self) -> None:
        rows = tuple(self.bars)
        if not all(isinstance(row, StockDailyKlineRow) for row in rows):
            raise TypeError("Stock daily input requires StockDailyKlineRow items")
        object.__setattr__(self, "bars", rows)
        if not isinstance(self.request, StockDailyKlineRequest):
            raise TypeError("Stock daily input requires StockDailyKlineRequest")
        if not isinstance(self.context, MarketPageContext):
            raise TypeError("Stock daily input requires MarketPageContext")
        if type(self.ts_code) is not str or type(self.name) is not str:
            raise TypeError("Stock daily input requires string identity fields")
        if type(self.query_end_date) is not date:
            raise TypeError("Stock daily input requires date query_end_date")
