from __future__ import annotations

import math

import pytest

from src.biz.services.wealth.market.detail_volume_display import format_daily_volume_display


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (586_339, "58.63万"),
        (5_863, "0.59万"),
        (0, "0.00万"),
        (12_345, "1.23万"),
        (12_350, "1.24万"),
    ],
)
def test_format_daily_volume_display_uses_fixed_ten_thousand_unit_and_half_up_rounding(
    value: object,
    expected: str,
) -> None:
    assert format_daily_volume_display(value) == expected


@pytest.mark.parametrize(
    "value",
    [None, float("nan"), float("inf"), -float("inf"), math.nan, "not-a-number"],
)
def test_format_daily_volume_display_rejects_missing_or_non_finite_values(value: object | None) -> None:
    assert format_daily_volume_display(value) is None
