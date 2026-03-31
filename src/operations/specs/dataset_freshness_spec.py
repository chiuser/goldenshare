from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DatasetCadence = Literal["reference", "daily", "weekly", "monthly", "event"]


@dataclass(frozen=True, slots=True)
class DatasetFreshnessSpec:
    dataset_key: str
    resource_key: str
    job_name: str
    display_name: str
    domain_key: str
    domain_display_name: str
    target_table: str
    cadence: DatasetCadence
    observed_date_column: str | None = None
    primary_execution_spec_key: str | None = None
