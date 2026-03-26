from __future__ import annotations

from datetime import date
from typing import Any

from src.services.sync.fields import DIVIDEND_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService
from src.services.transform.dividend_hash import build_dividend_event_key_hash, build_dividend_row_key_hash
from src.utils import coerce_row


def build_date_window_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    params = {}
    if kwargs.get("ts_code"):
        params["ts_code"] = kwargs["ts_code"]
    if kwargs.get("ann_date"):
        params["ann_date"] = kwargs["ann_date"].strftime("%Y%m%d")
    return params


class SyncDividendService(HttpResourceSyncService):
    job_name = "sync_dividend"
    target_table = "core.equity_dividend"
    api_name = "dividend"
    raw_dao_name = "raw_dividend"
    core_dao_name = "equity_dividend"
    fields = DIVIDEND_FIELDS
    date_fields = ("end_date", "ann_date", "record_date", "ex_date", "pay_date", "div_listdate", "imp_ann_date", "base_date")
    decimal_fields = ("base_share", "stk_div", "stk_bo_rate", "stk_co_rate", "cash_div", "cash_div_tax")
    params_builder = staticmethod(build_date_window_params)

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        rows = self.client.call(self.api_name, params=self.params_builder(run_type, **kwargs), fields=self.fields)
        normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
        raw_dao = getattr(self.dao, self.raw_dao_name)
        core_dao = getattr(self.dao, self.core_dao_name)
        raw_rows = [{**row, "row_key_hash": build_dividend_row_key_hash(row)} for row in normalized]
        raw_dao.bulk_upsert(raw_rows, conflict_columns=["row_key_hash"])
        required_fields = ("ts_code", "end_date", "ann_date", "div_proc")
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
                    "row_key_hash": build_dividend_row_key_hash(row),
                    "event_key_hash": build_dividend_event_key_hash(row),
                }
            )

        written = core_dao.bulk_upsert(valid_core_rows, conflict_columns=["row_key_hash"])
        message = None
        if skipped:
            message = f"skipped {skipped} core dividend rows missing required business keys"
            if sample_missing is not None:
                missing, row = sample_missing
                self.logger.debug(
                    "Sample skipped core.equity_dividend row due to missing required fields %s: ts_code=%s end_date=%s ann_date=%s div_proc=%s",
                    ",".join(missing),
                    row.get("ts_code"),
                    row.get("end_date"),
                    row.get("ann_date"),
                    row.get("div_proc"),
                )
            self.logger.warning(message)
        return len(rows), written, trade_date, message
