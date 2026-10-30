from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json


@dataclass(frozen=True, slots=True)
class XxmSpec:
    algorithm_version: str = "xxm-direction-v0.2-r4"
    dif_turn_pct: float = 1.0
    max_refs: int = 2
    min_bars: int = 2
    reference_policy: str = "nearest_then_farther_two"
    active_reference_policy: str = "same_bar_near_to_far_on_dull_break"
    zero_policy: str = "neutral_real_opposite"
    allow_zero_activation: bool = True
    activation_policy: str = "current_close_and_current_dif"
    reference_break_policy: str = "strict_break_within_current_segment"
    structure_return_policy: str = "adjacent_one_percent_to_dull"
    structure_lock_policy: str = "first_valid_opposite_color"
    historical_min_bars: int = 1
    top_activation_requires_positive_dif: bool = True
    macd_parameters: tuple[int, int, int] = (12, 26, 9)
    histogram_multiplier: int = 2
    color_flip: bool = True
    flip_requires_turn: bool = False

    def __post_init__(self) -> None:
        for field in fields(self):
            value, expected = getattr(self, field.name), field.default
            if (type(value) is not type(expected) or value != expected
                    or (type(expected) is tuple and any(
                        type(item) is not type(default) for item, default in zip(value, expected)))):
                raise ValueError("Formal r4 rules are immutable")

    @property
    def spec_hash(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


MAIN_SPEC = XxmSpec()
