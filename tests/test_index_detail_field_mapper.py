from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from src.biz.schemas.wealth.market.index_detail import IndexDetailDataStatusDto
from src.biz.services.wealth.market.index_detail.index_detail_field_mapper import (
    build_kline_bar,
    calculate_amplitude,
    resolve_direction,
)


def _row() -> dict:
    return {
        "trade_date": date(2026, 8, 10),
        "open": 100.0,
        "high": 110.0,
        "low": 90.0,
        "close": 105.0,
        "pre_close": 100.0,
        "change": 5.0,
        "pct_change": 5.0,
        "vol": 1234.0,
        "amount": 5678.0,
        "ma_bfq_5": 101.0,
        "ma_bfq_10": 102.0,
        "ma_bfq_20": 103.0,
        "ma_bfq_30": 104.0,
        "ma_bfq_60": 105.0,
        "ma_bfq_90": 106.0,
        "ma_bfq_250": None,
        "boll_upper_bfq": 112.0,
        "boll_mid_bfq": 102.0,
        "boll_lower_bfq": 92.0,
        "macd_dif_bfq": 1.1,
        "macd_dea_bfq": 1.2,
        "macd_bfq": 1.3,
        "kdj_k_bfq": 44.0,
        "kdj_d_bfq": 55.0,
        "kdj_bfq": 66.0,
    }


def test_index_kline_mapper_uses_frozen_factor_field_names() -> None:
    bar = build_kline_bar(_row())

    assert bar.changePct == 5.0
    assert bar.amplitude == 20.0
    assert bar.factors.ma.ma250 is None
    assert bar.factors.boll.middle == 102.0
    assert bar.factors.macd.dif == 1.1
    assert bar.factors.kdj.k == 44.0
    assert bar.factors.kdj.d == 55.0
    assert bar.factors.kdj.j == 66.0
    assert "ma15" not in bar.factors.ma.model_dump()
    assert "ma120" not in bar.factors.ma.model_dump()


@pytest.mark.parametrize(
    ("high", "low", "pre_close", "expected"),
    [
        (110.0, 90.0, 100.0, 20.0),
        (None, 90.0, 100.0, None),
        (110.0, None, 100.0, None),
        (110.0, 90.0, None, None),
        (110.0, 90.0, 0.0, None),
    ],
)
def test_calculate_amplitude_preserves_missing_inputs(high, low, pre_close, expected) -> None:
    assert calculate_amplitude(high=high, low=low, pre_close=pre_close) == expected


@pytest.mark.parametrize(
    ("change_pct", "expected"),
    [(1.0, "UP"), (-1.0, "DOWN"), (0.0, "FLAT"), (None, "UNKNOWN")],
)
def test_resolve_direction(change_pct, expected) -> None:
    assert resolve_direction(change_pct) == expected


def test_index_detail_dto_forbids_unfrozen_extra_fields() -> None:
    with pytest.raises(ValidationError):
        IndexDetailDataStatusDto.model_validate(
            {
                "status": "READY",
                "expectedTradeDate": "2026-08-10",
                "observedTradeDate": "2026-08-10",
                "note": "not part of the frozen contract",
            }
        )
