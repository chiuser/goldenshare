"""Prefix-causal replay and append-only incremental execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from collections.abc import Iterator
from typing import Mapping

from .bars import (
    CanonicalBar,
    ContinuityStatus,
    InputContractError,
    validate_canonical_bars,
)
from .pivot import CausalPivotEngine, PivotDetectionResult
from .profiles import DegreeProfile, DetectorProfile
from .scenarios import (
    ScenarioGenerationResult,
    ScenarioLifecycleTracker,
    ScenarioSnapshot,
)
from .swings import (
    ConfirmedSwing,
    FormingLeg,
    build_confirmed_swings,
    build_forming_leg,
)


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    as_of: datetime
    bar_visible_through: datetime
    detection: PivotDetectionResult
    confirmed_swings: tuple[ConfirmedSwing, ...]
    forming_leg: FormingLeg | None
    confirmed_scenarios: ScenarioGenerationResult
    provisional_scenarios: tuple[ScenarioSnapshot, ...]


@dataclass(frozen=True, slots=True)
class WaveReplayResult:
    snapshots: tuple[ReplaySnapshot, ...]

    @property
    def final(self) -> ReplaySnapshot:
        if not self.snapshots:
            raise ValueError("replay has no snapshots")
        return self.snapshots[-1]


def replay_wave(
    bars: tuple[CanonicalBar, ...] | list[CanonicalBar],
    *,
    detector: DetectorProfile,
    degree: DegreeProfile,
    continuity_status: ContinuityStatus = ContinuityStatus.COMPLETE,
    created_at: datetime | None = None,
) -> WaveReplayResult:
    """Replay every prefix; never derive a past snapshot from a future full run."""

    return WaveReplayResult(
        tuple(
            iter_wave_replay(
                bars,
                detector=detector,
                degree=degree,
                continuity_status=continuity_status,
                created_at=created_at,
            )
        )
    )


def iter_wave_replay(
    bars: tuple[CanonicalBar, ...] | list[CanonicalBar],
    *,
    detector: DetectorProfile,
    degree: DegreeProfile,
    continuity_status: ContinuityStatus = ContinuityStatus.COMPLETE,
    created_at: datetime | None = None,
) -> Iterator[ReplaySnapshot]:
    """Yield immutable prefix snapshots so long histories need not remain resident."""

    validated = validate_canonical_bars(bars, continuity_status=continuity_status)
    incremental = IncrementalWaveReplay(
        detector=detector,
        degree=degree,
        continuity_status=continuity_status,
        created_at=created_at,
    )
    for bar in validated:
        yield incremental.append(bar)


class IncrementalWaveReplay:
    """Append each bar exactly once while retaining immutable prefix snapshots."""

    def __init__(
        self,
        *,
        detector: DetectorProfile,
        degree: DegreeProfile,
        continuity_status: ContinuityStatus = ContinuityStatus.COMPLETE,
        created_at: datetime | None = None,
    ) -> None:
        self._detector = detector
        self._degree = degree
        self._continuity_status = continuity_status
        self._created_at = created_at
        self._bars: list[CanonicalBar] = []
        self._pivot_engine = CausalPivotEngine(
            profile=detector,
            degree=degree,
            continuity_status=continuity_status,
            created_at=created_at,
        )
        self._lifecycle = ScenarioLifecycleTracker()
        self._snapshots: list[ReplaySnapshot] = []
        self._confirmed_swings: tuple[ConfirmedSwing, ...] = ()
        self._confirmation_count = 0

    @property
    def snapshots(self) -> tuple[ReplaySnapshot, ...]:
        return tuple(self._snapshots)

    def append(self, bar: CanonicalBar) -> ReplaySnapshot:
        detection = self._pivot_engine.append(bar, retain_atr_history=False)
        self._bars.append(bar)
        bars = tuple(self._bars)
        as_of = bar.bar_end_at
        if len(detection.confirmations) != self._confirmation_count:
            self._confirmed_swings = build_confirmed_swings(
                detection.confirmations, bars
            )
            self._confirmation_count = len(detection.confirmations)
        swings = self._confirmed_swings
        forming = build_forming_leg(detection, bars)
        scenarios = self._lifecycle.generate(
            detection.confirmations,
            degree=self._degree,
            detector=self._detector,
            as_of=as_of,
            bar_visible_through=as_of,
            swings=swings,
        )
        provisional = tuple(
            replace(snapshot, uses_provisional=True, forming_leg=forming)
            for snapshot in scenarios.snapshots
            if forming is not None
        )
        snapshot = ReplaySnapshot(
            as_of=as_of,
            bar_visible_through=as_of,
            detection=detection,
            confirmed_swings=swings,
            forming_leg=forming,
            confirmed_scenarios=scenarios,
            provisional_scenarios=provisional,
        )
        self._snapshots.append(snapshot)
        return snapshot


def validate_context_visibility(
    *, decision_as_of: datetime, visible_through_by_freq: Mapping[str, datetime]
) -> None:
    if decision_as_of.tzinfo is None or decision_as_of.utcoffset() is None:
        raise InputContractError(
            "DECISION_AS_OF_TIMEZONE_INVALID", "decision_as_of must be timezone-aware"
        )
    for freq, visible_through in visible_through_by_freq.items():
        if visible_through > decision_as_of:
            raise InputContractError(
                "CROSS_PERIOD_FUTURE_CONTEXT",
                f"{freq} is visible only after the module decision time",
            )
