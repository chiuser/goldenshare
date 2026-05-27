import dagster as dg

from orchestrator.defs.assets.stock_return_distribution import gold_stock_return_distribution


stock_return_distribution_automation_sensor = dg.AutomationConditionSensorDefinition(
    name="stock_return_distribution_automation_sensor",
    target=dg.AssetSelection.assets(gold_stock_return_distribution),
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    description="股票涨跌幅区间分布在直接上游检查通过后，触发生成任务。",
    emit_backfills=True,
    use_user_code_server=False,
)
