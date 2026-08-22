from __future__ import annotations

from pathlib import Path

from src.app.model_registry import MODEL_MODULES
from src.foundation.models.base import Base
from src.ops.models.ops.etf_realtime_alert import EtfRealtimeAlert
from src.ops.models.ops.etf_realtime_minute_stat import EtfRealtimeMinuteStat
from src.ops.models.ops.etf_realtime_monitor_pool import EtfRealtimeMonitorPool
from src.ops.models.ops.etf_realtime_monitor_rule import EtfRealtimeMonitorRule


def test_etf_realtime_monitor_models_are_registered() -> None:
    assert EtfRealtimeMonitorPool.__table__ is Base.metadata.tables["ops.etf_realtime_monitor_pool"]
    assert EtfRealtimeMonitorRule.__table__ is Base.metadata.tables["ops.etf_realtime_monitor_rule"]
    assert EtfRealtimeMinuteStat.__table__ is Base.metadata.tables["ops.etf_realtime_minute_stat"]
    assert EtfRealtimeAlert.__table__ is Base.metadata.tables["ops.etf_realtime_alert"]
    assert "src.ops.models.ops.etf_realtime_monitor_pool" in MODEL_MODULES
    assert "src.ops.models.ops.etf_realtime_monitor_rule" in MODEL_MODULES
    assert "src.ops.models.ops.etf_realtime_minute_stat" in MODEL_MODULES
    assert "src.ops.models.ops.etf_realtime_alert" in MODEL_MODULES


def test_etf_realtime_monitor_migration_uses_current_head_and_does_not_seed() -> None:
    migration_text = Path("alembic/versions/20260822_000139_add_etf_realtime_monitor_tables.py").read_text(encoding="utf-8")

    assert 'revision = "20260822_000139"' in migration_text
    assert 'down_revision = "20260818_000138"' in migration_text
    assert "etf_realtime_monitor_pool" in migration_text
    assert "etf_realtime_monitor_rule" in migration_text
    assert "etf_realtime_minute_stat" in migration_text
    assert "etf_realtime_alert" in migration_text
    assert "INSERT" not in migration_text.upper()


def test_etf_realtime_monitor_pool_display_order_is_fully_retired() -> None:
    migration_text = Path("alembic/versions/20260822_000142_drop_etf_realtime_monitor_pool_display_order.py").read_text(
        encoding="utf-8"
    )

    assert "display_order" not in EtfRealtimeMonitorPool.__table__.c
    assert 'revision = "20260822_000142"' in migration_text
    assert 'down_revision = "20260822_000141"' in migration_text
    assert "op.drop_index(_INDEX" in migration_text
    assert 'op.drop_column(_TABLE, "display_order"' in migration_text
