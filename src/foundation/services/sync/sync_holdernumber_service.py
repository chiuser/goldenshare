from __future__ import annotations

from datetime import date

from src.foundation.services.sync.fields import HOLDERNUMBER_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService
from src.foundation.services.sync.sync_dividend_service import build_date_window_params
from src.foundation.services.transform.holdernumber_hash import build_holdernumber_event_key_hash, build_holdernumber_row_key_hash
from src.utils import coerce_row


class SyncHolderNumberService(HttpResourceSyncService):
    job_name = "sync_holder_number"
    target_table = "core_serving.equity_holder_number"
    api_name = "stk_holdernumber"
    raw_dao_name = "raw_holder_number"
    core_dao_name = "equity_holder_number"
    fields = HOLDERNUMBER_FIELDS
    date_fields = ("ann_date", "end_date")
    params_builder = staticmethod(build_date_window_params)

    def execute(self, run_type: str, **kwargs):  # type: ignore[no-untyped-def]
        trade_date = kwargs.get("trade_date")
        rows = self.client.call(self.api_name, params=self.params_builder(run_type, **kwargs), fields=self.fields)
        normalized = [coerce_row(row, self.date_fields, ()) for row in rows]
        raw_dao = getattr(self.dao, self.raw_dao_name)
        core_dao = getattr(self.dao, self.core_dao_name)
        raw_rows = [{**row, "row_key_hash": build_holdernumber_row_key_hash(row)} for row in normalized]
        raw_dao.bulk_upsert(raw_rows, conflict_columns=["row_key_hash"])

        required_fields = ("ts_code", "end_date")
        valid_core_rows = []
        skipped = 0
        sample_missing = None
        for row in normalized:
            missing = [field for field in required_fields if row.get(field) is None]
            if missing:
                skipped += 1
                if sample_missing is None:
                    sample_missing = (missing, row)
                continue
            valid_core_rows.append(
                {
                    **row,
                    "row_key_hash": build_holdernumber_row_key_hash(row),
                    "event_key_hash": build_holdernumber_event_key_hash(row),
                }
            )

        written = core_dao.bulk_upsert(valid_core_rows, conflict_columns=["row_key_hash"])
        message = None
        if skipped:
            message = f"skipped {skipped} core holdernumber rows missing required business keys"
            if sample_missing is not None:
                missing, row = sample_missing
                self.logger.debug(
                    "Sample skipped core_serving.equity_holder_number row due to missing required fields %s: ts_code=%s end_date=%s ann_date=%s",
                    ",".join(missing),
                    row.get("ts_code"),
                    row.get("end_date"),
                    row.get("ann_date"),
                )
            self.logger.warning(message)
        return len(rows), written, trade_date, message
