from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from orchestrator.defs.partitions import cn_a_stock_trade_days, cn_a_stock_week_ends
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    raw_stk_period_bar_adj_week_path,
    raw_stk_period_bar_week_path,
    raw_tushare_weekly_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA,
    RAW_STK_PERIOD_BAR_WEEK_SCHEMA,
    RAW_TUSHARE_WEEKLY_SCHEMA,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    WeeklyBudget,
    normalize_week_key,
    weekly_key_columns,
    weekly_required_columns,
    weekly_schema_hash,
)


def test_source_columns_match_real_13_21_11_contracts():
    assert [x.name for x in RAW_STK_PERIOD_BAR_WEEK_SCHEMA] == [
        "ts_code",
        "trade_date",
        "end_date",
        "freq",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "vol",
        "amount",
        "change",
        "pct_chg",
    ]
    assert [x.name for x in RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA] == [
        "ts_code",
        "trade_date",
        "end_date",
        "freq",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "open_qfq",
        "high_qfq",
        "low_qfq",
        "close_qfq",
        "open_hfq",
        "high_hfq",
        "low_hfq",
        "close_hfq",
        "vol",
        "amount",
        "change",
        "pct_chg",
    ]
    assert [x.name for x in RAW_TUSHARE_WEEKLY_SCHEMA] == [
        "ts_code",
        "trade_date",
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ]
    for schema in (
        RAW_STK_PERIOD_BAR_WEEK_SCHEMA,
        RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA,
        RAW_TUSHARE_WEEKLY_SCHEMA,
    ):
        assert not {x.name for x in schema} & {
            "api_name",
            "fetched_at",
            "raw_payload",
            "week_end",
        }
        assert next(x.type for x in schema if x.name == "trade_date") == "VARCHAR"
    types = {x.name: x.type for x in RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA}
    assert types["close_qfq"] == "DECIMAL(18,4)"
    assert types["vol"] == "DECIMAL(20,4)"
    assert types["pct_chg"] == "DECIMAL(10,4)"
    assert all(x.type == "DOUBLE" for x in RAW_TUSHARE_WEEKLY_SCHEMA[2:])
    assert len({weekly_schema_hash(x) for x in StockWeeklySource}) == 3


@pytest.mark.parametrize(
    "key", ["20260925", "2026-09-24", "2026-02-30", "../2026-09-25", True]
)
def test_invalid_partition_dates_rejected(key):
    with pytest.raises(ValueError):
        normalize_week_key(key)


def test_holiday_friday_and_paths_are_independent_and_pure(tmp_path):
    key = "2026-09-25"
    assert normalize_week_key(key) == key
    paths = [
        fn(tmp_path, key)
        for fn in (
            raw_stk_period_bar_week_path,
            raw_stk_period_bar_adj_week_path,
            raw_tushare_weekly_path,
        )
    ]
    assert len(set(paths)) == 3
    assert all(
        x.name == "part-000.parquet" and x.parent.name == f"week_end={key}"
        for x in paths
    )
    assert not list(tmp_path.iterdir())
    assert cn_a_stock_week_ends.name == "cn_a_stock_week_ends"
    assert cn_a_stock_week_ends.name != cn_a_stock_trade_days.name
    assert PATH_TEMPLATE_PARTITION_KEY in str(
        raw_tushare_weekly_path(
            Path(PATH_TEMPLATE_LAKE_ROOT), PATH_TEMPLATE_PARTITION_KEY
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"source_concurrency": 2},
        {"prod_max_connections": 2},
        {"minimum_interval_seconds": float("nan")},
        {"max_retries": True},
        {"fetch_batch_rows": 30_001},
        {"prod_statement_timeout_ms": 46_000},
        {"duckdb_memory_limit": "unlimited"},
        {"max_candidate_keys": 0},
    ],
)
def test_invalid_budget_cannot_be_frozen(changes):
    with pytest.raises(ValueError):
        WeeklyBudget(**changes)


def test_budget_is_immutable_and_unknown_settings_rejected():
    budget = WeeklyBudget()
    with pytest.raises(FrozenInstanceError):
        budget.max_retries = 99
    with pytest.raises(TypeError):
        WeeklyBudget(force=True)
    assert replace(budget, max_retries=0).max_retries == 0


def test_primary_null_values_and_alternate_requirements_do_not_share_policy():
    assert weekly_required_columns(StockWeeklySource.PRIMARY_ADJUSTED) == (
        "ts_code",
        "trade_date",
        "freq",
    )
    assert "close_qfq" not in weekly_required_columns(
        StockWeeklySource.PRIMARY_ADJUSTED
    )
    assert "close" in weekly_required_columns(StockWeeklySource.ALTERNATE_WEEKLY)
    assert "pre_close" not in weekly_required_columns(
        StockWeeklySource.ALTERNATE_WEEKLY
    )
    assert weekly_key_columns(StockWeeklySource.ALTERNATE_WEEKLY) == (
        "ts_code",
        "trade_date",
    )
