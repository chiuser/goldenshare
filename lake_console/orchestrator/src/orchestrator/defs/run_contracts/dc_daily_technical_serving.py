"""Shared contract for the ``gold_dc_daily_technical`` ClickHouse serving copy."""

from __future__ import annotations

from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
)


DC_DAILY_TECHNICAL_SERVING_TABLE = (
    "goldenshare_serving.board_fact_technical_daily"
)
CH_DC_DAILY_TECHNICAL_CHECKS = ("ch_dc_daily_technical_core_check",)
PROD_CH_DC_DAILY_TECHNICAL_CHECKS = (
    "prod_ch_dc_daily_technical_core_check",
)
DC_DAILY_TECHNICAL_SERVING_PARTITION_SET = "cn_a_dc_daily_trade_days"
DC_DAILY_TECHNICAL_SERVING_WINDOW_LIMIT = 10

# Keep this order derived from the lake contract. Serving, checks, and bootstrap
# must not maintain independent column lists that can drift apart.
DC_DAILY_TECHNICAL_SERVING_COLUMNS = tuple(
    column.name for column in GOLD_DC_DAILY_TECHNICAL_SCHEMA
)
DC_DAILY_TECHNICAL_SERVING_INSERT_COLUMNS = (
    *DC_DAILY_TECHNICAL_SERVING_COLUMNS,
    "updated_at",
)

DC_DAILY_TECHNICAL_SERVING_KEY_COLUMNS = (
    "ts_code",
    "trade_date",
    "category",
)
DC_DAILY_TECHNICAL_SERVING_NULLABLE_COLUMNS = (
    "ma_5",
    "ma_10",
    "ma_15",
    "ma_20",
    "ma_30",
    "ma_60",
    "ma_120",
    "ma_250",
    "boll_mid",
    "boll_upper",
    "boll_lower",
)
