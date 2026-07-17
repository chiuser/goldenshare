CREATE TABLE IF NOT EXISTS goldenshare_serving.board_fact_technical_daily
(
    ts_code LowCardinality(String),
    trade_date Date,
    category LowCardinality(String),
    close Float64,
    ma_5 Nullable(Float64),
    ma_10 Nullable(Float64),
    ma_15 Nullable(Float64),
    ma_20 Nullable(Float64),
    ma_30 Nullable(Float64),
    ma_60 Nullable(Float64),
    ma_120 Nullable(Float64),
    ma_250 Nullable(Float64),
    kdj_k Float64,
    kdj_d Float64,
    kdj_j Float64,
    macd_dif Float64,
    macd_dea Float64,
    macd Float64,
    boll_mid Nullable(Float64),
    boll_upper Nullable(Float64),
    boll_lower Nullable(Float64),
    observation_count UInt32,
    params_key LowCardinality(String),
    indicator_version LowCardinality(String),
    updated_at DateTime
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_date)
ORDER BY (trade_date, category, ts_code);
