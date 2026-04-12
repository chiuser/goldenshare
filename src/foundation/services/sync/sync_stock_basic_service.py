from __future__ import annotations

from datetime import date
from typing import Any

from src.foundation.connectors.factory import create_source_connector
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.foundation.services.sync.fields import STOCK_BASIC_FIELDS
from src.foundation.services.transform.normalize_security_service import NormalizeSecurityService
from src.utils import coerce_row


class SyncStockBasicService(BaseSyncService):
    job_name = "sync_stock_basic"
    target_table = "core.security_serving"
    fields = STOCK_BASIC_FIELDS
    _normalizer = NormalizeSecurityService()

    _raw_dao_by_source = {
        "tushare": "raw_tushare_stock_basic",
        "biying": "raw_biying_stock_basic",
    }
    _supported_source_keys = ("tushare", "biying", "all")

    def _get_rows_from_source(self, source_key: str) -> list[dict[str, Any]]:
        connector = create_source_connector(source_key)
        if source_key == "tushare":
            return connector.call("stock_basic", params={"list_status": "L,D,P,G"}, fields=STOCK_BASIC_FIELDS)
        return connector.call("stock_basic")

    def _normalize_raw(self, rows: list[dict[str, Any]], source_key: str) -> list[dict[str, Any]]:
        if source_key == "tushare":
            return [coerce_row(row, ["list_date", "delist_date"], []) for row in rows]
        normalized: list[dict[str, Any]] = []
        for row in rows:
            normalized.append(
                {
                    "dm": row.get("dm"),
                    "mc": row.get("mc"),
                    "jys": row.get("jys"),
                }
            )
        return normalized

    def _publish_serving(self, std_rows: list[dict[str, Any]], source_key: str) -> int:
        if not std_rows:
            return 0
        serving_rows = []
        if source_key == "biying":
            ts_codes = [str(row["ts_code"]) for row in std_rows if row.get("ts_code")]
            existing = self.dao.security.get_existing_ts_codes(ts_codes)
            for row in std_rows:
                ts_code = str(row.get("ts_code", ""))
                if ts_code and ts_code not in existing:
                    serving_rows.append({key: value for key, value in row.items() if key != "source_key"})
        else:
            for row in std_rows:
                serving_rows.append({key: value for key, value in row.items() if key != "source_key"})
        return self.dao.security.upsert_many(serving_rows)

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        del run_type
        source_key = str(kwargs.get("source_key") or "tushare").strip().lower()
        if source_key not in self._supported_source_keys:
            raise ValueError(f"Unsupported source_key for stock_basic: {source_key}")

        source_keys = ("tushare", "biying") if source_key == "all" else (source_key,)
        total_fetched = 0
        total_written = 0

        for current_source in source_keys:
            rows = self._get_rows_from_source(current_source)
            raw_rows = self._normalize_raw(rows, current_source)
            raw_dao = getattr(self.dao, self._raw_dao_by_source[current_source])
            raw_dao.bulk_upsert(raw_rows)

            std_rows = [self._normalizer.to_std(row, source_key=current_source) for row in rows]
            self.dao.security_std.bulk_upsert(std_rows)

            written = self._publish_serving(std_rows, source_key=current_source)
            total_fetched += len(rows)
            total_written += written

        return total_fetched, total_written, None, f"source={source_key}"
