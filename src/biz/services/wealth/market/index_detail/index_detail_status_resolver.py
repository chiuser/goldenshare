from __future__ import annotations

from datetime import date

from src.biz.schemas.wealth.market.index_detail import IndexDetailDataStatusDto


class IndexDetailStatusResolver:
    """Apply the frozen EMPTY > PARTIAL > DELAYED > READY priority."""

    @staticmethod
    def resolve(
        *,
        expected_trade_date: date,
        observed_trade_date: date | None,
        empty: bool,
        partial: bool,
    ) -> IndexDetailDataStatusDto:
        if empty:
            status = "EMPTY"
        elif partial:
            status = "PARTIAL"
        elif observed_trade_date is not None and observed_trade_date < expected_trade_date:
            status = "DELAYED"
        else:
            status = "READY"
        return IndexDetailDataStatusDto(
            status=status,  # type: ignore[arg-type]
            expectedTradeDate=expected_trade_date,
            observedTradeDate=observed_trade_date,
        )
