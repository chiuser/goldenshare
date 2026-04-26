from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class DatasetDateModel:
    date_axis: str
    bucket_rule: str
    window_mode: str
    input_shape: str
    observed_field: str | None
    audit_applicable: bool
    not_applicable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetIdentity:
    dataset_key: str
    display_name: str
    description: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DatasetDomain:
    domain_key: str
    domain_display_name: str
    cadence: str


@dataclass(frozen=True, slots=True)
class DatasetSourceDefinition:
    source_key_default: str
    adapter_key: str
    api_name: str
    source_fields: tuple[str, ...]
    source_doc_id: str | None = None
    request_builder_key: str = "generic"
    base_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DatasetInputField:
    name: str
    field_type: str
    required: bool = False
    default: Any = None
    enum_values: tuple[str, ...] = ()
    multi_value: bool = False
    display_name: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class DatasetInputModel:
    time_fields: tuple[DatasetInputField, ...] = ()
    filters: tuple[DatasetInputField, ...] = ()
    required_groups: tuple[tuple[str, ...], ...] = ()
    mutually_exclusive_groups: tuple[tuple[str, ...], ...] = ()
    dependencies: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class DatasetStorageDefinition:
    raw_dao_name: str
    core_dao_name: str
    target_table: str
    conflict_columns: tuple[str, ...] | None = None
    write_path: str = "raw_core_upsert"


@dataclass(frozen=True, slots=True)
class DatasetPlanningDefinition:
    universe_policy: str = "none"
    enum_fanout_fields: tuple[str, ...] = ()
    enum_fanout_defaults: dict[str, tuple[str, ...]] = field(default_factory=dict)
    pagination_policy: str = "none"
    page_limit: int | None = None
    chunk_size: int | None = None
    max_units_per_execution: int | None = None
    unit_builder_key: str = "generic"


@dataclass(frozen=True, slots=True)
class DatasetNormalizationDefinition:
    date_fields: tuple[str, ...] = ()
    decimal_fields: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    row_transform_name: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetObservability:
    progress_label: str
    observed_field: str | None
    audit_applicable: bool


@dataclass(frozen=True, slots=True)
class DatasetQualityPolicy:
    reject_policy: str = "record_rejections"
    required_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DatasetTransactionDefinition:
    commit_policy: str = "task"
    idempotent_write_required: bool = False
    write_volume_assessment: str = ""


@dataclass(frozen=True, slots=True)
class DatasetActionCapability:
    action: str
    manual_enabled: bool
    schedule_enabled: bool
    retry_enabled: bool
    supported_time_modes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DatasetCapabilities:
    actions: tuple[DatasetActionCapability, ...]

    def get_action(self, action: str) -> DatasetActionCapability | None:
        return next((item for item in self.actions if item.action == action), None)


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    identity: DatasetIdentity
    domain: DatasetDomain
    source: DatasetSourceDefinition
    date_model: DatasetDateModel
    input_model: DatasetInputModel
    storage: DatasetStorageDefinition
    planning: DatasetPlanningDefinition
    normalization: DatasetNormalizationDefinition
    capabilities: DatasetCapabilities
    observability: DatasetObservability
    quality: DatasetQualityPolicy
    transaction: DatasetTransactionDefinition

    @property
    def dataset_key(self) -> str:
        return self.identity.dataset_key

    @property
    def display_name(self) -> str:
        return self.identity.display_name
