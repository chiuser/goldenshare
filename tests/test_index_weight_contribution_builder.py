from __future__ import annotations

from decimal import Decimal

from src.biz.services.wealth.market.index_detail.index_weight_contribution_builder import (
    calculate_contribution_point,
)


def test_contribution_uses_frozen_formula_and_round_half_up() -> None:
    assert calculate_contribution_point(
        index_pre_close=Decimal("3440.12"),
        weight=Decimal("5.43"),
        constituent_pct_chg=Decimal("1.26"),
    ) == 2.3537


def test_contribution_keeps_sign_and_does_not_normalize_weight() -> None:
    assert calculate_contribution_point(
        index_pre_close="1000",
        weight="30",
        constituent_pct_chg="-2",
    ) == -6.0


def test_contribution_preserves_missing_inputs() -> None:
    assert calculate_contribution_point(index_pre_close=None, weight=5, constituent_pct_chg=1) is None
    assert calculate_contribution_point(index_pre_close=100, weight=None, constituent_pct_chg=1) is None
    assert calculate_contribution_point(index_pre_close=100, weight=5, constituent_pct_chg=None) is None
