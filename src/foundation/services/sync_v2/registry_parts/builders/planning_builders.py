from __future__ import annotations

from src.foundation.services.sync_v2.contracts import PlanningSpec

def build_planning_spec(**kwargs) -> PlanningSpec:  # type: ignore[no-untyped-def]
    return PlanningSpec(**kwargs)
