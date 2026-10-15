"""Retained 21-field weekly contract and rejected retired identities."""

from pathlib import Path
import pytest
from orchestrator.defs.paths import raw_stk_period_bar_adj_week_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_dataset_id,
    weekly_key_columns,
    weekly_schema_hash,
    normalize_week_key,
)


def test_retained_schema_and_path_are_unchanged():
    schema = RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA
    assert [x.name for x in schema] == [
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
    types = {x.name: x.type for x in schema}
    assert (
        types["close_qfq"] == "DECIMAL(18,4)"
        and types["vol"] == "DECIMAL(20,4)"
        and types["pct_chg"] == "DECIMAL(10,4)"
    )
    assert weekly_key_columns(StockWeeklySource.PRIMARY_ADJUSTED) == (
        "ts_code",
        "trade_date",
        "freq",
    )
    assert raw_stk_period_bar_adj_week_path(
        Path("/private/tmp/lake"), "2026-10-09"
    ) == Path(
        "/private/tmp/lake/raw/tushare/stk_period_bar_adj_week/week_end=2026-10-09/part-000.parquet"
    )


@pytest.mark.parametrize("source", ["primary_unadjusted", "weekly", "unknown"])
def test_retired_source_cannot_resolve_schema_or_target(source):
    for resolve in (StockWeeklySource, weekly_dataset_id, weekly_schema_hash):
        with pytest.raises(ValueError):
            resolve(source)


@pytest.mark.parametrize("value", ["2026-10-08", "20261009", "２０２６-１０-０９"])
def test_invalid_week_coordinate_rejected(value):
    with pytest.raises(ValueError):
        normalize_week_key(value)
