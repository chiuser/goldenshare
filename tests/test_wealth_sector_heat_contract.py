from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.biz.services.wealth.config import SectorOverviewHeatStrategyPayload, StrategyConfigService
from src.biz.services.wealth.market.sector_overview import (
    PriorPublishedHeat,
    SectorHeatConfigResolver,
    SectorHeatContract,
    SectorHeatRawFeatureRow,
    SectorPoolCounts,
)


def _resolved_config():  # type: ignore[no-untyped-def]
    return SectorHeatConfigResolver(StrategyConfigService()).resolve()


def _pool(*, member_count: int = 12) -> SectorPoolCounts:
    return SectorPoolCounts(
        source_member_count=member_count,
        member_count=member_count,
        suspended_count=1,
        quote_eligible_count=member_count - 1,
        valid_quote_count=member_count - 2,
        missing_quote_count=1,
        quote_coverage=(member_count - 2) / (member_count - 1),
    )


def _row(trade_date: date, code: str, value: float, *, invalid_reason: str | None = None) -> SectorHeatRawFeatureRow:
    return SectorHeatRawFeatureRow(
        trade_date=trade_date,
        sector_code=code,
        sector_name=f"概念{code}",
        pool=_pool(member_count=8 if invalid_reason == "MEMBER_COUNT_LOW" else 12),
        invalid_reason=invalid_reason,
        daily_return=value,
        relative_strength_5=value,
        daily_acceleration=value,
        up_ratio=value,
        limit_up_ratio=value,
        net_inflow_strength=value,
        positive_inflow_day_ratio_5=value,
        net_inflow_rate_slope_5=value,
        activity=value,
    )


def test_sector_heat_strategy_config_is_registered_and_hashed_deterministically() -> None:
    first = _resolved_config()
    second = _resolved_config()

    assert first.version == "1.0.0"
    assert first.payload.score_version == "concept-heat-eod-v1"
    assert len(first.config_hash) == 64
    assert first.config_hash == second.config_hash


def test_sector_heat_strategy_config_rejects_weight_drift() -> None:
    payload = _resolved_config().payload.model_dump(mode="python", by_alias=True)
    payload["weights"]["activity"] = Decimal("0.11")

    with pytest.raises(ValidationError, match="weights must sum to 1"):
        SectorOverviewHeatStrategyPayload.model_validate(payload)


def test_winsor_percentile_uses_average_rank_for_ties() -> None:
    percentiles = SectorHeatContract.empirical_percentiles(
        {"A": 1.0, "B": 2.0, "C": 2.0, "D": 100.0},
        lower=0.01,
        upper=0.99,
    )

    assert percentiles["A"] == 0.0
    assert percentiles["B"] == pytest.approx(0.5)
    assert percentiles["C"] == pytest.approx(0.5)
    assert percentiles["D"] == 1.0


def test_linear_slope_is_directional_and_stable() -> None:
    assert SectorHeatContract.linear_slope([1, 2, 3, 4, 5]) == pytest.approx(1.0)
    assert SectorHeatContract.linear_slope([5, 4, 3, 2, 1]) == pytest.approx(-1.0)
    assert SectorHeatContract.linear_slope([3, 3, 3, 3, 3]) == pytest.approx(0.0)


def test_final_rank_uses_unrounded_score_then_sector_code_tie_break() -> None:
    ranks = SectorHeatContract._stable_descending_ranks(
        {"B.DC": 80.004, "A.DC": 80.003, "C.DC": 80.003}
    )

    assert ranks == {"B.DC": 1, "A.DC": 2, "C.DC": 3}


def test_fixed_cross_section_golden_scores_ranks_quality_and_trend() -> None:
    resolved = _resolved_config()
    contract = SectorHeatContract(resolved.payload)
    start = date(2026, 8, 5)
    trade_dates = [start + timedelta(days=offset) for offset in range(6)]
    rows_by_date = {
        trade_date: [_row(trade_date, "A", 1.0), _row(trade_date, "B", 2.0), _row(trade_date, "C", 3.0)]
        for trade_date in trade_dates
    }
    rows_by_date[trade_dates[-1]].extend(
        [
            _row(trade_dates[-1], "D", 4.0, invalid_reason="MEMBER_COUNT_LOW"),
            _row(trade_dates[-1], "E", 5.0),
        ]
    )
    previous_date = trade_dates[-2]
    prior_published = {
        previous_date: {
            "A": PriorPublishedHeat(
                trade_date=previous_date,
                heat_status="VALID",
                heat_score=Decimal("4"),
                raw_heat_trend="STABLE",
                score_version=resolved.payload.score_version,
                config_hash=resolved.config_hash,
            ),
            "B": PriorPublishedHeat(
                trade_date=previous_date,
                heat_status="VALID",
                heat_score=Decimal("40"),
                raw_heat_trend="HEATING",
                score_version=resolved.payload.score_version,
                config_hash=resolved.config_hash,
            ),
            "C": PriorPublishedHeat(
                trade_date=previous_date,
                heat_status="VALID",
                heat_score=Decimal("90"),
                raw_heat_trend="STABLE",
                score_version=resolved.payload.score_version,
                config_hash=resolved.config_hash,
            ),
        }
    }

    rows = contract.calculate(
        ordered_trade_dates=trade_dates,
        rows_by_date=rows_by_date,
        prior_published_by_date=prior_published,
        config_hash=resolved.config_hash,
    )
    by_code = {row.sector_code: row for row in rows}

    assert by_code["A"].heat_score == Decimal("5.0000")
    assert by_code["B"].heat_score == Decimal("50.0000")
    assert by_code["C"].heat_score == Decimal("95.0000")
    assert by_code["A"].heat_score is not None and by_code["A"].heat_score.as_tuple().exponent == -2
    assert [by_code[code].heat_rank for code in ("C", "B", "A")] == [1, 2, 3]
    assert by_code["C"].heat_level == "BOILING"
    assert by_code["B"].raw_heat_trend == "HEATING"
    assert by_code["B"].heat_trend == "HEATING"
    assert by_code["D"].heat_status == "INVALID"
    assert by_code["D"].invalid_reason == "MEMBER_COUNT_LOW"
    assert by_code["D"].heat_score is None
    assert by_code["E"].invalid_reason == "HISTORY_INSUFFICIENT"


def test_missing_comparable_previous_heat_returns_unknown_without_filling() -> None:
    resolved = _resolved_config()
    contract = SectorHeatContract(resolved.payload)
    start = date(2026, 8, 5)
    trade_dates = [start + timedelta(days=offset) for offset in range(6)]
    rows_by_date = {trade_date: [_row(trade_date, "A", 1.0)] for trade_date in trade_dates}

    [row] = contract.calculate(
        ordered_trade_dates=trade_dates,
        rows_by_date=rows_by_date,
        prior_published_by_date={},
        config_hash=resolved.config_hash,
    )

    assert row.heat_delta_1d is None
    assert row.raw_heat_trend == "UNKNOWN"
    assert row.heat_trend == "UNKNOWN"


def test_future_rows_do_not_change_target_day_scores() -> None:
    resolved = _resolved_config()
    contract = SectorHeatContract(resolved.payload)
    start = date(2026, 8, 5)
    trade_dates = [start + timedelta(days=offset) for offset in range(6)]
    rows_by_date = {
        trade_date: [_row(trade_date, "A", 1.0), _row(trade_date, "B", 2.0)]
        for trade_date in trade_dates
    }
    baseline = contract.calculate(
        ordered_trade_dates=trade_dates,
        rows_by_date=rows_by_date,
        prior_published_by_date={},
        config_hash=resolved.config_hash,
    )
    future_date = trade_dates[-1] + timedelta(days=1)
    with_future = contract.calculate(
        ordered_trade_dates=trade_dates,
        rows_by_date={**rows_by_date, future_date: [_row(future_date, "A", 1000.0)]},
        prior_published_by_date={},
        config_hash=resolved.config_hash,
    )

    assert with_future == baseline
