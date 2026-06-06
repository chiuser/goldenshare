"""Catalog display helpers and read-only lake asset registry."""

from orchestrator.defs.catalog.name_mapping import (
    DATASET_CHINESE_NAMES,
    get_dataset_chinese_name,
)

__all__ = [
    "LAKE_ASSET_CATALOG",
    "PARTITION_MODEL_DEFINITIONS",
    "ComputeEngine",
    "DataContractSource",
    "DATASET_CHINESE_NAMES",
    "EventPolicy",
    "IngestionSource",
    "LakeAssetCatalogEntry",
    "LakeAssetPerformanceContract",
    "PartitionModel",
    "PartitionModelDefinition",
    "PartitionModelFamily",
    "PartitionPhysicalLayout",
    "WritePolicy",
    "get_lake_asset_catalog_entry",
    "get_dataset_chinese_name",
    "get_partition_model_definition",
    "list_lake_asset_catalog_entries",
    "list_lake_asset_entries_by_dataset_id",
    "list_lake_asset_keys",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(name)
    if name in {"DATASET_CHINESE_NAMES", "get_dataset_chinese_name"}:
        return globals()[name]

    from orchestrator.defs.catalog import lake_assets

    return getattr(lake_assets, name)
