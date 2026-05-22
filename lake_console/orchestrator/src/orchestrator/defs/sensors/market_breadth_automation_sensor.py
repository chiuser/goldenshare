import dagster as dg

from orchestrator.defs.assets.market_breadth import gold_market_breadth_daily


market_breadth_automation_sensor = dg.AutomationConditionSensorDefinition(
    name="market_breadth_automation_sensor",
    target=dg.AssetSelection.assets(gold_market_breadth_daily),
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    run_tags={
        "trigger": "automation_condition",
        "asset_family": "market_breadth",
    },
    description="Evaluate market breadth declarative automation only.",
    emit_backfills=True,
    use_user_code_server=False,
)
