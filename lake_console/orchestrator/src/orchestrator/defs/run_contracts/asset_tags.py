"""Asset tag keys, values, and builders for Goldenshare Dagster assets."""

from enum import Enum


ASSET_LAYER_TAG = "goldenshare/layer"
DATA_DOMAIN_TAG = "goldenshare/data_domain"


class AssetLayer(str, Enum):
    RAW = "原始层"
    SILVER = "标准层"
    GOLD = "正式层"


class DataDomain(str, Enum):
    BASIC = "基础数据"
    QUOTE = "行情数据"
    INDEX = "指数专题"
    PROJECT_CONFIG = "项目配置"
    DERIVED_METRIC = "衍生指标"


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
