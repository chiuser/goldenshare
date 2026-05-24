import dagster as dg

# Full SSE open-day backup partition set. Production daily assets should use
# their asset-family-specific partition definitions below.
cn_a_trade_days = dg.DynamicPartitionsDefinition(name="cn_a_trade_days")
cn_a_stock_trade_days = dg.DynamicPartitionsDefinition(name="cn_a_stock_trade_days")
cn_a_index_trade_days = dg.DynamicPartitionsDefinition(name="cn_a_index_trade_days")
