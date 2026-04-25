from __future__ import annotations

from src.foundation.datasets.models import (
    DatasetActionCapability,
    DatasetCapabilities,
    DatasetDefinition,
    DatasetDomain,
    DatasetIdentity,
    DatasetInputField,
    DatasetInputModel,
    DatasetNormalizationDefinition,
    DatasetObservability,
    DatasetPlanningDefinition,
    DatasetQualityPolicy,
    DatasetSourceDefinition,
    DatasetStorageDefinition,
)
from src.foundation.services.sync_v2.contracts import DatasetSyncContract, InputField
from src.foundation.services.sync_v2.registry_parts.assemble import DOMAIN_CONTRACT_GROUPS


TIME_FIELD_NAMES = frozenset(
    {
        "trade_date",
        "start_date",
        "end_date",
        "ann_date",
        "month",
        "start_month",
        "end_month",
    }
)

DOMAIN_META = {
    "market_equity": ("equity_market", "股票行情", "daily"),
    "market_fund": ("index_fund", "指数 / ETF", "daily"),
    "index_series": ("index_fund", "指数 / ETF", "daily"),
    "board_hotspot": ("board_theme", "板块 / 题材", "daily"),
    "moneyflow": ("moneyflow", "资金流向", "daily"),
    "reference_master": ("reference_data", "基础主数据", "snapshot"),
    "low_frequency": ("low_frequency", "低频数据", "low_frequency"),
}

DISPLAY_NAME_OVERRIDES = {
    "daily": "股票日线",
    "index_weekly": "指数周线",
    "index_monthly": "指数月线",
    "stock_basic": "股票主数据",
}


def list_dataset_definitions() -> tuple[DatasetDefinition, ...]:
    definitions: list[DatasetDefinition] = []
    for domain_group_key, contracts in DOMAIN_CONTRACT_GROUPS.items():
        for contract in contracts.values():
            definitions.append(_from_contract(domain_group_key, contract))
    return tuple(sorted(definitions, key=lambda item: item.dataset_key))


def get_dataset_definition(dataset_key: str) -> DatasetDefinition:
    for definition in list_dataset_definitions():
        if definition.dataset_key == dataset_key:
            return definition
    raise KeyError(f"dataset definition not found for dataset={dataset_key}")


def _from_contract(domain_group_key: str, contract: DatasetSyncContract) -> DatasetDefinition:
    domain_key, domain_display_name, cadence = DOMAIN_META.get(domain_group_key, ("other", "其他", "unknown"))
    display_name = DISPLAY_NAME_OVERRIDES.get(contract.dataset_key, contract.display_name)
    filter_fields = tuple(_input_field(field, contract=contract) for field in contract.input_schema.fields if field.name not in TIME_FIELD_NAMES)
    time_fields = tuple(_input_field(field, contract=contract) for field in contract.input_schema.fields if field.name in TIME_FIELD_NAMES)
    row_transform = contract.normalization_spec.row_transform
    return DatasetDefinition(
        identity=DatasetIdentity(
            dataset_key=contract.dataset_key,
            display_name=display_name,
            description=f"维护{display_name}数据。",
            aliases=(contract.job_name,),
        ),
        domain=DatasetDomain(
            domain_key=domain_key,
            domain_display_name=domain_display_name,
            cadence=cadence,
        ),
        source=DatasetSourceDefinition(
            source_key_default=contract.source_spec.source_key_default,
            adapter_key=contract.source_adapter_key,
            api_name=contract.source_spec.api_name,
            source_fields=contract.source_spec.fields,
            source_doc_id=f"{contract.source_spec.source_key_default}.{contract.source_spec.api_name}",
        ),
        date_model=contract.date_model,
        input_model=DatasetInputModel(
            time_fields=time_fields,
            filters=filter_fields,
            required_groups=contract.input_schema.required_groups,
            mutually_exclusive_groups=contract.input_schema.mutually_exclusive_groups,
            dependencies=contract.input_schema.dependencies,
        ),
        storage=DatasetStorageDefinition(
            raw_dao_name=contract.write_spec.raw_dao_name,
            core_dao_name=contract.write_spec.core_dao_name,
            target_table=contract.write_spec.target_table,
            conflict_columns=contract.write_spec.conflict_columns,
            write_path=contract.write_spec.write_path,
        ),
        planning=DatasetPlanningDefinition(
            universe_policy=contract.planning_spec.universe_policy,
            enum_fanout_fields=contract.planning_spec.enum_fanout_fields,
            enum_fanout_defaults=contract.planning_spec.enum_fanout_defaults,
            pagination_policy=contract.planning_spec.pagination_policy,
            chunk_size=contract.planning_spec.chunk_size,
            max_units_per_execution=contract.planning_spec.max_units_per_execution,
        ),
        normalization=DatasetNormalizationDefinition(
            date_fields=contract.normalization_spec.date_fields,
            decimal_fields=contract.normalization_spec.decimal_fields,
            required_fields=contract.normalization_spec.required_fields,
            row_transform_name=getattr(row_transform, "__name__", None) if row_transform is not None else None,
        ),
        capabilities=DatasetCapabilities(
            actions=(
                DatasetActionCapability(
                    action="maintain",
                    manual_enabled=True,
                    schedule_enabled=True,
                    retry_enabled=True,
                    supported_time_modes=_time_modes(contract),
                ),
            )
        ),
        observability=DatasetObservability(
            progress_label=contract.observe_spec.progress_label,
            observed_field=contract.date_model.observed_field,
            audit_applicable=contract.date_model.audit_applicable,
        ),
        quality=DatasetQualityPolicy(
            required_fields=contract.normalization_spec.required_fields,
        ),
    )


def _input_field(field: InputField, *, contract: DatasetSyncContract) -> DatasetInputField:
    enum_values = field.enum_values
    if not enum_values:
        enum_values = contract.planning_spec.enum_fanout_defaults.get(field.name, ())
    return DatasetInputField(
        name=field.name,
        field_type=field.field_type,
        required=field.required,
        default=field.default,
        enum_values=enum_values,
        multi_value=field.field_type == "list" and not (field.name == "is_new" and len(enum_values) == 1),
        description=field.description,
    )


def _time_modes(contract: DatasetSyncContract) -> tuple[str, ...]:
    window_mode = contract.date_model.window_mode
    supported_profiles = set(contract.run_profiles_supported)
    if window_mode == "none" or "snapshot_refresh" in supported_profiles and not {"point_incremental", "range_rebuild"} & supported_profiles:
        return ("none",)
    modes: list[str] = []
    if window_mode in {"point", "point_or_range"} and "point_incremental" in supported_profiles:
        modes.append("point")
    if window_mode in {"range", "point_or_range"} and "range_rebuild" in supported_profiles:
        modes.append("range")
    if window_mode == "none":
        modes.append("none")
    return tuple(modes or ("none",))
