from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json


@dataclass(frozen=True, slots=True)
class XxmSpec:
    algorithm_version: str = "xxm-direction-v0.1-r2"
    dif_turn_pct: float = 1.0
    max_refs: int = 2
    min_bars: int = 2
    reference_policy: str = "strongest_eligible"
    macd_parameters: tuple[int, int, int] = (12, 26, 9)
    histogram_multiplier: int = 2
    color_flip: bool = True
    flip_requires_turn: bool = False
    historical_price_only: bool = True
    fixed_expiry: None = None
    bottom_history_policy: str = "closed_origin_close_break_v1"
    same_segment_bottom_policy: str = "current_close_rearm_v1"
    bottom_dull_reference_policy: str = "prebreak_strongest_eligible_v1"

    def __post_init__(self) -> None:
        if self.dif_turn_pct not in (0.75, 1.0, 1.2):
            raise ValueError("Only the three frozen research gates are supported")
        baseline = {field.name: field.default for field in fields(self)}
        baseline["dif_turn_pct"] = self.dif_turn_pct
        if asdict(self) != baseline:
            raise ValueError("V0.1 settings are immutable")

    @property
    def spec_hash(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


MAIN_SPEC = XxmSpec()
