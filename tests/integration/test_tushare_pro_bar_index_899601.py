from __future__ import annotations

import os
from typing import Any

from pandas.core.generic import NDFrame
import pytest
import tushare as ts

from src.foundation.config.settings import get_settings


_RUN_FLAG = "RUN_TUSHARE_PROBAR_INDEX_899601"
_TS_CODE = "899601.BJ"
_ASSET = "I"
_DEFAULT_START_DATE = "20260401"
_DEFAULT_END_DATE = "20260430"


def _fetch_pro_bar_rows(*, freq: str) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.tushare_token:
        pytest.skip("TUSHARE_TOKEN is not configured")

    pro_api = ts.pro_api(settings.tushare_token)
    original_fillna = NDFrame.fillna

    def _compat_fillna(self: NDFrame, *args: Any, **kwargs: Any):
        method = kwargs.get("method")
        if method == "bfill" and not args:
            return self.bfill()
        return original_fillna(self, *args, **kwargs)

    NDFrame.fillna = _compat_fillna
    try:
        df = ts.pro_bar(
            ts_code=_TS_CODE,
            api=pro_api,
            asset=_ASSET,
            freq=freq,
            start_date=os.getenv("PROBAR_INDEX_899601_START_DATE", _DEFAULT_START_DATE),
            end_date=os.getenv("PROBAR_INDEX_899601_END_DATE", _DEFAULT_END_DATE),
        )
    finally:
        NDFrame.fillna = original_fillna

    if df is None:
        return []
    return df.to_dict(orient="records")


@pytest.mark.skipif(
    os.getenv(_RUN_FLAG) != "1",
    reason=f"set {_RUN_FLAG}=1 to run live Tushare pro_bar index test",
)
@pytest.mark.parametrize(
    ("freq", "label"),
    [
        ("D", "日线"),
        ("W", "周线"),
        ("M", "月线"),
    ],
)
def test_tushare_pro_bar_returns_rows_for_index_899601_bj(freq: str, label: str) -> None:
    rows = _fetch_pro_bar_rows(freq=freq)

    assert rows, (
        f"Tushare pro_bar did not return {label} rows for "
        f"ts_code={_TS_CODE}, asset={_ASSET}, freq={freq}"
    )
    assert all(str(row.get("ts_code") or "").upper() == _TS_CODE for row in rows)
    assert all("trade_date" in row for row in rows)
