from __future__ import annotations

from pathlib import Path

from src.app.model_registry import MODEL_MODULES
from src.foundation.models.base import Base
from src.foundation.models.meta.realtime_runtime_config import RealtimeRuntimeConfigRecord


def test_realtime_runtime_config_table_shape() -> None:
    assert RealtimeRuntimeConfigRecord.__table__.schema == "foundation"
    assert [column.name for column in RealtimeRuntimeConfigRecord.__table__.primary_key.columns] == ["object_key"]
    assert "object_kind" in RealtimeRuntimeConfigRecord.__table__.columns
    assert "runtime_config_json" in RealtimeRuntimeConfigRecord.__table__.columns
    assert "version" in RealtimeRuntimeConfigRecord.__table__.columns
    assert "requires_collector_restart" in RealtimeRuntimeConfigRecord.__table__.columns
    assert "updated_by_user_id" in RealtimeRuntimeConfigRecord.__table__.columns
    assert "created_at" in RealtimeRuntimeConfigRecord.__table__.columns
    assert "updated_at" in RealtimeRuntimeConfigRecord.__table__.columns


def test_realtime_runtime_config_model_is_registered() -> None:
    assert RealtimeRuntimeConfigRecord.__table__ is Base.metadata.tables["foundation.realtime_runtime_config"]
    assert "src.foundation.models.meta.realtime_runtime_config" in MODEL_MODULES


def test_realtime_runtime_config_migration_uses_current_head() -> None:
    migration_text = Path("alembic/versions/20260602_000116_add_realtime_runtime_config.py").read_text(encoding="utf-8")

    assert 'revision = "20260602_000116"' in migration_text
    assert 'down_revision = "20260531_000115"' in migration_text
    assert "ops.config_revision" not in migration_text
    assert "CREATE SCHEMA IF NOT EXISTS foundation" in migration_text
