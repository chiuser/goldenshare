import dagster as dg

from orchestrator.defs.assets.market_breadth import gold_market_breadth_daily


market_breadth_automation_sensor = dg.AutomationConditionSensorDefinition(
    name="market_breadth_automation_sensor",
    target=dg.AssetSelection.assets(gold_market_breadth_daily),
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    description="市场涨跌分布缺失且上游检查通过时，触发生成任务。",
    emit_backfills=True,
    use_user_code_server=False,
)
