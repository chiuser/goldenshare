from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from src.foundation.clients.tushare_client import TushareHttpClient
from src.foundation.config.settings import get_settings
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.foundation.services.sync.fields import MARGIN_FIELDS
from src.ops.models.ops.job_execution import JobExecution
from src.utils import coerce_row, parse_tushare_date

ALL_MARGIN_EXCHANGE_IDS = ("SSE", "SZSE", "BSE")


class SyncMarginService(BaseSyncService):
    job_name = "sync_margin"
    target_table = "core_serving.equity_margin"
    api_name = "margin"
    fields = MARGIN_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("rzye", "rzmre", "rzche", "rqye", "rqmcl", "rzrqye", "rqyl")

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.client = TushareHttpClient()

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        execution_id = kwargs.get("execution_id")
        exchange_ids = self._normalize_exchange_ids(kwargs.get("exchange_id"))
        self.ensure_not_canceled(execution_id)

        if run_type == "INCREMENTAL":
            trade_date = self._required_date(kwargs.get("trade_date"), field_name="trade_date")
            fetched, written = self._sync_trade_date(
                trade_date=trade_date,
                exchange_ids=exchange_ids,
                execution_id=execution_id,
            )
            return fetched, written, trade_date, f"trade_date={trade_date.isoformat()} exchanges={','.join(exchange_ids)}"

        explicit_trade_date = kwargs.get("trade_date")
        start_date = kwargs.get("start_date")
        end_date = kwargs.get("end_date")
        if explicit_trade_date is None and start_date is None and end_date is None:
            raise ValueError("sync_history.margin requires explicit time params: trade_date or start_date+end_date")

        if explicit_trade_date is not None:
            trade_date = self._required_date(explicit_trade_date, field_name="trade_date")
            fetched, written = self._sync_trade_date(
                trade_date=trade_date,
                exchange_ids=exchange_ids,
                execution_id=execution_id,
            )
            return fetched, written, trade_date, f"trade_date={trade_date.isoformat()} exchanges={','.join(exchange_ids)}"

        if start_date is None or end_date is None:
            raise ValueError("sync_history.margin requires both start_date and end_date when trade_date is not provided")
        start = self._required_date(start_date, field_name="start_date")
        end = self._required_date(end_date, field_name="end_date")
        if start > end:
            raise ValueError("start_date must be <= end_date")

        exchange = str(get_settings().default_exchange)
        trade_dates = self.dao.trade_calendar.get_open_dates(exchange, start, end)
        if not trade_dates:
            return 0, 0, end, "区间内无交易日，未执行同步"

        total_units = len(trade_dates) * len(exchange_ids)
        self._update_progress(
            execution_id=execution_id,
            current=0,
            total=total_units,
            message=f"准备按 {len(trade_dates)} 个交易日、{len(exchange_ids)} 个交易所同步融资融券交易汇总。",
        )
        total_fetched = 0
        total_written = 0
        current = 0
        for trade_date in trade_dates:
            for exchange_id in exchange_ids:
                self.ensure_not_canceled(execution_id)
                fetched, written = self._sync_one_exchange(
                    trade_date=trade_date,
                    exchange_id=exchange_id,
                )
                total_fetched += fetched
                total_written += written
                current += 1
                self._update_progress(
                    execution_id=execution_id,
                    current=current,
                    total=total_units,
                    message=(
                        f"margin: {current}/{total_units} trade_date={trade_date.isoformat()} "
                        f"exchange_id={exchange_id} fetched={fetched} written={written}"
                    ),
                )
        return total_fetched, total_written, end, f"trade_dates={len(trade_dates)} exchanges={','.join(exchange_ids)}"

    def _sync_trade_date(
        self,
        *,
        trade_date: date,
        exchange_ids: tuple[str, ...],
        execution_id: int | None,
    ) -> tuple[int, int]:
        total_units = len(exchange_ids)
        self._update_progress(
            execution_id=execution_id,
            current=0,
            total=total_units,
            message=f"准备同步 {trade_date.isoformat()} 的融资融券交易汇总。",
        )
        total_fetched = 0
        total_written = 0
        for index, exchange_id in enumerate(exchange_ids, start=1):
            self.ensure_not_canceled(execution_id)
            fetched, written = self._sync_one_exchange(
                trade_date=trade_date,
                exchange_id=exchange_id,
            )
            total_fetched += fetched
            total_written += written
            self._update_progress(
                execution_id=execution_id,
                current=index,
                total=total_units,
                message=(
                    f"margin: {index}/{total_units} trade_date={trade_date.isoformat()} "
                    f"exchange_id={exchange_id} fetched={fetched} written={written}"
                ),
            )
        return total_fetched, total_written

    def _sync_one_exchange(self, *, trade_date: date, exchange_id: str) -> tuple[int, int]:
        params = {
            "trade_date": trade_date.strftime("%Y%m%d"),
            "exchange_id": exchange_id,
        }
        rows = self.client.call(self.api_name, params=params, fields=self.fields)
        if not rows:
            return 0, 0
        normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
        self.dao.raw_margin.bulk_upsert(normalized)
        written = self.dao.equity_margin.bulk_upsert(normalized)
        return len(rows), written

    @staticmethod
    def _normalize_exchange_ids(value: Any) -> tuple[str, ...]:
        if value in (None, "", []):
            return ALL_MARGIN_EXCHANGE_IDS
        if isinstance(value, str):
            parts = [item.strip().upper() for item in value.split(",") if item.strip()]
        elif isinstance(value, (list, tuple, set)):
            parts = [str(item).strip().upper() for item in value if str(item).strip()]
        else:
            parts = [str(value).strip().upper()]
        if not parts:
            return ALL_MARGIN_EXCHANGE_IDS
        unique_parts = tuple(dict.fromkeys(parts))
        invalid = [item for item in unique_parts if item not in ALL_MARGIN_EXCHANGE_IDS]
        if invalid:
            raise ValueError(f"exchange_id contains unsupported values: {','.join(invalid)}")
        return unique_parts

    @staticmethod
    def _required_date(value: Any, *, field_name: str) -> date:
        parsed = parse_tushare_date(value)
        if parsed is None:
            raise ValueError(f"{field_name} is required")
        return parsed

    def _update_progress(self, *, execution_id: int | None, current: int, total: int, message: str) -> None:
        self._update_execution_progress(execution_id=execution_id, current=current, total=total, message=message)
