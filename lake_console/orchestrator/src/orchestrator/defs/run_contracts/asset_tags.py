"""Asset tag keys, values, and builders for Goldenshare Dagster assets."""

from enum import Enum


ASSET_LAYER_TAG = "goldenshare/layer"
DATA_DOMAIN_TAG = "goldenshare/data_domain"


class AssetLayer(str, Enum):
    RAW = "raw"
    SILVER = "silver"
    GOLD = "gold"


class DataDomain(str, Enum):
    BASIC_DATA = "basic_data"
    QUOTE_DATA = "quote_data"
    INDEX_TOPIC = "index_topic"
    PROJECT_CONFIG = "project_config"
    DERIVED_METRIC = "derived_metric"


def _coerce_asset_layer(layer: AssetLayer | str) -> AssetLayer:
    if isinstance(layer, AssetLayer):
        return layer
    return AssetLayer(layer)


def _coerce_data_domain(data_domain: DataDomain | str) -> DataDomain:
    if isinstance(data_domain, DataDomain):
        return data_domain
    return DataDomain(data_domain)


def build_asset_tags(
    *,
    layer: AssetLayer | str,
    data_domain: DataDomain | str,
) -> dict[str, str]:
    """Build the approved low-cardinality asset tags for a lake asset."""

    return {
        ASSET_LAYER_TAG: _coerce_asset_layer(layer).value,
        DATA_DOMAIN_TAG: _coerce_data_domain(data_domain).value,
    }
