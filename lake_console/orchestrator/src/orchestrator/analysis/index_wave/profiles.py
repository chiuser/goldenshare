"""Versioned detector, grammar, score, and degree profiles."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .identities import as_decimal, canonical_decimal


FORBIDDEN_GENERIC_PROFILE_MARKERS = frozenset({"MACD_7_52_7", "P0", "P1", "P2", "P3"})


@dataclass(frozen=True, slots=True)
class DetectorProfile:
    detector_key: str
    detector_version: str
    detector_profile_key: str
    atr_period: int | None
    atr_seed_method: str
    atr_smoothing: str
    atr_multiplier: Decimal | None
    fixed_reversal: Decimal | None
    extreme_source: str = "HIGH_LOW"
    confirmation_source: str = "CLOSE"
    threshold_anchor: str = "EXTREME_BAR"
    equal_extreme_policy: str = "KEEP_EARLIER"
    dual_confirmation_policy: str = "WAIT_FOR_UNAMBIGUOUS_BAR"
    post_confirmation_reset_policy: str = "NEXT_BAR_RESET"
    warmup_policy: str = "NO_CANDIDATE_BEFORE_MATURE_ATR"
    research_eligible: bool = True

    def __post_init__(self) -> None:
        if self.atr_multiplier is not None:
            object.__setattr__(self, "atr_multiplier", as_decimal(self.atr_multiplier))
        if self.fixed_reversal is not None:
            object.__setattr__(self, "fixed_reversal", as_decimal(self.fixed_reversal))
        validate_generic_profile_payload(
            {
                field_name: getattr(self, field_name)
                for field_name in self.__dataclass_fields__
            }
        )
        if self.detector_key == "CAUSAL_ATR_ZIGZAG":
            if not self.atr_period or self.atr_period <= 0:
                raise ValueError("ATR detector requires a positive atr_period")
            if self.atr_multiplier is None or self.atr_multiplier <= 0:
                raise ValueError("ATR detector requires a positive multiplier")
            if self.fixed_reversal is not None:
                raise ValueError("ATR detector cannot use a fixed reversal")
        elif self.detector_key == "ABSOLUTE_REVERSAL_TEST":
            if self.fixed_reversal is None or self.fixed_reversal <= 0:
                raise ValueError("absolute test detector requires a positive threshold")
            if self.research_eligible:
                raise ValueError("absolute test detector cannot be research eligible")
        else:
            raise ValueError(f"unsupported detector_key: {self.detector_key}")

    @classmethod
    def absolute_test(cls, threshold: Decimal | int | float | str) -> "DetectorProfile":
        converted = as_decimal(threshold)
        return cls(
            detector_key="ABSOLUTE_REVERSAL_TEST",
            detector_version="ABSOLUTE_REVERSAL_TEST_V1",
            detector_profile_key=(
                f"ABSOLUTE_REVERSAL_TEST_{canonical_decimal(converted)}_V1"
            ),
            atr_period=None,
            atr_seed_method="NOT_APPLICABLE",
            atr_smoothing="NOT_APPLICABLE",
            atr_multiplier=None,
            fixed_reversal=converted,
            research_eligible=False,
        )


@dataclass(frozen=True, slots=True)
class DegreeProfile:
    degree_key: str
    degree_version: str
    detector_profile_key: str
    grammar_profile_version: str
    max_history_pivots: int = 24
    max_start_candidates: int = 8
    max_scenarios: int = 5
    progression_horizon_bars: int = 20

    def __post_init__(self) -> None:
        if (
            min(
                self.max_history_pivots,
                self.max_start_candidates,
                self.max_scenarios,
                self.progression_horizon_bars,
            )
            <= 0
        ):
            raise ValueError("degree profile limits must be positive")
        validate_generic_profile_payload(
            {
                field_name: getattr(self, field_name)
                for field_name in self.__dataclass_fields__
            }
        )


def validate_generic_profile_payload(payload: object) -> None:
    """Keep special four-wave vocabulary out of the generic engine contract."""

    def strings(value: object):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield str(key)
                yield from strings(item)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                yield from strings(item)

    for rendered in strings(payload):
        tokens = {token.upper() for token in rendered.replace("-", "_").split("_")}
        upper = rendered.upper()
        if "MACD_7_52_7" in upper or any(
            marker in tokens for marker in {"P0", "P1", "P2", "P3"}
        ):
            raise ValueError(
                f"generic profile contains forbidden special marker: {rendered}"
            )


CAUSAL_ATR_PROFILE = DetectorProfile(
    detector_key="CAUSAL_ATR_ZIGZAG",
    detector_version="CAUSAL_ATR_ZIGZAG_V1",
    detector_profile_key="CAUSAL_ATR14_1P5_V1",
    atr_period=14,
    atr_seed_method="ARITHMETIC_MEAN_FIRST_N_TR",
    atr_smoothing="WILDER_RMA",
    atr_multiplier=Decimal("1.5"),
    fixed_reversal=None,
)

BASE_DEGREE_PROFILE = DegreeProfile(
    degree_key="BASE_ATR14_1P5_V1",
    degree_version="DEGREE_PROFILE_V1",
    detector_profile_key=CAUSAL_ATR_PROFILE.detector_profile_key,
    grammar_profile_version="GRAMMAR_PROFILE_V1",
)
