"""Causal ATR/fixed-threshold pivot confirmation state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from .bars import (
    CanonicalBar,
    ContinuityStatus,
    InputContractError,
    validate_canonical_bars,
)
from .identities import canonical_datetime, canonical_decimal, stable_hash
from .profiles import DegreeProfile, DetectorProfile


MODEL_VERSION = "INDEX_WAVE_CORE_V1"


class PivotType(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class DetectorState(str, Enum):
    WARMUP = "WARMUP"
    UNDEFINED = "UNDEFINED"
    UP = "UP"
    DOWN = "DOWN"


@dataclass(frozen=True, slots=True)
class PivotCandidate:
    pivot_type: PivotType
    extreme_at: datetime
    extreme_price: Decimal
    threshold_at_extreme: Decimal
    candidate_updated_at: datetime
    extreme_bar_key: str
    extreme_trade_date: date
    extreme_source_partition: str


@dataclass(frozen=True, slots=True)
class PivotConfirmation:
    model_version: str
    data_snapshot_id: str
    ts_code: str
    freq: str
    degree_key: str
    pivot_key: str
    pivot_type: PivotType
    extreme_at: datetime
    extreme_trade_date: date
    extreme_price: Decimal
    confirmed_at: datetime
    confirmation_trade_date: date
    confirmation_close: Decimal
    threshold_at_extreme: Decimal
    detector_profile_key: str
    extreme_bar_key: str
    confirmation_bar_key: str
    source_asset_key: str
    extreme_source_partition: str
    confirmation_source_partition: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PivotDetectionResult:
    state: DetectorState
    confirmations: tuple[PivotConfirmation, ...]
    candidate_high: PivotCandidate | None
    candidate_low: PivotCandidate | None
    atr_values: tuple[Decimal | None, ...]
    atr_history_complete: bool
    bar_visible_through: datetime

    @property
    def forming_candidate(self) -> PivotCandidate | None:
        if self.state is DetectorState.UP:
            return self.candidate_high
        if self.state is DetectorState.DOWN:
            return self.candidate_low
        return None


def wilder_atr(
    bars: tuple[CanonicalBar, ...], period: int
) -> tuple[Decimal | None, ...]:
    if period <= 0:
        raise ValueError("ATR period must be positive")
    true_ranges: list[Decimal] = []
    for index, bar in enumerate(bars):
        if index == 0:
            true_range = bar.high - bar.low
        else:
            previous_close = bars[index - 1].close
            true_range = max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        if not true_range.is_finite() or true_range < 0:
            raise ValueError("true range must be finite and non-negative")
        true_ranges.append(true_range)

    atr_values: list[Decimal | None] = [None] * len(bars)
    if len(bars) < period:
        return tuple(atr_values)
    seed = sum(true_ranges[:period], Decimal(0)) / Decimal(period)
    atr_values[period - 1] = seed
    previous = seed
    for index in range(period, len(bars)):
        previous = (previous * Decimal(period - 1) + true_ranges[index]) / Decimal(
            period
        )
        atr_values[index] = previous
    return tuple(atr_values)


def _threshold(
    profile: DetectorProfile,
    atr_values: tuple[Decimal | None, ...],
    index: int,
) -> Decimal | None:
    if profile.detector_key == "ABSOLUTE_REVERSAL_TEST":
        return profile.fixed_reversal
    atr = atr_values[index]
    if atr is None:
        return None
    assert profile.atr_multiplier is not None
    return atr * profile.atr_multiplier


def _candidate(
    pivot_type: PivotType,
    bar: CanonicalBar,
    threshold: Decimal,
) -> PivotCandidate:
    price = bar.high if pivot_type is PivotType.HIGH else bar.low
    return PivotCandidate(
        pivot_type=pivot_type,
        extreme_at=bar.bar_end_at,
        extreme_price=price,
        threshold_at_extreme=threshold,
        candidate_updated_at=bar.bar_end_at,
        extreme_bar_key=bar.bar_key,
        extreme_trade_date=bar.trade_date,
        extreme_source_partition=bar.source_partition,
    )


def _confirmation(
    candidate: PivotCandidate,
    bar: CanonicalBar,
    *,
    profile: DetectorProfile,
    degree: DegreeProfile,
    created_at: datetime,
) -> PivotConfirmation:
    pivot_key = stable_hash(
        "pivot/v1",
        bar.ts_code,
        bar.freq,
        degree.degree_key,
        profile.detector_profile_key,
        candidate.pivot_type.value,
        canonical_datetime(candidate.extreme_at),
        canonical_decimal(candidate.extreme_price),
        canonical_datetime(bar.bar_end_at),
        canonical_decimal(candidate.threshold_at_extreme),
    )
    return PivotConfirmation(
        model_version=MODEL_VERSION,
        data_snapshot_id=bar.data_snapshot_id,
        ts_code=bar.ts_code,
        freq=bar.freq,
        degree_key=degree.degree_key,
        pivot_key=pivot_key,
        pivot_type=candidate.pivot_type,
        extreme_at=candidate.extreme_at,
        extreme_trade_date=candidate.extreme_trade_date,
        extreme_price=candidate.extreme_price,
        confirmed_at=bar.bar_end_at,
        confirmation_trade_date=bar.trade_date,
        confirmation_close=bar.close,
        threshold_at_extreme=candidate.threshold_at_extreme,
        detector_profile_key=profile.detector_profile_key,
        extreme_bar_key=candidate.extreme_bar_key,
        confirmation_bar_key=bar.bar_key,
        source_asset_key=bar.source_asset_key,
        extreme_source_partition=candidate.extreme_source_partition,
        confirmation_source_partition=bar.source_partition,
        created_at=created_at,
    )


class CausalPivotEngine:
    """Append-only implementation of the frozen V1 detector state machine."""

    def __init__(
        self,
        *,
        profile: DetectorProfile,
        degree: DegreeProfile,
        continuity_status: ContinuityStatus = ContinuityStatus.COMPLETE,
        created_at: datetime | None = None,
    ) -> None:
        if degree.detector_profile_key != profile.detector_profile_key and not (
            profile.detector_key == "ABSOLUTE_REVERSAL_TEST"
            and not profile.research_eligible
        ):
            raise ValueError("degree and detector profile keys do not match")
        if created_at is not None and (
            created_at.tzinfo is None or created_at.utcoffset() is None
        ):
            raise ValueError("created_at must be timezone-aware")
        if continuity_status not in {
            ContinuityStatus.COMPLETE,
            ContinuityStatus.KNOWN_SESSION_EXCEPTION,
        }:
            raise InputContractError(
                "BAR_CONTINUITY_NOT_READY",
                f"continuity status {continuity_status.value} is not runnable",
            )
        self._profile = profile
        self._degree = degree
        self._continuity_status = continuity_status
        self._created_at = created_at
        self._bars: list[CanonicalBar] = []
        self._identity: tuple[str, str, str, str, str] | None = None
        self._true_ranges: list[Decimal] = []
        self._atr_values: list[Decimal | None] = []
        self._last_atr: Decimal | None = None
        self._state = DetectorState.WARMUP
        self._candidate_high: PivotCandidate | None = None
        self._candidate_low: PivotCandidate | None = None
        self._confirmations: list[PivotConfirmation] = []

    @property
    def bars(self) -> tuple[CanonicalBar, ...]:
        return tuple(self._bars)

    def append(
        self, bar: CanonicalBar, *, retain_atr_history: bool = True
    ) -> PivotDetectionResult:
        validate_canonical_bars(
            (bar,),
            as_of=bar.bar_end_at,
            continuity_status=self._continuity_status,
        )
        identity = (
            bar.ts_code,
            bar.freq,
            bar.source_asset_key,
            bar.source_contract_version,
            bar.data_snapshot_id,
        )
        if self._identity is None:
            self._identity = identity
        elif identity != self._identity:
            raise InputContractError(
                "BAR_SEQUENCE_IDENTITY_MIXED",
                "one run may contain only one instrument/frequency/source snapshot",
            )
        if self._bars:
            previous_end = self._bars[-1].bar_end_at
            if bar.bar_end_at == previous_end:
                raise InputContractError(
                    "BAR_SEQUENCE_DUPLICATE", "duplicate bar_end_at detected"
                )
            if bar.bar_end_at < previous_end:
                raise InputContractError(
                    "BAR_SEQUENCE_OUT_OF_ORDER",
                    "bar_end_at must be strictly increasing",
                )
        self._append_atr(bar)
        self._bars.append(bar)
        self._process_bar(bar, len(self._bars) - 1)
        return self.result(retain_atr_history=retain_atr_history)

    def result(self, *, retain_atr_history: bool = True) -> PivotDetectionResult:
        if not self._bars:
            raise ValueError("pivot engine has not received a bar")
        return PivotDetectionResult(
            state=self._state,
            confirmations=tuple(self._confirmations),
            candidate_high=self._candidate_high,
            candidate_low=self._candidate_low,
            atr_values=(
                tuple(self._atr_values)
                if retain_atr_history
                else (self._atr_values[-1],)
            ),
            atr_history_complete=retain_atr_history,
            bar_visible_through=self._bars[-1].bar_end_at,
        )

    def _append_atr(self, bar: CanonicalBar) -> None:
        if not self._bars:
            true_range = bar.high - bar.low
        else:
            previous_close = self._bars[-1].close
            true_range = max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        if not true_range.is_finite() or true_range < 0:
            raise ValueError("true range must be finite and non-negative")
        self._true_ranges.append(true_range)
        if self._profile.detector_key != "CAUSAL_ATR_ZIGZAG":
            self._atr_values.append(None)
            return
        assert self._profile.atr_period is not None
        period = self._profile.atr_period
        if len(self._true_ranges) < period:
            self._atr_values.append(None)
        elif len(self._true_ranges) == period:
            self._last_atr = sum(self._true_ranges, Decimal(0)) / Decimal(period)
            self._atr_values.append(self._last_atr)
        else:
            assert self._last_atr is not None
            self._last_atr = (
                self._last_atr * Decimal(period - 1) + true_range
            ) / Decimal(period)
            self._atr_values.append(self._last_atr)

    def _record_confirmation(
        self, candidate: PivotCandidate, bar: CanonicalBar
    ) -> None:
        confirmation = _confirmation(
            candidate,
            bar,
            profile=self._profile,
            degree=self._degree,
            created_at=self._created_at or bar.bar_end_at,
        )
        if self._confirmations:
            previous = self._confirmations[-1]
            if previous.pivot_type is confirmation.pivot_type:
                raise AssertionError("confirmed pivot types must alternate")
            if previous.extreme_at >= confirmation.extreme_at:
                raise AssertionError("confirmed extreme_at must be strictly increasing")
            if previous.confirmed_at >= confirmation.confirmed_at:
                raise AssertionError("confirmed_at must be strictly increasing")
        self._confirmations.append(confirmation)

    def _process_bar(self, bar: CanonicalBar, index: int) -> None:
        threshold = _threshold(self._profile, tuple(self._atr_values), index)
        if threshold is None:
            return
        if not threshold.is_finite() or threshold <= 0:
            raise ValueError("reversal threshold must be finite and positive")

        if self._state is DetectorState.WARMUP:
            self._state = DetectorState.UNDEFINED
            self._candidate_high = _candidate(PivotType.HIGH, bar, threshold)
            self._candidate_low = _candidate(PivotType.LOW, bar, threshold)
        elif self._state is DetectorState.UNDEFINED:
            if self._candidate_high is None or self._candidate_low is None:
                raise AssertionError("undefined state requires both candidates")
            if bar.high > self._candidate_high.extreme_price:
                self._candidate_high = _candidate(PivotType.HIGH, bar, threshold)
            if bar.low < self._candidate_low.extreme_price:
                self._candidate_low = _candidate(PivotType.LOW, bar, threshold)
        elif self._state is DetectorState.UP:
            if self._candidate_high is None:
                self._candidate_high = _candidate(PivotType.HIGH, bar, threshold)
            elif bar.high > self._candidate_high.extreme_price:
                self._candidate_high = _candidate(PivotType.HIGH, bar, threshold)
        elif self._state is DetectorState.DOWN:
            if self._candidate_low is None:
                self._candidate_low = _candidate(PivotType.LOW, bar, threshold)
            elif bar.low < self._candidate_low.extreme_price:
                self._candidate_low = _candidate(PivotType.LOW, bar, threshold)

        if self._state is DetectorState.UNDEFINED:
            assert self._candidate_high is not None and self._candidate_low is not None
            confirms_low = (
                bar.close - self._candidate_low.extreme_price
                >= self._candidate_low.threshold_at_extreme
            )
            confirms_high = (
                self._candidate_high.extreme_price - bar.close
                >= self._candidate_high.threshold_at_extreme
            )
            if confirms_low == confirms_high:
                return
            selected = self._candidate_low if confirms_low else self._candidate_high
            self._record_confirmation(selected, bar)
            self._state = (
                DetectorState.UP
                if selected.pivot_type is PivotType.LOW
                else DetectorState.DOWN
            )
            self._candidate_high = None
            self._candidate_low = None
            return

        if self._state is DetectorState.UP and self._candidate_high is not None:
            if (
                self._candidate_high.extreme_price - bar.close
                >= self._candidate_high.threshold_at_extreme
            ):
                self._record_confirmation(self._candidate_high, bar)
                self._state = DetectorState.DOWN
                self._candidate_high = None
                self._candidate_low = None
        elif self._state is DetectorState.DOWN and self._candidate_low is not None:
            if (
                bar.close - self._candidate_low.extreme_price
                >= self._candidate_low.threshold_at_extreme
            ):
                self._record_confirmation(self._candidate_low, bar)
                self._state = DetectorState.UP
                self._candidate_high = None
                self._candidate_low = None


def detect_pivots(
    bars: tuple[CanonicalBar, ...] | list[CanonicalBar],
    *,
    profile: DetectorProfile,
    degree: DegreeProfile,
    as_of: datetime | None = None,
    continuity_status: ContinuityStatus = ContinuityStatus.COMPLETE,
    created_at: datetime | None = None,
) -> PivotDetectionResult:
    """Run the frozen V1 state machine over an already bounded prefix."""

    validated = validate_canonical_bars(
        bars, as_of=as_of, continuity_status=continuity_status
    )
    engine = CausalPivotEngine(
        profile=profile,
        degree=degree,
        continuity_status=continuity_status,
        created_at=created_at,
    )
    result: PivotDetectionResult | None = None
    for bar in validated:
        result = engine.append(bar)
    assert result is not None
    return result
