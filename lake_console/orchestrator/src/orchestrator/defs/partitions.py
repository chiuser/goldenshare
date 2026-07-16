import dagster as dg

# Full SSE open-day backup partition set. Production daily assets should use
# their asset-family-specific partition definitions below.
cn_a_trade_days = dg.DynamicPartitionsDefinition(name="cn_a_trade_days")
cn_a_stock_trade_days = dg.DynamicPartitionsDefinition(name="cn_a_stock_trade_days")
cn_a_stk_nineturn_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_a_stk_nineturn_trade_days"
)
cn_a_stock_current_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_a_stock_current_trade_days"
)
cn_a_stock_mins_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_a_stock_mins_trade_days"
)
cn_a_stock_mins_silver_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_a_stock_mins_silver_trade_days"
)
cn_a_index_trade_days = dg.DynamicPartitionsDefinition(name="cn_a_index_trade_days")
cn_a_index_ts_codes = dg.DynamicPartitionsDefinition(name="cn_a_index_ts_codes")

# Dedicated board-data partition sets.  They intentionally do not reuse the
# broader index partition set: the three source domains have different
# history starts and must be registered independently of source availability.
cn_a_dc_index_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_a_dc_index_trade_days"
)
cn_a_dc_member_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_a_dc_member_trade_days"
)
cn_a_dc_daily_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_a_dc_daily_trade_days"
)
