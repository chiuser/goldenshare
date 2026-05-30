"""Sensor definition tag keys, values, and builders."""

from enum import Enum


SENSOR_DOMAIN_TAG = "goldenshare/sensor_domain"
SENSOR_TARGET_LAYER_TAG = "goldenshare/sensor_target_layer"
SENSOR_ROLE_TAG = "goldenshare/sensor_role"


class SensorDomain(str, Enum):
    BASIC_DATA = "basic_data"
    QUOTE_DATA = "quote_data"
    INDEX_TOPIC = "index_topic"
    DERIVED_METRIC = "derived_metric"
    PLATFORM_OBSERVABILITY = "platform_observability"


class SensorTargetLayer(str, Enum):
    PARTITION = "partition"
    RAW = "raw"
    SILVER = "silver"
    RAW_SILVER = "raw_silver"
    GOLD = "gold"
    SERVING = "serving"
    PLATFORM = "platform"


class SensorRole(str, Enum):
    PARTITION_REGISTRATION = "partition_registration"
    ASSET_UPDATE = "asset_update"
    AUTOMATION_CONDITION = "automation_condition"
    RUN_STATUS_NOTIFICATION = "run_status_notification"


def _coerce_sensor_domain(sensor_domain: SensorDomain | str) -> SensorDomain:
    if isinstance(sensor_domain, SensorDomain):
        return sensor_domain
    return SensorDomain(sensor_domain)


def _coerce_sensor_target_layer(
    target_layer: SensorTargetLayer | str,
) -> SensorTargetLayer:
    if isinstance(target_layer, SensorTargetLayer):
        return target_layer
    return SensorTargetLayer(target_layer)


def _coerce_sensor_role(role: SensorRole | str) -> SensorRole:
    if isinstance(role, SensorRole):
        return role
    return SensorRole(role)


def build_sensor_tags(
    *,
    sensor_domain: SensorDomain | str,
    target_layer: SensorTargetLayer | str,
    role: SensorRole | str,
) -> dict[str, str]:
    """Build the approved low-cardinality definition tags for a Dagster sensor."""

    return {
        SENSOR_DOMAIN_TAG: _coerce_sensor_domain(sensor_domain).value,
        SENSOR_TARGET_LAYER_TAG: _coerce_sensor_target_layer(target_layer).value,
        SENSOR_ROLE_TAG: _coerce_sensor_role(role).value,
    }
