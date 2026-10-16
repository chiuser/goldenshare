from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True)
class ForecastSpec:
    forecast_version: str = "xxm-key-point-forecast-v0.2-a1"
    scenario_policy: str = "entry_range_then_flat"
    target_selection: str = "nearest_feasible_over_entry_range"
    max_future_bars: int = 20
    calibration_tail_bars: int = 250
    daily_calibration_abs_tol: float = 0.0005
    minute_calibration_abs_tol: float = 1e-8
    daily_rounding_guard: float = 1e-10
    price_display_places: int = 2
    price_boundary_places: int = 4
    explanation_sample_count: int = 3
    display_policy: str = "near_term_conditions_v1"
    display_move_samples: int = 60
    display_move_quantile: float = 0.95
    structure_text_places: int = 0
    forecast_compute_budget_ms: int = 200
    max_response_bytes: int = 32768
    future_calendar_days: int = 90
    refresh_after_ms: int = 60000

    @property
    def spec_hash(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


FORECAST_SPEC = ForecastSpec()
