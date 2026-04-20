from __future__ import annotations

from src.foundation.connectors.base import SourceConnector
from src.foundation.connectors.factory import create_source_connector
from src.foundation.services.sync_v2.adapters.base import SourceAdapter, SourceRequest
from src.foundation.services.sync_v2.contracts import DatasetSyncContract, PlanUnit


class TushareSyncV2Adapter(SourceAdapter):
    source_key = "tushare"

    def __init__(self, connector: SourceConnector | None = None) -> None:
        self.connector = connector or create_source_connector(self.source_key)

    def build_request(
        self,
        *,
        contract: DatasetSyncContract,
        unit: PlanUnit,
        offset: int | None = None,
        page_limit: int | None = None,
    ) -> SourceRequest:
        params = dict(contract.source_spec.base_params)
        params.update(unit.request_params)
        if offset is not None:
            params["offset"] = offset
        if page_limit is not None:
            params["limit"] = page_limit
        return SourceRequest(
            source_key=self.source_key,
            api_name=contract.source_spec.api_name,
            params=params,
            fields=contract.source_spec.fields,
        )

    def execute(self, request: SourceRequest) -> list[dict]:
        return self.connector.call(
            api_name=request.api_name,
            params=request.params,
            fields=request.fields,
        )
