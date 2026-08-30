from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from src.biz.services.wealth.market.sector_analysis.sector_momentum_calculator import (
    SectorMomentumCalculator,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    DuplicateSectorFactError,
    SectorDailyFact,
    SectorReturnFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import (
    SectorPriceVolumeDailyFact,
    SectorPriceVolumeHistoryRange,
    SectorPriceVolumeMetricFact,
    SectorPriceVolumeMissingReason,
    SectorPriceVolumePeriod,
    SectorPriceVolumeRankedFact,
    SectorPriceVolumeState,
)


PERCENT_QUANTUM = Decimal("0.0001")
_HUNDRED = Decimal(100)
_AMOUNT_REASON_PRIORITY = (
    SectorPriceVolumeMissingReason.DATE_MISSING,
    SectorPriceVolumeMissingReason.AMOUNT_MISSING,
    SectorPriceVolumeMissingReason.AMOUNT_NON_FINITE,
    SectorPriceVolumeMissingReason.AMOUNT_NEGATIVE,
)


class SectorPriceVolumeCalculator:
    """Pure Decimal price-volume calculations with bounded rolling windows."""

    def __init__(
        self,
        *,
        momentum_calculator: SectorMomentumCalculator | None = None,
    ) -> None:
        self._momentum = momentum_calculator or SectorMomentumCalculator()

    @staticmethod
    def index_facts(
        facts: Iterable[SectorPriceVolumeDailyFact],
    ) -> dict[tuple[str, date], SectorPriceVolumeDailyFact]:
        indexed: dict[tuple[str, date], SectorPriceVolumeDailyFact] = {}
        for fact in facts:
            key = (fact.sector_code, fact.trade_date)
            if key in indexed:
                raise DuplicateSectorFactError(
                    f"duplicate sector price-volume fact: {fact.sector_code}@{fact.trade_date.isoformat()}"
                )
            indexed[key] = fact
        return indexed

    def calculate_snapshot(
        self,
        *,
        sector_codes: Iterable[str],
        open_dates: tuple[date, ...],
        facts: Iterable[SectorPriceVolumeDailyFact],
        period: SectorPriceVolumePeriod,
    ) -> tuple[SectorPriceVolumeRankedFact, ...]:
        codes = tuple(sector_codes)
        if not open_dates:
            raise ValueError("open_dates cannot be empty")
        target_date = open_dates[-1]
        metric_grid = self._calculate_metric_grid(
            sector_codes=codes,
            open_dates=open_dates,
            target_dates=(target_date,),
            facts=facts,
            period=period,
        )
        metrics = metric_grid[target_date]
        price_ranks, price_count = self._competition_rank(
            {
                item.sector_code: item.price_momentum_pct
                for item in metrics
                if item.price_momentum_pct is not None
            }
        )
        amount_ranks, amount_count = self._competition_rank(
            {
                item.sector_code: item.amount_activity_pct
                for item in metrics
                if item.amount_activity_pct is not None
            }
        )
        ranked = tuple(
            SectorPriceVolumeRankedFact(
                metric=item,
                price_rank=price_ranks.get(item.sector_code),
                price_rankable_count=price_count,
                amount_rank=amount_ranks.get(item.sector_code),
                amount_rankable_count=amount_count,
                state=self._state(item),
            )
            for item in metrics
        )
        return tuple(
            sorted(
                ranked,
                key=lambda item: (
                    item.metric.price_momentum_pct is None,
                    -item.metric.price_momentum_pct
                    if item.metric.price_momentum_pct is not None
                    else Decimal(0),
                    item.metric.sector_code,
                ),
            )
        )

    def calculate_history(
        self,
        *,
        sector_code: str,
        open_dates: tuple[date, ...],
        facts: Iterable[SectorPriceVolumeDailyFact],
        period: SectorPriceVolumePeriod,
        history_range: SectorPriceVolumeHistoryRange,
    ) -> tuple[SectorPriceVolumeMetricFact, ...]:
        if not open_dates:
            return ()
        target_dates = open_dates[-history_range:]
        metric_grid = self._calculate_metric_grid(
            sector_codes=(sector_code,),
            open_dates=open_dates,
            target_dates=target_dates,
            facts=facts,
            period=period,
        )
        return tuple(metric_grid[item][0] for item in target_dates)

    def _calculate_metric_grid(
        self,
        *,
        sector_codes: tuple[str, ...],
        open_dates: tuple[date, ...],
        target_dates: tuple[date, ...],
        facts: Iterable[SectorPriceVolumeDailyFact],
        period: SectorPriceVolumePeriod,
    ) -> dict[date, tuple[SectorPriceVolumeMetricFact, ...]]:
        indexed = self.index_facts(facts)
        price_index = self._momentum.index_facts(
            SectorDailyFact(
                sector_code=fact.sector_code,
                trade_date=fact.trade_date,
                close=fact.close,
                pct_change=fact.pct_change,
            )
            for fact in indexed.values()
        )
        price_results = self._momentum.calculate_for_dates(
            sector_codes=sector_codes,
            open_dates=open_dates,
            target_dates=target_dates,
            period=period,
            fact_index=price_index,
        )
        date_indexes = {item: index for index, item in enumerate(open_dates)}
        by_date: dict[date, list[SectorPriceVolumeMetricFact]] = {
            item: [] for item in target_dates
        }
        for sector_code in sector_codes:
            amount_values, amount_reasons = self._amount_series(
                sector_code=sector_code,
                open_dates=open_dates,
                fact_index=indexed,
            )
            amount_prefix = [Decimal(0)]
            reason_prefixes = {
                reason: [0] for reason in _AMOUNT_REASON_PRIORITY
            }
            for value, reason in zip(amount_values, amount_reasons, strict=True):
                amount_prefix.append(amount_prefix[-1] + (value or Decimal(0)))
                for candidate in _AMOUNT_REASON_PRIORITY:
                    reason_prefixes[candidate].append(
                        reason_prefixes[candidate][-1] + int(reason == candidate)
                    )
            prices = {
                price_fact.trade_date: price_fact
                for rows in price_results.values()
                for price_fact in rows
                if price_fact.sector_code == sector_code
            }
            for target_date in target_dates:
                price = prices[target_date]
                amount_value, amount_reason = self._amount_for_target(
                    target_index=date_indexes[target_date],
                    period=period,
                    amount_prefix=amount_prefix,
                    reason_prefixes=reason_prefixes,
                )
                price_value, price_reason = self._map_price(price)
                by_date[target_date].append(
                    SectorPriceVolumeMetricFact(
                        sector_code=sector_code,
                        trade_date=target_date,
                        price_momentum_pct=price_value,
                        amount_activity_pct=amount_value,
                        price_missing_reason=price_reason,
                        amount_missing_reason=amount_reason,
                    )
                )
        return {item: tuple(rows) for item, rows in by_date.items()}

    @staticmethod
    def _amount_series(
        *,
        sector_code: str,
        open_dates: tuple[date, ...],
        fact_index: dict[tuple[str, date], SectorPriceVolumeDailyFact],
    ) -> tuple[
        tuple[Decimal | None, ...],
        tuple[SectorPriceVolumeMissingReason | None, ...],
    ]:
        values: list[Decimal | None] = []
        reasons: list[SectorPriceVolumeMissingReason | None] = []
        for trade_date in open_dates:
            fact = fact_index.get((sector_code, trade_date))
            if fact is None:
                values.append(None)
                reasons.append(SectorPriceVolumeMissingReason.DATE_MISSING)
            elif fact.amount is None:
                values.append(None)
                reasons.append(SectorPriceVolumeMissingReason.AMOUNT_MISSING)
            elif not fact.amount.is_finite():
                values.append(None)
                reasons.append(SectorPriceVolumeMissingReason.AMOUNT_NON_FINITE)
            elif fact.amount < 0:
                values.append(None)
                reasons.append(SectorPriceVolumeMissingReason.AMOUNT_NEGATIVE)
            else:
                values.append(fact.amount)
                reasons.append(None)
        return tuple(values), tuple(reasons)

    @staticmethod
    def _amount_for_target(
        *,
        target_index: int,
        period: SectorPriceVolumePeriod,
        amount_prefix: list[Decimal],
        reason_prefixes: dict[SectorPriceVolumeMissingReason, list[int]],
    ) -> tuple[Decimal | None, SectorPriceVolumeMissingReason | None]:
        if target_index < 2 * period - 1:
            return None, SectorPriceVolumeMissingReason.HISTORY_INSUFFICIENT
        prior_start = target_index - 2 * period + 1
        recent_start = target_index - period + 1
        end = target_index + 1
        for reason in _AMOUNT_REASON_PRIORITY:
            prefix = reason_prefixes[reason]
            if prefix[end] - prefix[prior_start] > 0:
                return None, reason
        prior_sum = amount_prefix[recent_start] - amount_prefix[prior_start]
        if prior_sum <= 0:
            return (
                None,
                SectorPriceVolumeMissingReason.PRIOR_AMOUNT_AVERAGE_NON_POSITIVE,
            )
        recent_sum = amount_prefix[end] - amount_prefix[recent_start]
        value = ((recent_sum / prior_sum) - Decimal(1)) * _HUNDRED
        return value.quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP), None

    @staticmethod
    def _map_price(
        fact: SectorReturnFact,
    ) -> tuple[Decimal | None, SectorPriceVolumeMissingReason | None]:
        if fact.return_pct is not None:
            return (
                fact.return_pct.quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP),
                None,
            )
        mapping = {
            "HISTORY_INSUFFICIENT": SectorPriceVolumeMissingReason.HISTORY_INSUFFICIENT,
            "DATE_MISSING": SectorPriceVolumeMissingReason.DATE_MISSING,
            "CLOSE_MISSING": SectorPriceVolumeMissingReason.CLOSE_MISSING,
            "CLOSE_NON_POSITIVE": SectorPriceVolumeMissingReason.CLOSE_NON_POSITIVE,
            "PCT_CHANGE_MISSING": SectorPriceVolumeMissingReason.PCT_CHANGE_MISSING,
        }
        return None, mapping[fact.missing_reason]

    @staticmethod
    def _competition_rank(
        values_by_code: dict[str, Decimal],
    ) -> tuple[dict[str, int], int]:
        rows = sorted(values_by_code.items(), key=lambda item: (-item[1], item[0]))
        ranks: dict[str, int] = {}
        previous: Decimal | None = None
        current_rank = 0
        for index, (sector_code, value) in enumerate(rows, start=1):
            if previous is None or value != previous:
                current_rank = index
                previous = value
            ranks[sector_code] = current_rank
        return ranks, len(rows)

    @staticmethod
    def _state(metric: SectorPriceVolumeMetricFact) -> SectorPriceVolumeState | None:
        price = metric.price_momentum_pct
        amount = metric.amount_activity_pct
        if price is None or amount is None:
            return None
        if price > 0 and amount > 0:
            return "JOINT"
        if price > 0:
            return "PRICE_ONLY"
        if amount > 0:
            return "AMOUNT_ONLY"
        return "NEUTRAL"

    @staticmethod
    def as_json_percent(value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value.quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP))
