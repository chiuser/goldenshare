from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.bootstrap.source_method import BootstrapSourceMethod
from orchestrator.defs.paths import RAW


PARTITION_TYPES = {"full", "trade_date"}
EMPTY_POLICIES = {"allow_empty", "require_positive"}


@dataclass(frozen=True)
class BootstrapDatasetSpec:
    dataset_key: str
    layer: str
    old_lake_path_pattern: str
    target_path_pattern: str
    partition_type: str
    source_fields: tuple[str, ...]
    target_raw_fields: tuple[str, ...]
    select_sql_template: str
    empty_policy: str
    business_key: tuple[str, ...]
    source_method_metadata: str = BootstrapSourceMethod.OLD_LAKE_BOOTSTRAP.value

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_fields", tuple(self.source_fields))
        object.__setattr__(self, "target_raw_fields", tuple(self.target_raw_fields))
        object.__setattr__(self, "business_key", tuple(self.business_key))

        if not self.dataset_key:
            raise ValueError("Bootstrap dataset_key is required.")
        if self.layer != RAW:
            raise ValueError("BootstrapDatasetSpec only supports raw layer targets.")
        if self.partition_type not in PARTITION_TYPES:
            raise ValueError(f"Unsupported bootstrap partition_type: {self.partition_type}")
        if self.empty_policy not in EMPTY_POLICIES:
            raise ValueError(f"Unsupported bootstrap empty_policy: {self.empty_policy}")
        if self.source_method_metadata != BootstrapSourceMethod.OLD_LAKE_BOOTSTRAP.value:
            raise ValueError("Bootstrap source_method_metadata must be old_lake_bootstrap.")
        if not self.old_lake_path_pattern:
            raise ValueError("Bootstrap old_lake_path_pattern is required.")
        if not self.target_path_pattern:
            raise ValueError("Bootstrap target_path_pattern is required.")
        if not self.source_fields:
            raise ValueError("Bootstrap source_fields must not be empty.")
        if not self.target_raw_fields:
            raise ValueError("Bootstrap target_raw_fields must not be empty.")
        if not self.select_sql_template:
            raise ValueError("Bootstrap select_sql_template is required.")

    def source_path(self, partition_key: str | None = None) -> Path:
        return Path(self._render_path(self.old_lake_path_pattern, partition_key))

    def target_path(self, partition_key: str | None = None) -> Path:
        return Path(self._render_path(self.target_path_pattern, partition_key))

    @staticmethod
    def _render_path(pattern: str, partition_key: str | None) -> str:
        return pattern.format(partition_key=partition_key or "")
