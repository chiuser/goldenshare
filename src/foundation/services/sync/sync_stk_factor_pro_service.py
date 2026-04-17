from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from src.foundation.clients.tushare_client import TushareHttpClient
from src.foundation.config.settings import get_settings
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.foundation.services.sync.fields import STK_FACTOR_PRO_FIELDS
from src.ops.models.ops.job_execution import JobExecution
from src.utils import coerce_row, parse_tushare_date


class SyncStkFactorProService(BaseSyncService):
    job_name = "sync_stk_factor_pro"
    target_table = "core_serving.equity_factor_pro"
    api_name = "stk_factor_pro"
    fields = STK_FACTOR_PRO_FIELDS
    date_fields = ("trade_date",)
    page_limit = 10000
    history_start_date = date(2010, 1, 1)

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.client = TushareHttpClient()

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        execution_id = kwargs.get("execution_id")
        ts_code = kwargs.get("ts_code")
        self.ensure_not_canceled(execution_id)

        if run_type == "INCREMENTAL":
            trade_date = self._required_date(kwargs.get("trade_date"), field_name="trade_date")
            fetched, written = self._sync_trade_date(
                trade_date=trade_date,
                ts_code=ts_code,
                execution_id=execution_id,
            )
            self._update_progress(
                execution_id=execution_id,
                current=1,
                total=1,
                message=f"stk_factor_pro: 1/1 trade_date={trade_date.isoformat()} fetched={fetched} written={written}",
            )
            return fetched, written, trade_date, None

        explicit_trade_date = kwargs.get("trade_date")
        start_date = kwargs.get("start_date")
        end_date = kwargs.get("end_date")
        if explicit_trade_date is None and start_date is None and end_date is None:
            raise ValueError("sync_history.stk_factor_pro requires explicit time params: trade_date or start_date+end_date")

        if explicit_trade_date is not None:
            trade_date = self._required_date(explicit_trade_date, field_name="trade_date")
            fetched, written = self._sync_trade_date(
                trade_date=trade_date,
                ts_code=ts_code,
                execution_id=execution_id,
            )
            self._update_progress(
                execution_id=execution_id,
                current=1,
                total=1,
                message=f"stk_factor_pro: 1/1 trade_date={trade_date.isoformat()} fetched={fetched} written={written}",
            )
            return fetched, written, trade_date, None

        if start_date is None or end_date is None:
            raise ValueError("sync_history.stk_factor_pro requires both start_date and end_date when trade_date is not provided")

        start = self._required_date(start_date, field_name="start_date")
        end = self._required_date(end_date, field_name="end_date")
        if start > end:
            raise ValueError("start_date must be <= end_date")

        adjusted_start = max(start, self.history_start_date)
        if adjusted_start > end:
            return 0, 0, end, f"区间早于可用起点 {self.history_start_date.isoformat()}，未执行同步"

        exchange = str(kwargs.get("exchange") or get_settings().default_exchange)
        trade_dates = self.dao.trade_calendar.get_open_dates(exchange, adjusted_start, end)
        if not trade_dates:
            return 0, 0, end, "区间内无交易日，未执行同步"

        total = len(trade_dates)
        total_fetched = 0
        total_written = 0
        self._update_progress(
            execution_id=execution_id,
            current=0,
            total=total,
            message=f"准备按 {total} 个交易日同步股票技术面因子（专业版）。",
        )
        for index, trade_date in enumerate(trade_dates, start=1):
            self.ensure_not_canceled(execution_id)
            fetched, written = self._sync_trade_date(
                trade_date=trade_date,
                ts_code=ts_code,
                execution_id=execution_id,
            )
            total_fetched += fetched
            total_written += written
            self._update_progress(
                execution_id=execution_id,
                current=index,
                total=total,
                message=f"stk_factor_pro: {index}/{total} trade_date={trade_date.isoformat()} fetched={fetched} written={written}",
            )
        return total_fetched, total_written, end, f"trade_dates={total}"

    def _sync_trade_date(
        self,
        *,
        trade_date: date,
        ts_code: str | None,
        execution_id: int | None,
    ) -> tuple[int, int]:
        base_params: dict[str, Any] = {"trade_date": trade_date.strftime("%Y%m%d")}
        if ts_code:
            base_params["ts_code"] = ts_code

        fetched_total = 0
        written_total = 0
        offset = 0
        while True:
            self.ensure_not_canceled(execution_id)
            params = {**base_params, "limit": self.page_limit, "offset": offset}
            rows = self.client.call(self.api_name, params=params, fields=self.fields)
            if not rows:
                break
            normalized_rows = [coerce_row(row, self.date_fields, ()) for row in rows]
            self.dao.raw_stk_factor_pro.bulk_upsert(normalized_rows)
            serving_rows = [{**row, "source": "tushare"} for row in normalized_rows]
            written_total += self.dao.equity_factor_pro.bulk_upsert(serving_rows)
            fetched_total += len(rows)
            if len(rows) < self.page_limit:
                break
            offset += self.page_limit
        return fetched_total, written_total

    @staticmethod
    def _required_date(value: Any, *, field_name: str) -> date:
        parsed = parse_tushare_date(value)
        if parsed is None:
            raise ValueError(f"{field_name} is required")
        return parsed

    def _update_progress(self, *, execution_id: int | None, current: int, total: int, message: str) -> None:
        self._update_execution_progress(execution_id=execution_id, current=current, total=total, message=message)

