import dagster as dg

from orchestrator.defs.assets.stock_return_distribution import gold_stock_return_distribution
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)


stock_return_distribution_automation_sensor = dg.AutomationConditionSensorDefinition(
    name="stock_return_distribution_automation_sensor",
    target=dg.AssetSelection.assets(gold_stock_return_distribution),
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.DERIVED_METRIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.AUTOMATION_CONDITION,
    ),
    description="股票涨跌幅区间分布在直接上游检查通过后，触发生成任务。",
    emit_backfills=True,
    use_user_code_server=False,
)
