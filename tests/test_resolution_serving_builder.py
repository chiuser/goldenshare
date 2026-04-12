from __future__ import annotations

from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.serving.builders.equity_daily_bar_serving_builder import EquityDailyBarServingBuilder


def test_resolution_serving_builder_uses_composite_business_key_and_policy() -> None:
    builder = EquityDailyBarServingBuilder()
    policy = ResolutionPolicy(
        dataset_key="equity_daily_bar",
        mode="primary",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
        version=2,
    )
    result = builder.build_rows(
        std_rows_by_source={
            "tushare": [
                {"source_key": "tushare", "ts_code": "000001.SZ", "trade_date": "2026-04-10", "close": 12.3}
            ],
            "biying": [
                {"source_key": "biying", "ts_code": "000001.SZ", "trade_date": "2026-04-10", "close": 99.9}
            ],
        },
        policy=policy,
        active_sources={"tushare", "biying"},
        target_columns={
            "ts_code",
            "trade_date",
            "close",
            "source",
            "resolution_mode",
            "resolution_policy_version",
            "candidate_sources",
        },
    )

    assert result.resolved_count == 1
    row = result.rows[0]
    assert row["ts_code"] == "000001.SZ"
    assert row["trade_date"] == "2026-04-10"
    assert row["close"] == 12.3
    assert row["source"] == "tushare"
    assert row["resolution_mode"] == "primary"
    assert row["resolution_policy_version"] == 2
    assert row["candidate_sources"] == "biying,tushare"


def test_resolution_serving_builder_skips_row_when_business_key_incomplete() -> None:
    builder = EquityDailyBarServingBuilder()
    policy = ResolutionPolicy(
        dataset_key="equity_daily_bar",
        mode="primary",
        primary_source_key="tushare",
    )
    result = builder.build_rows(
        std_rows_by_source={
            "tushare": [
                {"source_key": "tushare", "ts_code": "000001.SZ", "trade_date": "2026-04-10", "close": 12.3},
                {"source_key": "tushare", "ts_code": "000002.SZ", "close": 8.1},
            ]
        },
        policy=policy,
        active_sources={"tushare"},
        target_columns={"ts_code", "trade_date", "close", "source"},
    )

    assert result.resolved_count == 1
    assert len(result.rows) == 1
    assert result.rows[0]["ts_code"] == "000001.SZ"
