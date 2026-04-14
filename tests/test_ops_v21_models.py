from __future__ import annotations

from src.ops.models.ops.dataset_layer_snapshot_history import DatasetLayerSnapshotHistory
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.models.ops.probe_run_log import ProbeRunLog
from src.ops.models.ops.resolution_release import ResolutionRelease
from src.ops.models.ops.resolution_release_stage_status import ResolutionReleaseStageStatus
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule


def test_ops_v21_new_models_schema_and_primary_keys() -> None:
    assert DatasetLayerSnapshotHistory.__table__.schema == "ops"
    assert [column.name for column in DatasetLayerSnapshotHistory.__table__.primary_key.columns] == ["id"]

    assert ProbeRule.__table__.schema == "ops"
    assert [column.name for column in ProbeRule.__table__.primary_key.columns] == ["id"]

    assert ProbeRunLog.__table__.schema == "ops"
    assert [column.name for column in ProbeRunLog.__table__.primary_key.columns] == ["id"]

    assert ResolutionRelease.__table__.schema == "ops"
    assert [column.name for column in ResolutionRelease.__table__.primary_key.columns] == ["id"]

    assert ResolutionReleaseStageStatus.__table__.schema == "ops"
    assert [column.name for column in ResolutionReleaseStageStatus.__table__.primary_key.columns] == ["id"]

    assert StdMappingRule.__table__.schema == "ops"
    assert [column.name for column in StdMappingRule.__table__.primary_key.columns] == ["id"]

    assert StdCleansingRule.__table__.schema == "ops"
    assert [column.name for column in StdCleansingRule.__table__.primary_key.columns] == ["id"]
