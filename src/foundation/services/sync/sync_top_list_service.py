from __future__ import annotations

from datetime import date

from src.foundation.services.transform.top_list_reason import hash_top_list_reason
from src.utils import coerce_row
from src.foundation.services.sync.fields import TOP_LIST_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService
from src.foundation.services.sync.sync_daily_basic_service import build_trade_date_only


class SyncTopListService(HttpResourceSyncService):
    job_name = "sync_top_list"
    target_table = "core.equity_top_list"
    api_name = "top_list"
    raw_dao_name = "raw_top_list"
    core_dao_name = "equity_top_list"
    fields = TOP_LIST_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("close", "pct_change", "turnover_rate", "amount", "l_sell", "l_buy", "l_amount", "net_amount", "net_rate", "amount_rate", "float_values")
    params_builder = staticmethod(build_trade_date_only)

    def execute(self, run_type: str, **kwargs) -> tuple[int, int, date | None, str | None]:  # type: ignore[override]
        trade_date = kwargs.get("trade_date")
        rows = self.client.call(self.api_name, params=self.params_builder(run_type, **kwargs), fields=self.fields)
        normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
        self.dao.raw_top_list.bulk_upsert(normalized)

        valid_core_rows: list[dict] = []
        skipped_missing_reason = 0
        for row in normalized:
            reason_hash = hash_top_list_reason(row.get("reason"))
            if reason_hash is None:
                skipped_missing_reason += 1
                continue
            valid_core_rows.append(
                {
                    **row,
                    "pct_chg": row.get("pct_change"),
                    "reason_hash": reason_hash,
                }
            )

        if skipped_missing_reason:
            self.logger.warning("skipped %s top_list rows missing required core reason", skipped_missing_reason)

        # Keep the legacy primary-key conflict semantics until all historical rows have
        # been backfilled with reason_hash and duplicate groups have been checked.
        written = self.dao.equity_top_list.bulk_upsert(valid_core_rows)
        message = None
        if skipped_missing_reason:
            message = f"skipped {skipped_missing_reason} top_list rows missing required core reason"
        return len(rows), written, trade_date, message
