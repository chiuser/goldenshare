from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import (
    WealthSectorAnalysisPublishBatch,
)
from src.foundation.models.core_serving.wealth_sector_daily_insight_item import (
    WealthSectorDailyInsightItem,
)
from src.foundation.models.core_serving.wealth_sector_daily_insight_summary import (
    WealthSectorDailyInsightSummary,
)
from src.foundation.models.core_serving.wealth_sector_dual_momentum_daily import (
    WealthSectorDualMomentumDaily,
)
from src.foundation.models.core_serving.wealth_sector_member_breadth_daily import (
    WealthSectorMemberBreadthDaily,
)
from src.foundation.models.core_serving.wealth_sector_member_ma_breadth_daily import (
    WealthSectorMemberMaBreadthDaily,
)
from src.foundation.models.core_serving.wealth_sector_momentum_daily import (
    WealthSectorMomentumDaily,
)
from src.foundation.models.core_serving.wealth_sector_price_volume_daily import (
    WealthSectorPriceVolumeDaily,
)
from src.foundation.models.core_serving.wealth_sector_relative_rotation_daily import (
    WealthSectorRelativeRotationDaily,
)


MODELS = (
    WealthSectorAnalysisPublishBatch,
    WealthSectorMomentumDaily,
    WealthSectorDualMomentumDaily,
    WealthSectorRelativeRotationDaily,
    WealthSectorMemberBreadthDaily,
    WealthSectorMemberMaBreadthDaily,
    WealthSectorPriceVolumeDaily,
    WealthSectorDailyInsightSummary,
    WealthSectorDailyInsightItem,
)
FACT_MODELS = MODELS[1:7]
MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260831_000168_add_wealth_sector_analysis_daily_facts.py"
)


def test_nine_models_are_non_partitioned_core_serving_tables() -> None:
    assert len(MODELS) == 9
    assert len({model.__tablename__ for model in MODELS}) == 9
    for model in MODELS:
        assert model.__table__.schema == "core_serving"
        assert "postgresql_partition_by" not in model.__table__.dialect_options["postgresql"]


def test_fact_tables_bind_batch_and_trade_date_and_freeze_comparison_identity() -> None:
    for model in FACT_MODELS:
        foreign_keys = tuple(
            constraint
            for constraint in model.__table__.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        )
        assert any(
            tuple(element.parent.name for element in constraint.elements) == ("batch_id", "trade_date")
            for constraint in foreign_keys
        )
        check_sql = " ".join(
            str(constraint.sqltext)
            for constraint in model.__table__.constraints
            if isinstance(constraint, CheckConstraint)
        )
        assert "GLOBAL:L1" in check_sql
        assert "PARENT:L2:" in check_sql


def test_previous_batch_binding_is_composite_and_complete() -> None:
    table = WealthSectorAnalysisPublishBatch.__table__
    foreign_keys = tuple(
        constraint for constraint in table.constraints if isinstance(constraint, ForeignKeyConstraint)
    )
    assert any(
        tuple(element.parent.name for element in constraint.elements)
        == ("previous_batch_id", "previous_trade_date")
        for constraint in foreign_keys
    )
    check_sql = " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )
    assert "previous_batch_id IS NULL OR previous_trade_date IS NOT NULL" in check_sql


def test_migration_is_single_head_hdd_fail_closed_and_has_no_destructive_downgrade() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision = "20260830_000167"' in source
    assert '_TABLESPACE = "gs_raw_cold_hdd"' in source
    assert "has_tablespace_privilege" in source
    assert "pg_tablespace_location" in source
    assert "postgresql_tablespace=_TABLESPACE" in source
    assert "actual TOAST" not in source
    assert "不支持自动 downgrade 删除" in source
    for model in MODELS:
        assert model.__tablename__ in source
