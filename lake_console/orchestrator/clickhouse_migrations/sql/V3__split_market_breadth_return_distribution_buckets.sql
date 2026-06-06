ALTER TABLE goldenshare_serving.share_fact_market_breadth_daily
    RENAME COLUMN down_gt_7_count TO down_7_10_count;

ALTER TABLE goldenshare_serving.share_fact_market_breadth_daily
    RENAME COLUMN up_gt_7_count TO up_7_10_count;

ALTER TABLE goldenshare_serving.share_fact_market_breadth_daily
    ADD COLUMN down_gt_10_count UInt32 AFTER red_rate;

ALTER TABLE goldenshare_serving.share_fact_market_breadth_daily
    ADD COLUMN up_gt_10_count UInt32 AFTER up_7_10_count;
