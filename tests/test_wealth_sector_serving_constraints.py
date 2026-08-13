from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from src.foundation.models.core_serving.wealth_sector_heat_daily import WealthSectorHeatDaily
from src.foundation.models.core_serving.wealth_sector_hierarchy import WealthSectorHierarchy


@pytest.fixture()
def engine() -> Engine:
    database = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with database.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        WealthSectorHierarchy.__table__.create(connection)
        WealthSectorHeatDaily.__table__.create(connection)
    return database


def _hierarchy_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sector_code": "BK001",
        "sector_name": "测试行业",
        "industry_level": 1,
        "industry_level_name": "一级行业",
        "parent_sector_code": None,
        "parent_sector_name": None,
        "root_sector_code": "BK001",
        "root_sector_name": "测试行业",
        "hierarchy_path": "BK001",
        "is_leaf": False,
        "display_order": 0,
        "baseline_version": "dc-industry-v1",
        "source_received_date": date(2026, 8, 13),
        "code_reference_trade_date": date(2026, 8, 12),
        "published_at": datetime(2026, 8, 13, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def _heat_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "trade_date": date(2026, 8, 12),
        "sector_code": "BK100",
        "sector_name": "测试概念",
        "heat_status": "VALID",
        "invalid_reason": None,
        "base_heat_score": Decimal("72.0000"),
        "base_heat_rank": 3,
        "heat_score": Decimal("75.0000"),
        "heat_rank": 2,
        "heat_level": "ACTIVE",
        "heat_delta_1d": Decimal("2.0000"),
        "heat_trend": "STABLE",
        "raw_heat_trend": "STABLE",
        "price_strength_score": Decimal("0.700000"),
        "breadth_score": Decimal("0.800000"),
        "capital_flow_score": Decimal("0.600000"),
        "activity_score": Decimal("0.500000"),
        "persistence_score": Decimal("0.750000"),
        "source_member_count": 12,
        "member_count": 10,
        "suspended_count": 1,
        "quote_eligible_count": 9,
        "valid_quote_count": 8,
        "missing_quote_count": 1,
        "quote_coverage": Decimal("0.888889"),
        "score_version": "concept-heat-eod-v1",
        "config_hash": "a" * 64,
        "source_dates_json": {"dc_daily": "2026-08-12"},
        "source_row_counts_json": {"dc_daily": 100},
        "source_hash": "b" * 64,
        "calculated_at": datetime(2026, 8, 13, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def _insert(engine: Engine, table: Any, values: dict[str, Any]) -> None:
    with engine.begin() as connection:
        connection.execute(table.insert().values(**values))


def test_valid_hierarchy_and_heat_rows_are_accepted(engine: Engine) -> None:
    _insert(engine, WealthSectorHierarchy.__table__, _hierarchy_row())
    _insert(engine, WealthSectorHeatDaily.__table__, _heat_row())


def test_invalid_heat_with_fixed_reason_and_empty_outputs_is_accepted(engine: Engine) -> None:
    _insert(
        engine,
        WealthSectorHeatDaily.__table__,
        _heat_row(
            heat_status="INVALID",
            invalid_reason="HISTORY_INSUFFICIENT",
            heat_score=None,
            heat_rank=None,
            heat_level="NONE",
            heat_delta_1d=None,
            heat_trend="UNKNOWN",
            raw_heat_trend="UNKNOWN",
            persistence_score=None,
        ),
    )


def test_hierarchy_parent_fields_must_match_the_industry_level(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        _insert(
            engine,
            WealthSectorHierarchy.__table__,
            _hierarchy_row(parent_sector_code="BK000", parent_sector_name="非法父级"),
        )


def test_valid_heat_requires_all_scores_and_ranks(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        _insert(
            engine,
            WealthSectorHeatDaily.__table__,
            _heat_row(price_strength_score=None),
        )


def test_invalid_heat_rejects_free_text_reason(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        _insert(
            engine,
            WealthSectorHeatDaily.__table__,
            _heat_row(
                heat_status="INVALID",
                invalid_reason="free text",
                heat_score=None,
                heat_rank=None,
                heat_level="NONE",
                heat_delta_1d=None,
                heat_trend="UNKNOWN",
                raw_heat_trend="UNKNOWN",
            ),
        )


def test_invalid_heat_cannot_publish_a_fake_zero_score(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        _insert(
            engine,
            WealthSectorHeatDaily.__table__,
            _heat_row(
                heat_status="INVALID",
                invalid_reason="HISTORY_INSUFFICIENT",
                heat_score=Decimal("0.0000"),
                heat_rank=None,
                heat_level="NONE",
                heat_delta_1d=None,
                heat_trend="UNKNOWN",
                raw_heat_trend="UNKNOWN",
                persistence_score=None,
            ),
        )


def test_heat_member_count_equations_are_enforced(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        _insert(
            engine,
            WealthSectorHeatDaily.__table__,
            _heat_row(quote_eligible_count=10),
        )
