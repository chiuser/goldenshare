"""Fixed next-completed-bar policy; no user-selectable forecast strategy."""
from dataclasses import asdict, dataclass, fields
import hashlib
import json


@dataclass(frozen=True, slots=True)
class ForecastSpec:
    forecast_version: str = "xxm-key-point-forecast-v0.4-r4"
    scenario_policy: str = "next_completed_bar"
    target_selection: str = "near_range_before_far"
    max_future_bars: int = 1
    calibration_tail_bars: int = 250
    daily_calibration_abs_tol: float = 0.0005
    minute_calibration_abs_tol: float = 1e-8
    daily_rounding_guard: float = 1e-10
    display_policy: str = "valid_integer_boundaries"
    structure_text_places: int = 0
    forecast_compute_budget_ms: int = 400
    max_response_bytes: int = 32768
    future_calendar_days: int = 90
    refresh_after_ms: int = 60000

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not type(field.default) or value != field.default:
                raise ValueError("Formal r4 forecast rules are immutable")

    @property
    def spec_hash(self) -> str:
        # Preserve the forecast Spec's own canonical JSON convention.
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


FORECAST_SPEC = ForecastSpec()
