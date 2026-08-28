from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.biz.services.wealth.market.sector_analysis.sector_member_detail_contract import (
    DuplicateSectorMemberFactError,
    SectorMemberDailyFact,
    SectorMemberSourceFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_return_calculator import (
    SectorMemberReturnCalculator,
)


TARGET_DATE = date(2026, 8, 27)
OPEN_DATES = tuple(TARGET_DATE - timedelta(days=offset) for offset in range(4, -1, -1))


def _daily(
    code: str,
    trade_date: date,
    *,
    close: str | None = "10",
    pct_change: str | None = "1",
) -> SectorMemberDailyFact:
    return SectorMemberDailyFact(
        stock_code=code,
        trade_date=trade_date,
        close=None if close is None else Decimal(close),
        pct_change=None if pct_change is None else Decimal(pct_change),
    )


def test_one_day_uses_pct_change_and_keeps_close_independent() -> None:
    calculator = SectorMemberReturnCalculator()
    rows = calculator.calculate(
        members=(SectorMemberSourceFact("000001.SZ", "甲"),),
        daily_facts=(
            _daily("000001.SZ", TARGET_DATE, close=None, pct_change="2.34567"),
        ),
        open_dates=(TARGET_DATE,),
        target_date=TARGET_DATE,
        period=1,
    )

    assert rows[0].close is None
    assert rows[0].return_pct == Decimal("2.3457")
    assert rows[0].return_missing_reason == "NONE"


def test_multi_day_compounds_each_daily_pct_change() -> None:
    calculator = SectorMemberReturnCalculator()
    rows = calculator.calculate(
        members=(SectorMemberSourceFact("000001.SZ", "甲"),),
        daily_facts=tuple(
            _daily("000001.SZ", item, pct_change=value)
            for item, value in zip(OPEN_DATES, ("1", "2", "-1", "3", "4"), strict=True)
        ),
        open_dates=OPEN_DATES,
        target_date=TARGET_DATE,
        period=5,
    )

    expected = (
        Decimal("1.01")
        * Decimal("1.02")
        * Decimal("0.99")
        * Decimal("1.03")
        * Decimal("1.04")
        - Decimal(1)
    ) * Decimal(100)
    assert rows[0].return_pct == expected.quantize(Decimal("0.0001"))


@pytest.mark.parametrize(
    ("open_dates", "daily_facts", "reason"),
    [
        (OPEN_DATES[:4], (), "HISTORY_INSUFFICIENT"),
        (
            OPEN_DATES,
            tuple(_daily("000001.SZ", item) for item in OPEN_DATES[:-1]),
            "DATE_MISSING",
        ),
        (
            OPEN_DATES,
            tuple(
                _daily("000001.SZ", item, pct_change=None if index == 2 else "1")
                for index, item in enumerate(OPEN_DATES)
            ),
            "PCT_CHANGE_MISSING",
        ),
    ],
)
def test_missing_windows_never_fill_or_forward_fill(
    open_dates, daily_facts, reason
) -> None:
    target = open_dates[-1]
    row = SectorMemberReturnCalculator().calculate(
        members=(SectorMemberSourceFact("000001.SZ", "甲"),),
        daily_facts=daily_facts,
        open_dates=open_dates,
        target_date=target,
        period=5,
    )[0]

    assert row.return_pct is None
    assert row.return_missing_reason == reason


def test_sort_keeps_null_last_and_uses_code_for_ties() -> None:
    calculator = SectorMemberReturnCalculator()
    members = (
        SectorMemberSourceFact("000003.SZ", "丙"),
        SectorMemberSourceFact("000002.SZ", "乙"),
        SectorMemberSourceFact("000001.SZ", "甲"),
    )
    daily = (
        _daily("000003.SZ", TARGET_DATE, pct_change=None),
        _daily("000002.SZ", TARGET_DATE, pct_change="2"),
        _daily("000001.SZ", TARGET_DATE, pct_change="2"),
    )
    calculated = calculator.calculate(
        members=members,
        daily_facts=daily,
        open_dates=(TARGET_DATE,),
        target_date=TARGET_DATE,
        period=1,
    )

    assert [
        row.stock_code for row in calculator.sort(calculated, direction="GAINERS")
    ] == [
        "000001.SZ",
        "000002.SZ",
        "000003.SZ",
    ]
    assert [
        row.stock_code for row in calculator.sort(calculated, direction="LOSERS")
    ] == [
        "000001.SZ",
        "000002.SZ",
        "000003.SZ",
    ]


@pytest.mark.parametrize("duplicate_kind", ["member", "daily"])
def test_duplicate_business_keys_are_rejected(duplicate_kind: str) -> None:
    calculator = SectorMemberReturnCalculator()
    members = (SectorMemberSourceFact("000001.SZ", "甲"),)
    daily = (_daily("000001.SZ", TARGET_DATE),)
    if duplicate_kind == "member":
        members = members * 2
    else:
        daily = daily * 2

    with pytest.raises(DuplicateSectorMemberFactError):
        calculator.calculate(
            members=members,
            daily_facts=daily,
            open_dates=(TARGET_DATE,),
            target_date=TARGET_DATE,
            period=1,
        )
