from __future__ import annotations

from typing import Any

from src.services.sync.fields import US_BASIC_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def _normalize_us_classify(value: Any) -> str:
    normalized = str(value).strip().upper()
    return "EQT" if normalized == "EQ" else normalized


def build_us_basic_params(run_type: str, **kwargs: Any):  # type: ignore[no-untyped-def]
    params = {}
    classify = kwargs.get("classify")
    if isinstance(classify, list):
        values = [_normalize_us_classify(item) for item in classify if str(item).strip()]
        if values:
            params["classify"] = ",".join(values)
    elif classify is not None and classify != "":
        params["classify"] = _normalize_us_classify(classify)
    for key in ("ts_code", "offset", "limit"):
        if kwargs.get(key) is not None and kwargs.get(key) != "":
            params[key] = kwargs[key]
    return params


def transform_us_security(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["source"] = "tushare"
    return normalized


class SyncUsBasicService(HttpResourceSyncService):
    job_name = "sync_us_basic"
    target_table = "core.us_security"
    api_name = "us_basic"
    raw_dao_name = "raw_us_basic"
    core_dao_name = "us_security"
    fields = US_BASIC_FIELDS
    date_fields = ("list_date", "delist_date")
    params_builder = staticmethod(build_us_basic_params)
    core_transform = staticmethod(transform_us_security)
