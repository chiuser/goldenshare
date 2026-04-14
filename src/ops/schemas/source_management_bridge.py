from __future__ import annotations

from pydantic import BaseModel

from src.ops.schemas.layer_snapshot import LayerSnapshotLatestItem
from src.ops.schemas.probe import ProbeRuleListItem
from src.ops.schemas.resolution_release import ResolutionReleaseListItem
from src.ops.schemas.std_rule import StdCleansingRuleItem, StdMappingRuleItem


class SourceManagementBridgeSummary(BaseModel):
    probe_total: int
    probe_active: int
    release_total: int
    release_running: int
    std_mapping_total: int
    std_mapping_active: int
    std_cleansing_total: int
    std_cleansing_active: int
    layer_latest_total: int
    layer_latest_failed: int


class SourceManagementBridgeResponse(BaseModel):
    summary: SourceManagementBridgeSummary
    probe_rules: list[ProbeRuleListItem]
    releases: list[ResolutionReleaseListItem]
    std_mapping_rules: list[StdMappingRuleItem]
    std_cleansing_rules: list[StdCleansingRuleItem]
    layer_latest: list[LayerSnapshotLatestItem]
