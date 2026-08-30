from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.biz.schemas.wealth.market.sector_price_volume import (
    SectorPriceVolumeSnapshotRowDto,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorScopeInvalidError,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import (
    ALLOWED_HISTORY_RANGES,
    ALLOWED_PERIODS,
    ALLOWED_STATES,
    FORMULA_KEY,
    FORMULA_VERSION,
    SectorPriceVolumeDailyFact,
    SectorPriceVolumeMetricFact,
    SectorPriceVolumeMissingReason,
    SectorPriceVolumeRankedFact,
    parse_price_volume_history_range,
    parse_price_volume_period,
)


def test_frozen_formula_enums_and_parsers_accept_only_approved_values() -> None:
    assert FORMULA_KEY == "sector-price-volume-distribution"
    assert FORMULA_VERSION == 1
    assert ALLOWED_PERIODS == (1, 5, 10, 20, 30)
    assert ALLOWED_HISTORY_RANGES == (20, 30, 60)
    assert ALLOWED_STATES == ("JOINT", "PRICE_ONLY", "AMOUNT_ONLY", "NEUTRAL")
    assert tuple(parse_price_volume_period(item) for item in ALLOWED_PERIODS) == ALLOWED_PERIODS
    assert tuple(
        parse_price_volume_history_range(item) for item in ALLOWED_HISTORY_RANGES
    ) == ALLOWED_HISTORY_RANGES
    for value in (0, 2, 15, 60):
        with pytest.raises(SectorScopeInvalidError):
            parse_price_volume_period(value)
    for value in (0, 5, 21, 120):
        with pytest.raises(SectorScopeInvalidError):
            parse_price_volume_history_range(value)


def test_daily_fact_rejects_float_and_metric_requires_value_reason_exclusivity() -> None:
    with pytest.raises(TypeError):
        SectorPriceVolumeDailyFact(
            sector_code="BK1001.DC",
            trade_date=date(2026, 8, 28),
            close=1.0,  # type: ignore[arg-type]
            pct_change=Decimal("1"),
            amount=Decimal("100"),
        )
    with pytest.raises(ValueError):
        SectorPriceVolumeMetricFact(
            sector_code="BK1001.DC",
            trade_date=date(2026, 8, 28),
            price_momentum_pct=Decimal("1"),
            amount_activity_pct=Decimal("2"),
            price_missing_reason=SectorPriceVolumeMissingReason.DATE_MISSING,
            amount_missing_reason=None,
        )


def test_ranked_fact_and_dto_reject_inconsistent_rank_state_and_non_finite_value() -> None:
    metric = SectorPriceVolumeMetricFact(
        sector_code="BK1001.DC",
        trade_date=date(2026, 8, 28),
        price_momentum_pct=Decimal("1"),
        amount_activity_pct=Decimal("0"),
        price_missing_reason=None,
        amount_missing_reason=None,
    )
    with pytest.raises(ValueError):
        SectorPriceVolumeRankedFact(
            metric=metric,
            price_rank=None,
            price_rankable_count=1,
            amount_rank=1,
            amount_rankable_count=1,
            state="PRICE_ONLY",
        )
    with pytest.raises(ValidationError):
        SectorPriceVolumeSnapshotRowDto(
            sectorCode="BK1001.DC",
            sectorName="行业甲",
            industryLevel=1,
            hierarchyPath="行业甲",
            rootSectorCode="BK1001.DC",
            rootSectorName="行业甲",
            priceMomentumPct=float("nan"),
            amountActivityPct=0.0,
            priceRank=1,
            priceRankableCount=1,
            amountRank=1,
            amountRankableCount=1,
            state="PRICE_ONLY",
        )
