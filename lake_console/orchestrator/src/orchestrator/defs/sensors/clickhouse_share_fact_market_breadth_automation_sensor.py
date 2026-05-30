import dagster as dg

from orchestrator.defs.assets.clickhouse_serving import (
    ch_share_fact_market_breadth_daily,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)


clickhouse_share_fact_market_breadth_automation_sensor = (
    dg.AutomationConditionSensorDefinition(
        name="clickhouse_share_fact_market_breadth_automation_sensor",
        target=dg.AssetSelection.assets(ch_share_fact_market_breadth_daily),
        default_status=dg.DefaultSensorStatus.STOPPED,
        minimum_interval_seconds=600,
        tags=build_sensor_tags(
            sensor_domain=SensorDomain.DERIVED_METRIC,
            target_layer=SensorTargetLayer.SERVING,
            role=SensorRole.AUTOMATION_CONDITION,
        ),
        description="ClickHouse 市场宽度 serving 在直接上游检查通过后，触发同步任务。",
        emit_backfills=True,
        use_user_code_server=False,
    )
)
