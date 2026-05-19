import dagster as dg

cn_a_trade_days = dg.DynamicPartitionsDefinition(name="cn_a_trade_days")
