from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json


@dataclass(frozen=True, slots=True)
class XxmSpec:
    algorithm_version: str = "xxm-direction-v0.1-r4"
    dif_turn_pct: float = 1.0
    max_refs: int = 2
    min_bars: int = 2
    reference_policy: str = "nearest_then_farther_two"
    active_reference_policy: str = "same_bar_near_to_far_on_dull_break"
    zero_policy: str = "neutral_real_opposite"
    allow_zero_activation: bool = True
    allow_zero_reactivation: bool = True
    macd_parameters: tuple[int, int, int] = (12, 26, 9)
    histogram_multiplier: int = 2
    color_flip: bool = True
    flip_requires_turn: bool = False
    historical_price_only: bool = True
    fixed_expiry: None = None
    bottom_history_policy: str = "closed_origin_close_break_v1"
    same_segment_bottom_policy: str = "current_close_rearm_v1"

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
