from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DatasetCadence = Literal["reference", "daily", "weekly", "monthly", "event"]


@dataclass(frozen=True, slots=True)
class DatasetFreshnessSpec:
    dataset_key: str
    resource_key: str
    display_name: str
    domain_key: str
    domain_display_name: str
    target_table: str
    cadence: DatasetCadence
    raw_table: str | None = None
    observed_date_column: str | None = None
    primary_action_key: str | None = None
