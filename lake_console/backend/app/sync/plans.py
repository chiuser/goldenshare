from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LakeSyncPlan:
    dataset_key: str
    display_name: str
    source: str
    api_name: str | None
    mode: str
    request_strategy_key: str
    request_count: int
    partition_count: int
    write_policy: str
    write_paths: tuple[str, ...]
    required_manifests: tuple[str, ...]
    parameters: dict[str, Any]
    notes: tuple[str, ...]
    estimate: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_key": self.dataset_key,
            "display_name": self.display_name,
            "source": self.source,
            "api_name": self.api_name,
            "mode": self.mode,
            "request_strategy_key": self.request_strategy_key,
            "request_count": self.request_count,
            "partition_count": self.partition_count,
            "write_policy": self.write_policy,
            "write_paths": list(self.write_paths),
            "required_manifests": list(self.required_manifests),
            "parameters": self.parameters,
            "notes": list(self.notes),
            "estimate": self.estimate,
        }
