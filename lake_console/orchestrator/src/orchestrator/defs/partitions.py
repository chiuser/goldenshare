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
cn_a_index_mins_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_a_index_mins_trade_days"
)
cn_major_index_mins_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_major_index_mins_trade_days"
)
cn_major_index_factor_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_major_index_factor_trade_days"
)

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

# International index data uses natural-day partitions.  It must not reuse an
# SSE trading-day partition set because source publication follows multiple
# overseas markets and may legitimately produce an empty file.
cn_global_index_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_global_index_trade_days"
)
