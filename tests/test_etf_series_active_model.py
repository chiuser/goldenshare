from __future__ import annotations

from pathlib import Path

from src.app.model_registry import MODEL_MODULES
from src.foundation.models.base import Base
from src.ops.models.ops.etf_series_active import EtfSeriesActive


def test_etf_series_active_table_shape() -> None:
    assert EtfSeriesActive.__table__.schema == "ops"
    assert [column.name for column in EtfSeriesActive.__table__.primary_key.columns] == ["resource", "ts_code"]
    assert "first_seen_date" in EtfSeriesActive.__table__.columns
    assert "last_seen_date" in EtfSeriesActive.__table__.columns
    assert "last_checked_at" in EtfSeriesActive.__table__.columns
    assert "created_at" in EtfSeriesActive.__table__.columns
    assert "updated_at" in EtfSeriesActive.__table__.columns
    index_names = {index.name for index in EtfSeriesActive.__table__.indexes}
    assert "idx_etf_series_active_resource" in index_names
    assert "idx_etf_series_active_resource_last_seen" in index_names


def test_etf_series_active_model_is_registered() -> None:
    assert EtfSeriesActive.__table__ is Base.metadata.tables["ops.etf_series_active"]
    assert "src.ops.models.ops.etf_series_active" in MODEL_MODULES


def test_etf_series_active_migration_uses_current_head() -> None:
    migration_text = Path("alembic/versions/20260618_000117_add_etf_series_active.py").read_text(encoding="utf-8")

    assert 'revision = "20260618_000117"' in migration_text
    assert 'down_revision = "20260602_000116"' in migration_text
    assert "ops.index_series_active" not in migration_text
    assert "raw_tushare.fund_daily" not in migration_text
    assert "core_serving.fund_daily_bar" not in migration_text
    assert "CREATE SCHEMA IF NOT EXISTS ops" in migration_text
