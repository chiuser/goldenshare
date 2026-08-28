from __future__ import annotations

from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import (
    MINIMUM_GROUP_SIZE,
    SectorDualMomentumClassification,
    SectorDualMomentumLeadingThreshold,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorRankFact,
    SectorReturnFact,
)


class SectorDualMomentumClassifier:
    """Classify existing return and percentile facts without recalculating them."""

    @staticmethod
    def classify(
        *,
        return_fact: SectorReturnFact,
        rank_fact: SectorRankFact,
        calculable_count: int,
        leading_threshold: SectorDualMomentumLeadingThreshold,
    ) -> SectorDualMomentumClassification:
        if return_fact.sector_code != rank_fact.sector_code:
            raise ValueError("return and rank facts must reference the same sector")
        values = (
            rank_fact.return_pct,
            rank_fact.strength_rank,
            rank_fact.percentile,
        )
        if any(value is None for value in values) and not all(
            value is None for value in values
        ):
            raise ValueError("rank fact values must be null together")
        if rank_fact.return_pct != return_fact.return_pct:
            raise ValueError("return and rank facts must carry the same return")

        if return_fact.return_pct is None:
            if return_fact.missing_reason == "NONE":
                raise ValueError("missing return requires a missing reason")
            return SectorDualMomentumClassification(
                sector_code=return_fact.sector_code,
                return_pct=None,
                strength_rank=None,
                percentile=None,
                absolute_status="UNAVAILABLE",
                relative_status="UNAVAILABLE",
                qualification_status="NOT_EVALUATED",
                coordinate_status="UNAVAILABLE",
                display_status="DATA_INSUFFICIENT",
                missing_reason=return_fact.missing_reason,
            )

        if return_fact.missing_reason != "NONE":
            raise ValueError("calculable return cannot carry a missing reason")
        assert rank_fact.strength_rank is not None
        assert rank_fact.percentile is not None
        absolute_status = (
            "POSITIVE" if return_fact.return_pct > 0 else "NOT_POSITIVE"
        )
        if calculable_count < MINIMUM_GROUP_SIZE:
            return SectorDualMomentumClassification(
                sector_code=return_fact.sector_code,
                return_pct=return_fact.return_pct,
                strength_rank=rank_fact.strength_rank,
                percentile=rank_fact.percentile,
                absolute_status=absolute_status,
                relative_status="SAMPLE_INSUFFICIENT",
                qualification_status="NOT_EVALUATED",
                coordinate_status="PLOTTABLE",
                display_status="SAMPLE_INSUFFICIENT",
                missing_reason=None,
            )

        relative_status = (
            "LEADING"
            if rank_fact.percentile >= leading_threshold
            else "NOT_LEADING"
        )
        qualified = absolute_status == "POSITIVE" and relative_status == "LEADING"
        display_status = {
            ("POSITIVE", "LEADING"): "QUALIFIED",
            ("POSITIVE", "NOT_LEADING"): "UP_NOT_LEADING",
            ("NOT_POSITIVE", "LEADING"): "NOT_UP_LEADING",
            ("NOT_POSITIVE", "NOT_LEADING"): "NOT_UP_NOT_LEADING",
        }[(absolute_status, relative_status)]
        return SectorDualMomentumClassification(
            sector_code=return_fact.sector_code,
            return_pct=return_fact.return_pct,
            strength_rank=rank_fact.strength_rank,
            percentile=rank_fact.percentile,
            absolute_status=absolute_status,
            relative_status=relative_status,
            qualification_status="QUALIFIED" if qualified else "NOT_QUALIFIED",
            coordinate_status="PLOTTABLE",
            display_status=display_status,
            missing_reason=None,
        )
