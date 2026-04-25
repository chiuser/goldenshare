from __future__ import annotations

from src.foundation.connectors.base import SourceConnector
from src.foundation.connectors.factory import create_source_connector
from src.foundation.services.sync_v2.adapters.base import SourceAdapter, SourceRequest
from src.foundation.services.sync_v2.contracts import DatasetSyncContract, PlanUnit
from src.foundation.services.sync_v2.sentinel_guard import assert_no_forbidden_business_sentinel


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
        assert_no_forbidden_business_sentinel(params, location="source_request.params")
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
        rows = self.connector.call(
            api_name=request.api_name,
            params=request.params,
            fields=request.fields,
        )
        if request.api_name == "ths_hot":
            query_market = str(request.params.get("market") or "").strip()
            query_is_new = str(request.params.get("is_new") or "").strip()
            for row in rows:
                if query_market:
                    row["query_market"] = query_market
                if query_is_new:
                    row["query_is_new"] = query_is_new
        if request.api_name == "dc_hot":
            query_market = str(request.params.get("market") or "").strip()
            query_hot_type = str(request.params.get("hot_type") or "").strip()
            query_is_new = str(request.params.get("is_new") or "").strip()
            for row in rows:
                if query_market:
                    row["query_market"] = query_market
                if query_hot_type:
                    row["query_hot_type"] = query_hot_type
                if query_is_new:
                    row["query_is_new"] = query_is_new
        if request.api_name == "limit_list_ths":
            query_limit_type = str(request.params.get("limit_type") or "").strip()
            query_market = str(request.params.get("market") or "").strip()
            for row in rows:
                if query_limit_type:
                    row["query_limit_type"] = query_limit_type
                if query_market:
                    row["query_market"] = query_market
        if request.api_name == "stk_mins":
            query_freq = str(request.params.get("freq") or "").strip()
            for row in rows:
                row["freq"] = query_freq
        return rows
