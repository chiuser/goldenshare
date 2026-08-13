from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Sequence

from src.biz.services.wealth.config import SectorOverviewHeatStrategyPayload


_BASE_SCORE_QUANTUM = Decimal("0.0001")
_FINAL_SCORE_QUANTUM = Decimal("0.01")
_COMPONENT_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class SectorPoolCounts:
    source_member_count: int
    member_count: int
    suspended_count: int
    quote_eligible_count: int
    valid_quote_count: int
    missing_quote_count: int
    quote_coverage: float


@dataclass(frozen=True, slots=True)
class SectorHeatRawFeatureRow:
    trade_date: date
    sector_code: str
    sector_name: str
    pool: SectorPoolCounts
    invalid_reason: str | None = None
    daily_return: float | None = None
    relative_strength_5: float | None = None
    daily_acceleration: float | None = None
    up_ratio: float | None = None
    limit_up_ratio: float | None = None
    net_inflow_strength: float | None = None
    positive_inflow_day_ratio_5: float | None = None
    net_inflow_rate_slope_5: float | None = None
    activity: float | None = None


@dataclass(frozen=True, slots=True)
class PriorPublishedHeat:
    trade_date: date
    heat_status: str
    heat_score: Decimal | None
    raw_heat_trend: str
    score_version: str
    config_hash: str


@dataclass(frozen=True, slots=True)
class SectorHeatCandidate:
    trade_date: date
    sector_code: str
    sector_name: str
    heat_status: str
    invalid_reason: str | None
    base_heat_score: Decimal | None
    base_heat_rank: int | None
    heat_score: Decimal | None
    heat_rank: int | None
    heat_level: str
    heat_delta_1d: Decimal | None
    heat_trend: str
    raw_heat_trend: str
    price_strength_score: Decimal | None
    breadth_score: Decimal | None
    capital_flow_score: Decimal | None
    activity_score: Decimal | None
    persistence_score: Decimal | None
    pool: SectorPoolCounts


@dataclass(frozen=True, slots=True)
class _BaseScore:
    score: float
    rank: int
    price_strength: float
    breadth: float
    capital_flow: float
    activity: float


class SectorHeatContract:
    """Pure EOD V1 cross-sectional scoring contract."""

    def __init__(self, config: SectorOverviewHeatStrategyPayload) -> None:
        self.config = config

    @staticmethod
    def winsorize(values: Sequence[float], *, lower: float, upper: float) -> list[float]:
        finite_values = [float(value) for value in values if math.isfinite(float(value))]
        if not finite_values:
            return []
        low_value = SectorHeatContract._quantile(finite_values, lower)
        high_value = SectorHeatContract._quantile(finite_values, upper)
        return [min(max(float(value), low_value), high_value) for value in values]

    @staticmethod
    def empirical_percentiles(values: Mapping[str, float], *, lower: float, upper: float) -> dict[str, float]:
        ordered_codes = sorted(values)
        clipped_values = SectorHeatContract.winsorize(
            [values[code] for code in ordered_codes],
            lower=lower,
            upper=upper,
        )
        if not clipped_values:
            return {}
        if len(clipped_values) == 1:
            return {ordered_codes[0]: 0.5}

        indices_by_value: dict[float, list[int]] = {}
        for index, value in enumerate(sorted(clipped_values), start=1):
            indices_by_value.setdefault(value, []).append(index)
        average_rank = {value: sum(indices) / len(indices) for value, indices in indices_by_value.items()}
        denominator = len(clipped_values) - 1
        return {
            code: (average_rank[value] - 1) / denominator
            for code, value in zip(ordered_codes, clipped_values, strict=True)
        }

    @staticmethod
    def linear_slope(values: Sequence[float]) -> float:
        if len(values) < 2:
            raise ValueError("linear slope requires at least two values")
        x_mean = (len(values) - 1) / 2
        y_mean = sum(values) / len(values)
        denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
        if denominator == 0:
            return 0.0
        return sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values)) / denominator

    def calculate(
        self,
        *,
        ordered_trade_dates: Sequence[date],
        rows_by_date: Mapping[date, Sequence[SectorHeatRawFeatureRow]],
        prior_published_by_date: Mapping[date, Mapping[str, PriorPublishedHeat]],
        config_hash: str,
    ) -> list[SectorHeatCandidate]:
        required_dates = self.config.persistence_trading_days + 1
        if len(ordered_trade_dates) != required_dates:
            raise ValueError(f"expected {required_dates} calculation dates, got {len(ordered_trade_dates)}")
        target_date = ordered_trade_dates[-1]
        complete_codes_by_date = [
            {
                row.sector_code
                for row in rows_by_date.get(trade_date, ())
                if row.invalid_reason is None and self._has_complete_base_features(row)
            }
            for trade_date in ordered_trade_dates
        ]
        target_history_ready_codes = set.intersection(*complete_codes_by_date) if complete_codes_by_date else set()
        base_by_date = {}
        for trade_date in ordered_trade_dates:
            rows = rows_by_date.get(trade_date, ())
            if trade_date == target_date:
                rows = tuple(row for row in rows if row.sector_code in target_history_ready_codes)
            base_by_date[trade_date] = self._calculate_base_cross_section(rows)
        target_rows = {row.sector_code: row for row in rows_by_date.get(target_date, ())}

        persistence_ready: dict[str, tuple[float, float]] = {}
        target_base = base_by_date[target_date]
        for sector_code, current_base in target_base.items():
            historical_ranks: list[int] = []
            for historical_date in ordered_trade_dates[:-1]:
                historical = base_by_date[historical_date].get(sector_code)
                if historical is None:
                    break
                historical_ranks.append(historical.rank)
            if len(historical_ranks) != self.config.persistence_trading_days:
                continue
            streak = 0
            for rank in reversed(historical_ranks):
                if rank > self.config.persistence_top_n:
                    break
                streak += 1
            persistence_ready[sector_code] = (float(streak), float(historical_ranks[-1] - current_base.rank))

        persistence_scores = self._calculate_persistence_scores(persistence_ready)
        unranked_final_scores: dict[str, float] = {}
        for sector_code, persistence_score in persistence_scores.items():
            base = target_base[sector_code]
            weights = self.config.weights
            unranked_final_scores[sector_code] = 100 * (
                float(weights.price_strength) * base.price_strength
                + float(weights.breadth) * base.breadth
                + float(weights.capital_flow) * base.capital_flow
                + float(weights.activity) * base.activity
                + float(weights.persistence) * persistence_score
            )
        final_ranks = self._stable_descending_ranks(unranked_final_scores)

        candidates: list[SectorHeatCandidate] = []
        for sector_code in sorted(target_rows):
            row = target_rows[sector_code]
            base = target_base.get(sector_code)
            persistence_score = persistence_scores.get(sector_code)
            invalid_reason = row.invalid_reason
            if invalid_reason is None and not self._has_complete_base_features(row):
                invalid_reason = "FEATURE_MISSING"
            if invalid_reason is None and (
                sector_code not in target_history_ready_codes or base is None or persistence_score is None
            ):
                invalid_reason = "HISTORY_INSUFFICIENT"
            if invalid_reason is not None:
                candidates.append(self._invalid_candidate(row=row, base=base, invalid_reason=invalid_reason))
                continue

            final_score = unranked_final_scores[sector_code]
            published_score = self._decimal_final_score(final_score)
            heat_delta, raw_trend, heat_trend = self._resolve_trend(
                sector_code=sector_code,
                current_score=float(published_score),
                ordered_trade_dates=ordered_trade_dates,
                prior_published_by_date=prior_published_by_date,
                config_hash=config_hash,
            )
            candidates.append(
                SectorHeatCandidate(
                    trade_date=target_date,
                    sector_code=sector_code,
                    sector_name=row.sector_name,
                    heat_status="VALID",
                    invalid_reason=None,
                    base_heat_score=self._decimal_base_score(base.score),
                    base_heat_rank=base.rank,
                    heat_score=published_score,
                    heat_rank=final_ranks[sector_code],
                    heat_level=self._heat_level(float(published_score)),
                    heat_delta_1d=self._decimal_final_score(heat_delta) if heat_delta is not None else None,
                    heat_trend=heat_trend,
                    raw_heat_trend=raw_trend,
                    price_strength_score=self._decimal_component(base.price_strength),
                    breadth_score=self._decimal_component(base.breadth),
                    capital_flow_score=self._decimal_component(base.capital_flow),
                    activity_score=self._decimal_component(base.activity),
                    persistence_score=self._decimal_component(persistence_score),
                    pool=row.pool,
                )
            )
        return candidates

    def _calculate_base_cross_section(self, rows: Sequence[SectorHeatRawFeatureRow]) -> dict[str, _BaseScore]:
        complete_rows = {
            row.sector_code: row
            for row in rows
            if row.invalid_reason is None and self._has_complete_base_features(row)
        }
        if not complete_rows:
            return {}
        lower = float(self.config.winsor.lower)
        upper = float(self.config.winsor.upper)

        def percentiles(field_name: str) -> dict[str, float]:
            return self.empirical_percentiles(
                {code: float(getattr(row, field_name)) for code, row in complete_rows.items()},
                lower=lower,
                upper=upper,
            )

        feature_percentiles = {
            field_name: percentiles(field_name)
            for field_name in (
                "daily_return",
                "relative_strength_5",
                "daily_acceleration",
                "up_ratio",
                "limit_up_ratio",
                "net_inflow_strength",
                "positive_inflow_day_ratio_5",
                "net_inflow_rate_slope_5",
                "activity",
            )
        }
        price_weights = self.config.component_weights.price
        breadth_weights = self.config.component_weights.breadth
        capital_weights = self.config.component_weights.capital_flow
        raw_components: dict[str, tuple[float, float, float, float]] = {}
        raw_base_scores: dict[str, float] = {}
        main_weights = self.config.weights
        base_weight_sum = float(
            main_weights.price_strength + main_weights.breadth + main_weights.capital_flow + main_weights.activity
        )
        for code in sorted(complete_rows):
            price = (
                float(price_weights.daily_return) * feature_percentiles["daily_return"][code]
                + float(price_weights.relative_strength_5) * feature_percentiles["relative_strength_5"][code]
                + float(price_weights.daily_acceleration) * feature_percentiles["daily_acceleration"][code]
            )
            breadth = (
                float(breadth_weights.up_ratio) * feature_percentiles["up_ratio"][code]
                + float(breadth_weights.limit_up_ratio) * feature_percentiles["limit_up_ratio"][code]
            )
            capital_persistence = (
                float(capital_weights.persistence.positive_day_ratio)
                * feature_percentiles["positive_inflow_day_ratio_5"][code]
                + float(capital_weights.persistence.slope) * feature_percentiles["net_inflow_rate_slope_5"][code]
            )
            capital_flow = (
                float(capital_weights.current) * feature_percentiles["net_inflow_strength"][code]
                + float(capital_weights.persistence.weight) * capital_persistence
            )
            activity = feature_percentiles["activity"][code]
            raw_components[code] = (price, breadth, capital_flow, activity)
            raw_base_scores[code] = 100 * (
                float(main_weights.price_strength) * price
                + float(main_weights.breadth) * breadth
                + float(main_weights.capital_flow) * capital_flow
                + float(main_weights.activity) * activity
            ) / base_weight_sum
        ranks = self._stable_descending_ranks(raw_base_scores)
        return {
            code: _BaseScore(
                score=raw_base_scores[code],
                rank=ranks[code],
                price_strength=raw_components[code][0],
                breadth=raw_components[code][1],
                capital_flow=raw_components[code][2],
                activity=raw_components[code][3],
            )
            for code in raw_base_scores
        }

    def _calculate_persistence_scores(self, raw_values: Mapping[str, tuple[float, float]]) -> dict[str, float]:
        if not raw_values:
            return {}
        lower = float(self.config.winsor.lower)
        upper = float(self.config.winsor.upper)
        streak_percentiles = self.empirical_percentiles(
            {code: values[0] for code, values in raw_values.items()}, lower=lower, upper=upper
        )
        improvement_percentiles = self.empirical_percentiles(
            {code: values[1] for code, values in raw_values.items()}, lower=lower, upper=upper
        )
        weights = self.config.component_weights.persistence
        return {
            code: (
                float(weights.top_20_streak) * streak_percentiles[code]
                + float(weights.rank_improvement) * improvement_percentiles[code]
            )
            for code in raw_values
        }

    def _resolve_trend(
        self,
        *,
        sector_code: str,
        current_score: float,
        ordered_trade_dates: Sequence[date],
        prior_published_by_date: Mapping[date, Mapping[str, PriorPublishedHeat]],
        config_hash: str,
    ) -> tuple[float | None, str, str]:
        previous_dates = list(reversed(ordered_trade_dates[:-1]))
        if not previous_dates:
            return None, "UNKNOWN", "UNKNOWN"
        previous = prior_published_by_date.get(previous_dates[0], {}).get(sector_code)
        if not self._is_comparable(previous, expected_date=previous_dates[0], config_hash=config_hash):
            return None, "UNKNOWN", "UNKNOWN"
        assert previous is not None and previous.heat_score is not None
        delta = current_score - float(previous.heat_score)
        raw_trend = self._raw_trend(delta)
        if raw_trend == "STABLE":
            return delta, raw_trend, "STABLE"

        confirmation_count = self.config.trend_confirmation_days - 1
        confirmation_dates = previous_dates[:confirmation_count]
        if len(confirmation_dates) != confirmation_count:
            return delta, raw_trend, "STABLE"
        for confirmation_date in confirmation_dates:
            candidate = prior_published_by_date.get(confirmation_date, {}).get(sector_code)
            if not self._is_comparable(candidate, expected_date=confirmation_date, config_hash=config_hash):
                return delta, raw_trend, "STABLE"
            assert candidate is not None
            if candidate.raw_heat_trend != raw_trend:
                return delta, raw_trend, "STABLE"
        return delta, raw_trend, raw_trend

    def _is_comparable(self, row: PriorPublishedHeat | None, *, expected_date: date, config_hash: str) -> bool:
        return bool(
            row is not None
            and row.trade_date == expected_date
            and row.heat_status == "VALID"
            and row.heat_score is not None
            and row.score_version == self.config.score_version
            and row.config_hash == config_hash
        )

    def _raw_trend(self, delta: float) -> str:
        if delta >= float(self.config.trend_thresholds.heating):
            return "HEATING"
        if delta <= float(self.config.trend_thresholds.cooling):
            return "COOLING"
        return "STABLE"

    def _heat_level(self, score: float) -> str:
        thresholds = self.config.level_thresholds
        if score >= float(thresholds.boiling):
            return "BOILING"
        if score >= float(thresholds.hot):
            return "HOT"
        if score >= float(thresholds.active):
            return "ACTIVE"
        return "NONE"

    @staticmethod
    def _invalid_candidate(
        *, row: SectorHeatRawFeatureRow, base: _BaseScore | None, invalid_reason: str
    ) -> SectorHeatCandidate:
        return SectorHeatCandidate(
            trade_date=row.trade_date,
            sector_code=row.sector_code,
            sector_name=row.sector_name,
            heat_status="INVALID",
            invalid_reason=invalid_reason,
            base_heat_score=SectorHeatContract._decimal_base_score(base.score) if base else None,
            base_heat_rank=base.rank if base else None,
            heat_score=None,
            heat_rank=None,
            heat_level="NONE",
            heat_delta_1d=None,
            heat_trend="UNKNOWN",
            raw_heat_trend="UNKNOWN",
            price_strength_score=SectorHeatContract._decimal_component(base.price_strength) if base else None,
            breadth_score=SectorHeatContract._decimal_component(base.breadth) if base else None,
            capital_flow_score=SectorHeatContract._decimal_component(base.capital_flow) if base else None,
            activity_score=SectorHeatContract._decimal_component(base.activity) if base else None,
            persistence_score=None,
            pool=row.pool,
        )

    @staticmethod
    def _has_complete_base_features(row: SectorHeatRawFeatureRow) -> bool:
        return all(
            value is not None and math.isfinite(float(value))
            for value in (
                row.daily_return,
                row.relative_strength_5,
                row.daily_acceleration,
                row.up_ratio,
                row.limit_up_ratio,
                row.net_inflow_strength,
                row.positive_inflow_day_ratio_5,
                row.net_inflow_rate_slope_5,
                row.activity,
            )
        )

    @staticmethod
    def _stable_descending_ranks(values: Mapping[str, float]) -> dict[str, int]:
        ordered = sorted(values, key=lambda code: (-values[code], code))
        return {code: index for index, code in enumerate(ordered, start=1)}

    @staticmethod
    def _quantile(values: Sequence[float], quantile: float) -> float:
        ordered = sorted(float(value) for value in values)
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * quantile
        lower_index = math.floor(position)
        upper_index = math.ceil(position)
        if lower_index == upper_index:
            return ordered[lower_index]
        fraction = position - lower_index
        return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction

    @staticmethod
    def _decimal_base_score(value: float) -> Decimal:
        return Decimal(str(value)).quantize(_BASE_SCORE_QUANTUM, rounding=ROUND_HALF_UP)

    @staticmethod
    def _decimal_final_score(value: float) -> Decimal:
        return Decimal(str(value)).quantize(_FINAL_SCORE_QUANTUM, rounding=ROUND_HALF_UP)

    @staticmethod
    def _decimal_component(value: float) -> Decimal:
        return Decimal(str(value)).quantize(_COMPONENT_QUANTUM, rounding=ROUND_HALF_UP)
