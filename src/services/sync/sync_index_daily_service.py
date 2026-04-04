from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from src.config.settings import get_settings
from src.models.ops.job_execution import JobExecution
from src.services.sync.fields import INDEX_DAILY_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService
from src.utils import coerce_row


def build_index_daily_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {"ts_code": kwargs.get("ts_code"), "start_date": kwargs.get("start_date", settings.history_start_date).replace("-", "")}
        if kwargs.get("end_date"):
            params["end_date"] = kwargs["end_date"].replace("-", "")
        return {k: v for k, v in params.items() if v}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental index_daily sync")
    params = {"trade_date": trade_date.strftime("%Y%m%d"), "ts_code": kwargs.get("ts_code")}
    return {k: v for k, v in params.items() if v}


class SyncIndexDailyService(HttpResourceSyncService):
    job_name = "sync_index_daily"
    target_table = "core.index_daily_serving"
    api_name = "index_daily"
    raw_dao_name = "raw_index_daily"
    core_dao_name = "index_daily_serving"
    fields = INDEX_DAILY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount")
    params_builder = staticmethod(build_index_daily_params)
    core_transform = staticmethod(lambda row: {**row, "change_amount": row.get("change")})
    page_limit = 2000
    resource_key = "index_daily"

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        execution_id = kwargs.get("execution_id")
        self.ensure_not_canceled(execution_id)
        if kwargs.get("ts_code"):
            fetched, written, latest_seen = self._sync_index_code(run_type=run_type, **kwargs)
            if latest_seen is not None:
                self.dao.index_series_active.upsert_seen_codes(self.resource_key, {kwargs["ts_code"]: latest_seen})
            self._update_progress(
                execution_id=execution_id,
                current=1,
                total=1,
                message=f"index_daily: 1/1 ts_code={kwargs['ts_code']} fetched={fetched} written={written}",
            )
            return fetched, written, trade_date, None

        index_codes = self.dao.index_series_active.list_active_codes(self.resource_key)
        if not index_codes:
            index_codes = [item.ts_code for item in self.dao.index_basic.get_active_indexes() if item.ts_code]
        total_indexes = len(index_codes)
        self._update_progress(
            execution_id=execution_id,
            current=0,
            total=total_indexes,
            message=f"准备按 {total_indexes} 个指数逐个同步日线行情。",
        )
        total_fetched = 0
        total_written = 0
        latest_seen_by_code: dict[str, date] = {}
        for index, index_code in enumerate(index_codes, start=1):
            self.ensure_not_canceled(execution_id)
            fetched, written, latest_seen = self._sync_index_code(run_type=run_type, **{**kwargs, "ts_code": index_code})
            total_written += written
            total_fetched += fetched
            if latest_seen is not None:
                latest_seen_by_code[index_code] = latest_seen
            self._update_progress(
                execution_id=execution_id,
                current=index,
                total=total_indexes,
                message=f"正在同步指数日线：{index}/{total_indexes} {index_code} fetched={fetched} written={written}",
            )
        if latest_seen_by_code:
            self.dao.index_series_active.upsert_seen_codes(self.resource_key, latest_seen_by_code)
        return total_fetched, total_written, trade_date, None

    def _sync_index_code(self, *, run_type: str, **kwargs: Any) -> tuple[int, int, date | None]:
        execution_id = kwargs.get("execution_id")
        params = self.params_builder(run_type, **kwargs)
        total_fetched = 0
        total_written = 0
        latest_seen: date | None = None
        offset = 0
        while True:
            self.ensure_not_canceled(execution_id)
            page_params = {**params, "limit": self.page_limit, "offset": offset}
            rows = self.client.call(self.api_name, params=page_params, fields=self.fields)
            if not rows:
                break
            normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
            self.dao.raw_index_daily.bulk_upsert(normalized)
            written = self.dao.index_daily_serving.bulk_upsert([self.core_transform(row) for row in normalized])
            total_fetched += len(rows)
            total_written += written
            for row in normalized:
                row_date = row.get("trade_date")
                if isinstance(row_date, date) and (latest_seen is None or row_date > latest_seen):
                    latest_seen = row_date
            if len(rows) < self.page_limit:
                break
            offset += self.page_limit
        return total_fetched, total_written, latest_seen

    def _update_progress(self, *, execution_id: int | None, current: int, total: int, message: str) -> None:
        if execution_id is None:
            return
        execution = self.session.get(JobExecution, execution_id)
        if execution is None:
            return
        execution.progress_current = current
        execution.progress_total = total
        execution.progress_percent = int((current / total) * 100) if total else None
        execution.progress_message = message
        execution.last_progress_at = datetime.now(timezone.utc)
        self.session.commit()
