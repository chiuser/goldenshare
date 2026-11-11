from __future__ import annotations

from sqlalchemy.orm import Session

from src.foundation.dao.factory import DAOFactory
from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.serving.builders.index_daily_serving_builder import IndexDailyServingBuilder
from src.foundation.serving.publish_service import ServingPublishService
from src.foundation.serving.validation import validate_serving_coverage


def test_index_daily_still_resolves_by_code_and_date() -> None:
    builder = IndexDailyServingBuilder()
    policy = ResolutionPolicy(dataset_key="index_daily", mode="primary", primary_source_key="tushare")
    result = builder.build_rows(
        std_rows_by_source={
            "tushare": [{"source_key": "tushare", "ts_code": "000001.SH", "trade_date": "2026-04-10", "close": 3310.2}]
        },
        policy=policy,
        active_sources={"tushare"},
        target_columns={"ts_code", "trade_date", "close", "source"},
    )

    assert result.resolved_count == 1
    row = result.rows[0]
    assert row["ts_code"] == "000001.SH"
    assert row["trade_date"] == "2026-04-10"
    assert row["source"] == "tushare"


def test_default_publish_registry_only_retains_index_daily_builder() -> None:
    dao = DAOFactory(Session())
    registry = ServingPublishService(dao).builder_registry
    assert isinstance(registry.get("index_daily"), IndexDailyServingBuilder)
    assert registry.get("index_weekly") is None
    assert registry.get("index_monthly") is None
    assert validate_serving_coverage(dao=dao, builder_registry=registry) == []
