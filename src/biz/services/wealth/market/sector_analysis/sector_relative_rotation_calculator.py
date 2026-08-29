from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from src.biz.services.wealth.market.sector_analysis.sector_momentum_calculator import (
    PERCENTILE_QUANTUM,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    MissingReason,
)
from src.biz.services.wealth.market.sector_analysis.sector_relative_rotation_contract import (
    IMPROVEMENT_LOOKBACK_DAYS,
    MINIMUM_GROUP_SIZE,
    X_SPLIT,
    SectorRelativeRotationPointFact,
    SectorRelativeRotationRankSlice,
    SectorRelativeRotationSelectedRankSlice,
    SectorRelativeRotationStatus,
)


class SectorRelativeRotationCalculator:
    """Calculate relative-rotation coordinates from existing return and rank facts."""

    @classmethod
    def calculate_current_snapshot(
        cls,
        *,
        sector_codes: tuple[str, ...],
        open_dates: tuple[date, ...],
        current_date: date,
        current_slice: SectorRelativeRotationRankSlice,
        comparison_slice: SectorRelativeRotationRankSlice,
    ) -> tuple[SectorRelativeRotationPointFact, ...]:
        cls._validate_current_snapshot_inputs(
            sector_codes=sector_codes,
            open_dates=open_dates,
            current_date=current_date,
            current_slice=current_slice,
            comparison_slice=comparison_slice,
        )
        return tuple(
            cls._calculate_point(
                sector_code=sector_code,
                trade_date=current_date,
                current=(
                    current_slice.returns[index],
                    current_slice.ranked[index],
                ),
                comparison=(
                    comparison_slice.returns[index],
                    comparison_slice.ranked[index],
                ),
                current_count=current_slice.calculable_count,
                comparison_count=comparison_slice.calculable_count,
            )
            for index, sector_code in enumerate(sector_codes)
        )

    @classmethod
    def calculate_selected_trail(
        cls,
        *,
        selected_sector_code: str,
        open_dates: tuple[date, ...],
        display_dates: tuple[date, ...],
        rank_slices: Mapping[date, SectorRelativeRotationSelectedRankSlice],
    ) -> tuple[SectorRelativeRotationPointFact, ...]:
        cls._validate_selected_trail_inputs(
            selected_sector_code=selected_sector_code,
            open_dates=open_dates,
            display_dates=display_dates,
            rank_slices=rank_slices,
        )
        date_indexes = {item: index for index, item in enumerate(open_dates)}
        points: list[SectorRelativeRotationPointFact] = []
        for display_date in display_dates:
            comparison_date = open_dates[
                date_indexes[display_date] - IMPROVEMENT_LOOKBACK_DAYS
            ]
            current_slice = rank_slices[display_date]
            comparison_slice = rank_slices[comparison_date]
            points.append(
                cls._calculate_point(
                    sector_code=selected_sector_code,
                    trade_date=display_date,
                    current=(current_slice.return_fact, current_slice.rank_fact),
                    comparison=(
                        comparison_slice.return_fact,
                        comparison_slice.rank_fact,
                    ),
                    current_count=current_slice.calculable_count,
                    comparison_count=comparison_slice.calculable_count,
                )
            )
        return tuple(points)

    @staticmethod
    def canonical_sort(
        rows: Iterable[SectorRelativeRotationPointFact],
    ) -> tuple[SectorRelativeRotationPointFact, ...]:
        def sort_key(row: SectorRelativeRotationPointFact):
            if row.percentile is None:
                return (2, Decimal(0), Decimal(0), row.sector_code)
            if row.percentile_delta_5d is None:
                return (1, -row.percentile, Decimal(0), row.sector_code)
            return (
                0,
                -row.percentile,
                -row.percentile_delta_5d,
                row.sector_code,
            )

        return tuple(sorted(rows, key=sort_key))

    @classmethod
    def _calculate_point(
        cls,
        *,
        sector_code: str,
        trade_date: date,
        current,
        comparison,
        current_count: int,
        comparison_count: int,
    ) -> SectorRelativeRotationPointFact:
        current_return, current_rank = current
        comparison_return, comparison_rank = comparison
        current_reason = cls._normalize_reason(current_return.missing_reason)
        comparison_reason = cls._normalize_reason(comparison_return.missing_reason)

        if current_rank.percentile is None:
            delta = None
            coordinate_status = "UNAVAILABLE"
            rotation_status = "DATA_INSUFFICIENT"
        elif comparison_rank.percentile is None:
            delta = None
            coordinate_status = "UNAVAILABLE"
            rotation_status = "DATA_INSUFFICIENT"
        else:
            delta = (current_rank.percentile - comparison_rank.percentile).quantize(
                PERCENTILE_QUANTUM,
                rounding=ROUND_HALF_UP,
            )
            coordinate_status = "PLOTTABLE"
            if (
                current_count < MINIMUM_GROUP_SIZE
                or comparison_count < MINIMUM_GROUP_SIZE
            ):
                rotation_status = "SAMPLE_INSUFFICIENT"
            else:
                rotation_status = cls._classify(
                    percentile=current_rank.percentile,
                    delta=delta,
                )

        return SectorRelativeRotationPointFact(
            sector_code=sector_code,
            trade_date=trade_date,
            return_pct=current_rank.return_pct,
            strength_rank=current_rank.strength_rank,
            percentile=current_rank.percentile,
            percentile_delta_5d=delta,
            current_calculable_count=current_count,
            comparison_calculable_count=comparison_count,
            rotation_status=rotation_status,
            coordinate_status=coordinate_status,
            current_missing_reason=current_reason,
            comparison_missing_reason=comparison_reason,
        )

    @staticmethod
    def _classify(
        *,
        percentile: Decimal,
        delta: Decimal,
    ) -> SectorRelativeRotationStatus:
        if percentile >= X_SPLIT and delta > 0:
            return "LEADING_IMPROVING"
        if percentile < X_SPLIT and delta > 0:
            return "WEAK_IMPROVING"
        if percentile >= X_SPLIT and delta <= 0:
            return "STRONG_NOT_IMPROVING"
        return "WEAK_NOT_IMPROVING"

    @staticmethod
    def _normalize_reason(reason: MissingReason) -> MissingReason | None:
        return None if reason == "NONE" else reason

    @staticmethod
    def _validate_current_snapshot_inputs(
        *,
        sector_codes: tuple[str, ...],
        open_dates: tuple[date, ...],
        current_date: date,
        current_slice: SectorRelativeRotationRankSlice,
        comparison_slice: SectorRelativeRotationRankSlice,
    ) -> None:
        if not sector_codes or len(sector_codes) != len(set(sector_codes)):
            raise ValueError(
                "relative-rotation sector codes must be non-empty and unique"
            )
        if not open_dates or open_dates != tuple(sorted(set(open_dates))):
            raise ValueError(
                "relative-rotation open dates must be unique and ascending"
            )
        date_indexes = {item: index for index, item in enumerate(open_dates)}
        position = date_indexes.get(current_date)
        if position is None or position < IMPROVEMENT_LOOKBACK_DAYS:
            raise ValueError("relative-rotation current date lacks its comparison date")
        comparison_date = open_dates[position - IMPROVEMENT_LOOKBACK_DAYS]
        if current_slice.trade_date != current_date:
            raise ValueError("relative-rotation current rank slice is misdated")
        if comparison_slice.trade_date != comparison_date:
            raise ValueError("relative-rotation comparison rank slice is misdated")
        for rank_slice in (current_slice, comparison_slice):
            slice_codes = tuple(item.sector_code for item in rank_slice.ranked)
            if slice_codes != sector_codes:
                raise ValueError("relative-rotation rank slice does not match the pool")

    @staticmethod
    def _validate_selected_trail_inputs(
        *,
        selected_sector_code: str,
        open_dates: tuple[date, ...],
        display_dates: tuple[date, ...],
        rank_slices: Mapping[date, SectorRelativeRotationSelectedRankSlice],
    ) -> None:
        if not selected_sector_code:
            raise ValueError("relative-rotation selected sector code is required")
        if not open_dates or open_dates != tuple(sorted(set(open_dates))):
            raise ValueError(
                "relative-rotation open dates must be unique and ascending"
            )
        if not display_dates or display_dates != tuple(sorted(set(display_dates))):
            raise ValueError(
                "relative-rotation display dates must be unique and ascending"
            )
        date_indexes = {item: index for index, item in enumerate(open_dates)}
        required_dates: set[date] = set()
        for display_date in display_dates:
            position = date_indexes.get(display_date)
            if position is None or position < IMPROVEMENT_LOOKBACK_DAYS:
                raise ValueError(
                    "relative-rotation display date lacks its comparison date"
                )
            required_dates.add(display_date)
            required_dates.add(open_dates[position - IMPROVEMENT_LOOKBACK_DAYS])
        for required_date in required_dates:
            rank_slice = rank_slices.get(required_date)
            if rank_slice is None or rank_slice.trade_date != required_date:
                raise ValueError("relative-rotation rank slice is missing or misdated")
            if rank_slice.rank_fact.sector_code != selected_sector_code:
                raise ValueError(
                    "relative-rotation selected rank slice has the wrong sector"
                )
