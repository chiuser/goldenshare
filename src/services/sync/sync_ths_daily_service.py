from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select

from src.config.settings import get_settings
from src.models.core.ths_index import ThsIndex
from src.models.ops.job_execution import JobExecution
from src.services.sync.base_sync_service import BaseSyncService
from src.services.sync.fields import THS_DAILY_FIELDS
from src.services.sync.sync_ths_index_service import SyncThsIndexService
from src.utils import coerce_row


def build_ths_daily_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {
            "ts_code": kwargs.get("ts_code"),
            "start_date": (kwargs.get("start_date") or settings.history_start_date).replace("-", ""),
            "end_date": kwargs.get("end_date", "").replace("-", "") if kwargs.get("end_date") else None,
        }
        return {key: value for key, value in params.items() if value}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental ths_daily sync")
    params = {"trade_date": trade_date.strftime("%Y%m%d")}
    if kwargs.get("ts_code"):
        params["ts_code"] = kwargs["ts_code"]
    return params


class SyncThsDailyService(BaseSyncService):
    job_name = "sync_ths_daily"
    target_table = "core.ths_daily"
    fields = THS_DAILY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = (
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "avg_price",
        "change",
        "pct_change",
        "vol",
        "turnover_rate",
        "total_mv",
        "float_mv",
    )

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.client = SyncThsIndexService(session).client

    def execute(self, run_type: str, **kwargs):  # type: ignore[no-untyped-def]
        trade_date = kwargs.get("trade_date")
        execution_id = kwargs.get("execution_id")
        self.ensure_not_canceled(execution_id)

        extra_kwargs = {key: value for key, value in kwargs.items() if key != "trade_date"}
        direct_params = build_ths_daily_params(run_type, trade_date=trade_date, **extra_kwargs)
        if direct_params.get("ts_code"):
            fetched, written = self._sync_daily_slice(direct_params)
            self._update_progress(
                execution_id=execution_id,
                current=1,
                total=1,
                message=f"已完成定向同步：{direct_params['ts_code']}",
            )
            return fetched, written, trade_date, None

        if run_type == "FULL":
            start_date = kwargs.get("start_date")
            end_date = kwargs.get("end_date")
            parsed_start_date = self._normalize_date(start_date)
            parsed_end_date = self._normalize_date(end_date)
            SyncThsIndexService(self.session).run_full()
            stmt = select(ThsIndex.ts_code)
            if parsed_start_date:
                stmt = stmt.where(ThsIndex.list_date.is_(None) | (ThsIndex.list_date <= parsed_start_date))
            board_codes = list(self.session.scalars(stmt.distinct().order_by(ThsIndex.ts_code)))
        else:
            if trade_date is None:
                raise ValueError("trade_date is required for incremental ths_daily sync")
            SyncThsIndexService(self.session).run_full()
            board_codes = list(self.session.scalars(select(ThsIndex.ts_code).order_by(ThsIndex.ts_code)))
            start_date = trade_date.isoformat()
            end_date = trade_date.isoformat()
            parsed_end_date = self._normalize_date(end_date)

        total_fetched = 0
        total_written = 0
        total_boards = len(board_codes)
        self._update_progress(
            execution_id=execution_id,
            current=0,
            total=total_boards,
            message=f"准备按 {total_boards} 个同花顺板块逐个同步行情。",
        )
        for index, board_code in enumerate(board_codes, start=1):
            self.ensure_not_canceled(execution_id)
            params = build_ths_daily_params(
                "FULL",
                ts_code=board_code,
                start_date=start_date,
                end_date=end_date,
            )
            fetched, written = self._sync_daily_slice(params)
            total_fetched += fetched
            total_written += written
            self._update_progress(
                execution_id=execution_id,
                current=index,
                total=total_boards,
                message=f"正在同步同花顺板块行情：{index}/{total_boards} {board_code}",
            )
        return total_fetched, total_written, parsed_end_date, f"boards={len(board_codes)}"

    def _sync_daily_slice(self, params: dict[str, str]) -> tuple[int, int]:
        rows = self.client.call("ths_daily", params=params, fields=self.fields)
        normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
        self.dao.raw_ths_daily.bulk_upsert(normalized)
        written = self.dao.ths_daily.bulk_upsert(normalized)
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
