from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
from pandas.core.generic import NDFrame
import pytest
import tushare as ts

from src.biz.queries.quote_query_service import QuoteQueryService
from src.db import SessionLocal
from src.foundation.config.settings import get_settings


_RUN_FLAG = "RUN_TUSHARE_PROBAR_COMPARE"


def _parse_yyyymmdd(value: str) -> date:
    normalized = value.strip()
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid yyyymmdd: {value}")
    return date.fromisoformat(f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:8]}")


def _to_decimal_4(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _assert_close_decimal(left: Decimal, right: Decimal, *, tolerance: Decimal = Decimal("0.0200")) -> None:
    assert abs(left - right) <= tolerance, f"left={left} right={right} tolerance={tolerance}"


@pytest.mark.skipif(
    os.getenv(_RUN_FLAG) != "1",
    reason=f"set {_RUN_FLAG}=1 to run live Tushare pro_bar parity test",
)
def test_quote_daily_forward_matches_tushare_pro_bar_qfq() -> None:
    ts_code = os.getenv("PROBAR_COMPARE_TS_CODE", "000001.SZ").strip().upper()
    trade_date_raw = os.getenv("PROBAR_COMPARE_TRADE_DATE", "20191230")
    trade_date = _parse_yyyymmdd(trade_date_raw)

    # Use in-memory pro client and pass it into pro_bar to avoid ts.set_token() writing ~/tk.csv.
    pro_api = ts.pro_api(get_settings().tushare_token)
    original_fillna = NDFrame.fillna

    def _compat_fillna(self: NDFrame, *args: Any, **kwargs: Any):
        method = kwargs.get("method")
        if method == "bfill" and not args:
            return self.bfill()
        return original_fillna(self, *args, **kwargs)

    NDFrame.fillna = _compat_fillna
    try:
        sdk_df = ts.pro_bar(
            ts_code=ts_code,
            api=pro_api,
            asset="E",
            start_date=trade_date_raw,
            end_date="",
            adj="qfq",
            freq="D",
        )
    finally:
        NDFrame.fillna = original_fillna
    sdk_rows = [] if sdk_df is None else sdk_df.to_dict(orient="records")
    if not sdk_rows:
        pytest.skip(f"tushare pro_bar returned no rows for {ts_code} {trade_date_raw}")
    sdk_row = next((row for row in sdk_rows if _parse_yyyymmdd(str(row["trade_date"])) == trade_date), None)
    if sdk_row is None:
        pytest.skip(f"tushare pro_bar returned no target row for {ts_code} {trade_date_raw}")

    with SessionLocal() as session:
        query_service = QuoteQueryService()
        instrument = query_service.resolve_instrument(
            session,
            ts_code=ts_code,
            symbol=None,
            market=None,
            security_type="stock",
        )
        response = query_service.build_kline(
            session,
            instrument=instrument,
            period="day",
            adjustment="forward",
            start_date=trade_date,
            end_date=trade_date,
            limit=10,
        )

    assert response.meta.bar_count == 1, f"expected one bar for {ts_code} {trade_date.isoformat()}"
    bar = response.bars[0]
    assert bar.trade_date == trade_date

    # pro_bar returns qfq prices; compare with our forward-adjusted daily kline.
    assert bar.open is not None
    assert bar.high is not None
    assert bar.low is not None
    assert bar.close is not None

    _assert_close_decimal(bar.open, _to_decimal_4(sdk_row["open"]))
    _assert_close_decimal(bar.high, _to_decimal_4(sdk_row["high"]))
    _assert_close_decimal(bar.low, _to_decimal_4(sdk_row["low"]))
    _assert_close_decimal(bar.close, _to_decimal_4(sdk_row["close"]))
