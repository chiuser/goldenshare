from __future__ import annotations

from typing import Any

from src.services.sync.fields import HK_BASIC_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_hk_basic_params(run_type: str, **kwargs: Any):  # type: ignore[no-untyped-def]
    params = {}
    list_status = kwargs.get("list_status")
    if isinstance(list_status, list):
        values = [str(item).strip() for item in list_status if str(item).strip()]
        if values:
            params["list_status"] = ",".join(values)
    elif list_status:
        params["list_status"] = list_status
    return params


def transform_hk_security(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["source"] = "tushare"
    return normalized


class SyncHkBasicService(HttpResourceSyncService):
    job_name = "sync_hk_basic"
    target_table = "core.hk_security"
    api_name = "hk_basic"
    raw_dao_name = "raw_hk_basic"
    core_dao_name = "hk_security"
    fields = HK_BASIC_FIELDS
    date_fields = ("list_date", "delist_date")
    params_builder = staticmethod(build_hk_basic_params)
    core_transform = staticmethod(transform_hk_security)
