from __future__ import annotations

from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.foundation.models.meta.dataset_source_status import DatasetSourceStatus
from src.foundation.models.meta.source_registry import SourceRegistry


def test_source_registry_table_shape() -> None:
    assert SourceRegistry.__table__.schema == "foundation"
    assert [column.name for column in SourceRegistry.__table__.primary_key.columns] == ["source_key"]
    assert {index.name for index in SourceRegistry.__table__.indexes} == {"idx_source_registry_enabled_priority"}


def test_dataset_resolution_policy_table_shape() -> None:
    assert DatasetResolutionPolicy.__table__.schema == "foundation"
    assert [column.name for column in DatasetResolutionPolicy.__table__.primary_key.columns] == ["dataset_key"]
    assert "mode" in DatasetResolutionPolicy.__table__.columns
    assert "primary_source_key" in DatasetResolutionPolicy.__table__.columns
    assert "fallback_source_keys" in DatasetResolutionPolicy.__table__.columns
    assert "field_rules_json" in DatasetResolutionPolicy.__table__.columns


def test_dataset_source_status_table_shape() -> None:
    assert DatasetSourceStatus.__table__.schema == "foundation"
    assert [column.name for column in DatasetSourceStatus.__table__.primary_key.columns] == ["dataset_key", "source_key"]
    assert {index.name for index in DatasetSourceStatus.__table__.indexes} == {"idx_dataset_source_status_active"}
