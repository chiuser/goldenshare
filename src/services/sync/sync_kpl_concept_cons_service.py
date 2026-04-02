from __future__ import annotations

from src.services.sync.fields import KPL_CONCEPT_CONS_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_kpl_concept_cons_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    if run_type == "FULL":
        params = {
            "trade_date": kwargs.get("trade_date"),
            "ts_code": kwargs.get("ts_code"),
            "con_code": kwargs.get("con_code"),
        }
        return {key: value.replace("-", "") if key == "trade_date" and isinstance(value, str) else value for key, value in params.items() if value}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental kpl_concept_cons sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "con_code": kwargs.get("con_code"),
    }
    return {key: value for key, value in params.items() if value}


def transform_kpl_concept_cons_row(row):  # type: ignore[no-untyped-def]
    if row.get("con_name") in (None, "") and row.get("ts_name"):
        row["con_name"] = row["ts_name"]
    return row


class SyncKplConceptConsService(HttpResourceSyncService):
    job_name = "sync_kpl_concept_cons"
    target_table = "core.kpl_concept_cons"
    api_name = "kpl_concept_cons"
    raw_dao_name = "raw_kpl_concept_cons"
    core_dao_name = "kpl_concept_cons"
    fields = KPL_CONCEPT_CONS_FIELDS
    date_fields = ("trade_date",)
    params_builder = staticmethod(build_kpl_concept_cons_params)
    core_transform = staticmethod(transform_kpl_concept_cons_row)
