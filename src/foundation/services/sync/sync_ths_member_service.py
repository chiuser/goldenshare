from __future__ import annotations

from datetime import date
from datetime import datetime, timezone

from sqlalchemy import select

from src.foundation.models.core.ths_index import ThsIndex
from src.ops.models.ops.job_execution import JobExecution
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.foundation.services.sync.fields import THS_MEMBER_FIELDS
from src.foundation.services.sync.sync_ths_index_service import SyncThsIndexService
from src.utils import coerce_row


def build_ths_member_params(run_type: str, **kwargs):  # type: ignore[no-untyped-def]
    params = {
        "ts_code": kwargs.get("ts_code"),
        "con_code": kwargs.get("con_code"),
    }
    return {key: value for key, value in params.items() if value not in (None, "")}


class SyncThsMemberService(BaseSyncService):
    job_name = "sync_ths_member"
    target_table = "core.ths_member"
    fields = THS_MEMBER_FIELDS
    date_fields = ("in_date", "out_date")
    decimal_fields = ("weight",)

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.client = SyncThsIndexService(session).client

    def execute(self, run_type: str, **kwargs):  # type: ignore[no-untyped-def]
        execution_id = kwargs.get("execution_id")
        self.ensure_not_canceled(execution_id)
        params = build_ths_member_params(run_type, **kwargs)
        if params:
            fetched, written = self._sync_member_slice(params)
            self._update_progress(
                execution_id=execution_id,
                current=1,
                total=1,
                message=f"已完成定向同步：{params.get('ts_code') or params.get('con_code')}",
            )
            return fetched, written, None, None

        SyncThsIndexService(self.session).run_full()
        board_codes = list(self.session.scalars(select(ThsIndex.ts_code).order_by(ThsIndex.ts_code)))
        total_fetched = 0
        total_written = 0
        total_boards = len(board_codes)
        self._update_progress(
            execution_id=execution_id,
            current=0,
            total=total_boards,
            message=f"准备按 {total_boards} 个同花顺板块逐个同步成分。",
        )
        for index, board_code in enumerate(board_codes, start=1):
            self.ensure_not_canceled(execution_id)
            fetched, written = self._sync_member_slice({"ts_code": board_code})
            total_fetched += fetched
            total_written += written
            self._update_progress(
                execution_id=execution_id,
                current=index,
                total=total_boards,
                message=f"正在同步同花顺板块成分：{index}/{total_boards} {board_code}",
            )
        return total_fetched, total_written, None, f"boards={len(board_codes)}"

    def _sync_member_slice(self, params: dict[str, str]) -> tuple[int, int]:
        rows = self.client.call("ths_member", params=params, fields=self.fields)
        normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
        self.dao.raw_ths_member.bulk_upsert(normalized)
        written = self.dao.ths_member.bulk_upsert(normalized)
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
