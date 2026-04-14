from __future__ import annotations

from sqlalchemy.orm import Session

from src.ops.queries.layer_snapshot_query_service import LayerSnapshotQueryService
from src.ops.queries.probe_query_service import ProbeQueryService
from src.ops.queries.resolution_release_query_service import ResolutionReleaseQueryService
from src.ops.queries.std_rule_query_service import StdRuleQueryService
from src.ops.schemas.source_management_bridge import SourceManagementBridgeResponse, SourceManagementBridgeSummary


class SourceManagementBridgeQueryService:
    def get_bridge_payload(
        self,
        session: Session,
        *,
        probe_limit: int = 20,
        release_limit: int = 20,
        std_rule_limit: int = 200,
        layer_limit: int = 500,
    ) -> SourceManagementBridgeResponse:
        probe_response = ProbeQueryService().list_probe_rules(session, limit=probe_limit, offset=0)
        release_response = ResolutionReleaseQueryService().list_releases(session, limit=release_limit, offset=0)
        mapping_response = StdRuleQueryService().list_mapping_rules(session, limit=std_rule_limit, offset=0)
        cleansing_response = StdRuleQueryService().list_cleansing_rules(session, limit=std_rule_limit, offset=0)
        layer_latest_response = LayerSnapshotQueryService().list_latest(session, limit=layer_limit)

        summary = SourceManagementBridgeSummary(
            probe_total=probe_response.total,
            probe_active=sum(1 for item in probe_response.items if item.status == "active"),
            release_total=release_response.total,
            release_running=sum(1 for item in release_response.items if item.status == "running"),
            std_mapping_total=mapping_response.total,
            std_mapping_active=sum(1 for item in mapping_response.items if item.status == "active"),
            std_cleansing_total=cleansing_response.total,
            std_cleansing_active=sum(1 for item in cleansing_response.items if item.status == "active"),
            layer_latest_total=layer_latest_response.total,
            layer_latest_failed=sum(1 for item in layer_latest_response.items if item.status == "failed"),
        )
        return SourceManagementBridgeResponse(
            summary=summary,
            probe_rules=probe_response.items,
            releases=release_response.items,
            std_mapping_rules=mapping_response.items,
            std_cleansing_rules=cleansing_response.items,
            layer_latest=layer_latest_response.items,
        )
