from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    DuplicateSectorFactError,
    MissingReason,
    SectorDailyFact,
    SectorMomentumDirection,
    SectorMomentumPeriod,
    SectorRankFact,
    SectorReturnFact,
)


RETURN_QUANTUM = Decimal("0.0001")
PERCENTILE_QUANTUM = Decimal("0.1")


class SectorMomentumCalculator:
    """Deterministic price-only cross-sectional momentum calculations."""

    @staticmethod
    def index_facts(facts: Iterable[SectorDailyFact]) -> dict[tuple[str, date], SectorDailyFact]:
        indexed: dict[tuple[str, date], SectorDailyFact] = {}
        for fact in facts:
            key = (fact.sector_code, fact.trade_date)
            if key in indexed:
                raise DuplicateSectorFactError(
                    f"duplicate sector daily fact: {fact.sector_code}@{fact.trade_date.isoformat()}"
                )
            indexed[key] = fact
        return indexed

    def calculate_for_date(
        self,
        *,
        sector_codes: Iterable[str],
        open_dates: tuple[date, ...],
        target_date: date,
        period: SectorMomentumPeriod,
        fact_index: dict[tuple[str, date], SectorDailyFact],
    ) -> tuple[SectorReturnFact, ...]:
        try:
            target_index = open_dates.index(target_date)
        except ValueError as exc:
            raise ValueError("target date is absent from the supplied open-date window") from exc
        return tuple(
            self._calculate_one(
                sector_code=sector_code,
                open_dates=open_dates,
                target_index=target_index,
                period=period,
                fact_index=fact_index,
            )
            for sector_code in sector_codes
        )

    def calculate_for_dates(
        self,
        *,
        sector_codes: Iterable[str],
        open_dates: tuple[date, ...],
        target_dates: tuple[date, ...],
        period: SectorMomentumPeriod,
        fact_index: dict[tuple[str, date], SectorDailyFact],
    ) -> dict[date, tuple[SectorReturnFact, ...]]:
        """Calculate a historical grid without re-reading each rolling window."""
        date_indexes = {item: index for index, item in enumerate(open_dates)}
        if any(item not in date_indexes for item in target_dates):
            raise ValueError("target date is absent from the supplied open-date window")
        results: dict[date, list[SectorReturnFact]] = {item: [] for item in target_dates}
        for sector_code in sector_codes:
            facts = tuple(fact_index.get((sector_code, item)) for item in open_dates)
            if period == 1:
                for target_date in target_dates:
                    fact = facts[date_indexes[target_date]]
                    if fact is None:
                        result = SectorReturnFact(
                            sector_code,
                            target_date,
                            None,
                            "DATE_MISSING",
                        )
                    elif fact.pct_change is None or not fact.pct_change.is_finite():
                        result = SectorReturnFact(
                            sector_code,
                            target_date,
                            None,
                            "PCT_CHANGE_MISSING",
                        )
                    else:
                        result = SectorReturnFact(
                            sector_code,
                            target_date,
                            fact.pct_change.quantize(
                                RETURN_QUANTUM,
                                rounding=ROUND_HALF_UP,
                            ),
                            "NONE",
                        )
                    results[target_date].append(result)
                continue

            invalid_reasons = tuple(self._close_reason(fact) for fact in facts)
            invalid_prefix = [0]
            for reason in invalid_reasons:
                invalid_prefix.append(invalid_prefix[-1] + int(reason != "NONE"))
            for target_date in target_dates:
                target_index = date_indexes[target_date]
                if target_index < period:
                    result = SectorReturnFact(
                        sector_code,
                        target_date,
                        None,
                        "HISTORY_INSUFFICIENT",
                    )
                else:
                    start_index = target_index - period
                    invalid_count = (
                        invalid_prefix[target_index + 1] - invalid_prefix[start_index]
                    )
                    if invalid_count:
                        reason = next(
                            item
                            for item in invalid_reasons[start_index : target_index + 1]
                            if item != "NONE"
                        )
                        result = SectorReturnFact(
                            sector_code,
                            target_date,
                            None,
                            reason,
                        )
                    else:
                        start_fact = facts[start_index]
                        end_fact = facts[target_index]
                        assert start_fact is not None and start_fact.close is not None
                        assert end_fact is not None and end_fact.close is not None
                        return_pct = (
                            (end_fact.close / start_fact.close) - Decimal(1)
                        ) * Decimal(100)
                        result = SectorReturnFact(
                            sector_code,
                            target_date,
                            return_pct.quantize(
                                RETURN_QUANTUM,
                                rounding=ROUND_HALF_UP,
                            ),
                            "NONE",
                        )
                results[target_date].append(result)
        return {item: tuple(rows) for item, rows in results.items()}

    @staticmethod
    def rank_strength(return_facts: Iterable[SectorReturnFact]) -> tuple[SectorRankFact, ...]:
        rows = tuple(return_facts)
        valid_values = tuple(row.return_pct for row in rows if row.return_pct is not None)
        frequencies: dict[Decimal, int] = {}
        for value in valid_values:
            frequencies[value] = frequencies.get(value, 0) + 1
        ranks_by_value: dict[Decimal, tuple[int, Decimal]] = {}
        greater = 0
        for value in sorted(frequencies, reverse=True):
            equal = frequencies[value]
            if len(valid_values) == 1:
                percentile = Decimal("100.0")
            else:
                average_rank = Decimal(greater) + (Decimal(equal) + Decimal(1)) / Decimal(2)
                percentile = (
                    (Decimal(len(valid_values)) - average_rank)
                    / Decimal(len(valid_values) - 1)
                    * Decimal(100)
                ).quantize(PERCENTILE_QUANTUM, rounding=ROUND_HALF_UP)
            ranks_by_value[value] = (greater + 1, percentile)
            greater += equal

        result: list[SectorRankFact] = []
        for row in rows:
            if row.return_pct is None:
                result.append(
                    SectorRankFact(
                        sector_code=row.sector_code,
                        return_pct=None,
                        strength_rank=None,
                        percentile=None,
                    )
                )
                continue
            strength_rank, percentile = ranks_by_value[row.return_pct]
            result.append(
                SectorRankFact(
                    sector_code=row.sector_code,
                    return_pct=row.return_pct.quantize(RETURN_QUANTUM, rounding=ROUND_HALF_UP),
                    strength_rank=strength_rank,
                    percentile=percentile,
                )
            )
        return tuple(result)

    @staticmethod
    def sort_ranking_rows(
        rows: Iterable[SectorRankFact],
        *,
        direction: SectorMomentumDirection,
    ) -> tuple[SectorRankFact, ...]:
        def sort_key(row: SectorRankFact):
            if row.return_pct is None:
                return (1, Decimal(0), row.sector_code)
            value = -row.return_pct if direction == "GAINERS" else row.return_pct
            return (0, value, row.sector_code)

        return tuple(sorted(rows, key=sort_key))

    @staticmethod
    def as_json_return(value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value.quantize(RETURN_QUANTUM, rounding=ROUND_HALF_UP))

    @staticmethod
    def as_json_percentile(value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value.quantize(PERCENTILE_QUANTUM, rounding=ROUND_HALF_UP))

    @staticmethod
    def _calculate_one(
        *,
        sector_code: str,
        open_dates: tuple[date, ...],
        target_index: int,
        period: SectorMomentumPeriod,
        fact_index: dict[tuple[str, date], SectorDailyFact],
    ) -> SectorReturnFact:
        target_date = open_dates[target_index]
        if period == 1:
            fact = fact_index.get((sector_code, target_date))
            if fact is None:
                return SectorReturnFact(sector_code, target_date, None, "DATE_MISSING")
            if fact.pct_change is None or not fact.pct_change.is_finite():
                return SectorReturnFact(sector_code, target_date, None, "PCT_CHANGE_MISSING")
            return SectorReturnFact(
                sector_code,
                target_date,
                fact.pct_change.quantize(RETURN_QUANTUM, rounding=ROUND_HALF_UP),
                "NONE",
            )

        if target_index < period:
            return SectorReturnFact(sector_code, target_date, None, "HISTORY_INSUFFICIENT")
        required_dates = open_dates[target_index - period : target_index + 1]
        required_facts: list[SectorDailyFact] = []
        for required_date in required_dates:
            fact = fact_index.get((sector_code, required_date))
            if fact is None:
                return SectorReturnFact(sector_code, target_date, None, "DATE_MISSING")
            required_facts.append(fact)
        closes = [fact.close for fact in required_facts]
        if any(value is None or not value.is_finite() for value in closes):
            return SectorReturnFact(sector_code, target_date, None, "CLOSE_MISSING")
        if any(value <= 0 for value in closes if value is not None):
            return SectorReturnFact(sector_code, target_date, None, "CLOSE_NON_POSITIVE")
        start_close = closes[0]
        end_close = closes[-1]
        assert start_close is not None and end_close is not None
        return_pct = ((end_close / start_close) - Decimal(1)) * Decimal(100)
        return SectorReturnFact(
            sector_code,
            target_date,
            return_pct.quantize(RETURN_QUANTUM, rounding=ROUND_HALF_UP),
            "NONE",
        )

    @staticmethod
    def _close_reason(fact: SectorDailyFact | None) -> MissingReason:
        if fact is None:
            return "DATE_MISSING"
        if fact.close is None or not fact.close.is_finite():
            return "CLOSE_MISSING"
        if fact.close <= 0:
            return "CLOSE_NON_POSITIVE"
        return "NONE"
