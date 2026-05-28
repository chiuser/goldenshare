CREATE TABLE IF NOT EXISTS goldenshare_serving.share_fact_market_breadth_daily
(
    trade_date Date,
    up_count UInt32,
    down_count UInt32,
    flat_count UInt32,
    total_count UInt32,
    red_rate Float64,
    down_gt_7_count UInt32,
    down_5_7_count UInt32,
    down_3_5_count UInt32,
    down_0_3_count UInt32,
    up_0_3_count UInt32,
    up_3_5_count UInt32,
    up_5_7_count UInt32,
    up_gt_7_count UInt32,
    updated_at DateTime
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_date)
ORDER BY trade_date;
