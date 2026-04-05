from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select

from src.foundation.config.settings import get_settings
from src.foundation.models.core.dc_index import DcIndex
from src.ops.models.ops.job_execution import JobExecution
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.foundation.services.sync.fields import DC_DAILY_FIELDS
from src.foundation.services.sync.sync_dc_index_service import SyncDcIndexService
from src.utils import coerce_row


def build_dc_daily_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {
            "ts_code": kwargs.get("ts_code"),
            "start_date": (kwargs.get("start_date") or settings.history_start_date).replace("-", ""),
            "end_date": kwargs.get("end_date", "").replace("-", "") if kwargs.get("end_date") else None,
            "idx_type": kwargs.get("idx_type"),
        }
        return {key: value for key, value in params.items() if value}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental dc_daily sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "idx_type": kwargs.get("idx_type"),
    }
    return {key: value for key, value in params.items() if value}


class SyncDcDailyService(BaseSyncService):
    job_name = "sync_dc_daily"
    target_table = "core.dc_daily"
    fields = DC_DAILY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("close", "open", "high", "low", "change", "pct_change", "vol", "amount", "swing", "turnover_rate")

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.client = SyncDcIndexService(session).client

    def execute(self, run_type: str, **kwargs):  # type: ignore[no-untyped-def]
        trade_date = kwargs.get("trade_date")
        execution_id = kwargs.get("execution_id")
        self.ensure_not_canceled(execution_id)

        direct_kwargs = {key: value for key, value in kwargs.items() if key != "trade_date"}
        direct_params = build_dc_daily_params(run_type, trade_date=trade_date, **direct_kwargs)
        if direct_params.get("ts_code"):
            fetched, written = self._sync_daily_slice(direct_params)
            self._update_progress(
                execution_id=execution_id,
                current=1,
                total=1,
                message=f"已完成定向同步：{direct_params['ts_code']}",
            )
            return fetched, written, trade_date, None

        idx_type = kwargs.get("idx_type")
        if run_type == "FULL":
            start_date = kwargs.get("start_date")
            end_date = kwargs.get("end_date")
            parsed_start_date = self._normalize_date(start_date)
            parsed_end_date = self._normalize_date(end_date)
            SyncDcIndexService(self.session).run_full(
                start_date=start_date,
                end_date=end_date,
                idx_type=idx_type,
            )
            stmt = select(DcIndex.ts_code)
            if parsed_start_date:
                stmt = stmt.where(DcIndex.trade_date >= parsed_start_date)
            if parsed_end_date:
                stmt = stmt.where(DcIndex.trade_date <= parsed_end_date)
            if idx_type:
                stmt = stmt.where(DcIndex.idx_type == idx_type)
            board_codes = list(self.session.scalars(stmt.distinct().order_by(DcIndex.ts_code)))
        else:
            if trade_date is None:
                raise ValueError("trade_date is required for incremental dc_daily sync")
            SyncDcIndexService(self.session).run_incremental(trade_date=trade_date, idx_type=idx_type)
            stmt = select(DcIndex.ts_code).where(DcIndex.trade_date == trade_date)
            if idx_type:
                stmt = stmt.where(DcIndex.idx_type == idx_type)
            board_codes = list(self.session.scalars(stmt.distinct().order_by(DcIndex.ts_code)))

        total_fetched = 0
        total_written = 0
        total_boards = len(board_codes)
        self._update_progress(
            execution_id=execution_id,
            current=0,
            total=total_boards,
            message=f"准备按 {total_boards} 个东方财富板块逐个同步行情。",
        )
        for index, board_code in enumerate(board_codes, start=1):
            self.ensure_not_canceled(execution_id)
            params = build_dc_daily_params(
                run_type,
                trade_date=trade_date,
                ts_code=board_code,
                start_date=kwargs.get("start_date"),
                end_date=kwargs.get("end_date"),
            )
            fetched, written = self._sync_daily_slice(params)
            total_fetched += fetched
            total_written += written
            self._update_progress(
                execution_id=execution_id,
                current=index,
                total=total_boards,
                message=f"正在同步东方财富板块行情：{index}/{total_boards} {board_code}",
            )
        return total_fetched, total_written, trade_date, f"boards={len(board_codes)}"

    def _sync_daily_slice(self, params: dict[str, str]) -> tuple[int, int]:
        rows = self.client.call("dc_daily", params=params, fields=self.fields)
        normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
        self.dao.raw_dc_daily.bulk_upsert(normalized)
        written = self.dao.dc_daily.bulk_upsert(normalized)
        return len(rows), written

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

    @staticmethod
    def _normalize_date(value: date | str | None) -> date | None:
        if value is None:
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(value)
