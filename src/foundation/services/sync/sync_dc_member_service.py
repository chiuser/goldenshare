from __future__ import annotations

from datetime import date
from datetime import datetime, timezone

from sqlalchemy import select

from src.foundation.models.core.dc_index import DcIndex
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.foundation.services.sync.fields import DC_MEMBER_FIELDS
from src.foundation.services.sync.sync_dc_index_service import SyncDcIndexService
from src.utils import coerce_row


def build_dc_member_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    params = {
        "trade_date": trade_date.strftime("%Y%m%d") if trade_date else None,
        "ts_code": kwargs.get("ts_code"),
        "con_code": kwargs.get("con_code"),
    }
    return {key: value for key, value in params.items() if value}


class SyncDcMemberService(BaseSyncService):
    job_name = "sync_dc_member"
    target_table = "core_serving.dc_member"
    fields = DC_MEMBER_FIELDS
    date_fields = ("trade_date",)

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.client = SyncDcIndexService(session).client

    def execute(self, run_type: str, **kwargs):  # type: ignore[no-untyped-def]
        trade_date = kwargs.get("trade_date")
        execution_id = kwargs.get("execution_id")
        self.ensure_not_canceled(execution_id)
        extra_kwargs = {key: value for key, value in kwargs.items() if key != "trade_date"}
        params = build_dc_member_params(run_type, trade_date=trade_date, **extra_kwargs)
        if params.get("ts_code") or params.get("con_code"):
            fetched, written = self._sync_member_slice(params)
            self._update_progress(
                execution_id=execution_id,
                current=1,
                total=1,
                message=f"已完成定向同步：{params.get('ts_code') or params.get('con_code')}",
            )
            return fetched, written, trade_date, None

        if trade_date is None:
            raise ValueError("东方财富板块成分同步需要指定交易日期，或使用具体板块代码定向同步。")

        SyncDcIndexService(self.session).run_incremental(trade_date=trade_date, idx_type=kwargs.get("idx_type"))
        stmt = select(DcIndex.ts_code).where(DcIndex.trade_date == trade_date)
        if kwargs.get("idx_type"):
            stmt = stmt.where(DcIndex.idx_type == kwargs["idx_type"])
        board_codes = list(self.session.scalars(stmt.distinct().order_by(DcIndex.ts_code)))

        total_fetched = 0
        total_written = 0
        total_boards = len(board_codes)
        self._update_progress(
            execution_id=execution_id,
            current=0,
            total=total_boards,
            message=f"准备按 {total_boards} 个东方财富板块逐个同步成分。",
        )
        for index, board_code in enumerate(board_codes, start=1):
            self.ensure_not_canceled(execution_id)
            fetched, written = self._sync_member_slice(
                build_dc_member_params(run_type, trade_date=trade_date, ts_code=board_code)
            )
            total_fetched += fetched
            total_written += written
            self._update_progress(
                execution_id=execution_id,
                current=index,
                total=total_boards,
                message=f"正在同步东方财富板块成分：{index}/{total_boards} {board_code}",
            )
        return total_fetched, total_written, trade_date, f"boards={len(board_codes)}"

    def _sync_member_slice(self, params: dict[str, str]) -> tuple[int, int]:
        rows = self.client.call("dc_member", params=params, fields=self.fields)
        normalized = [coerce_row(row, self.date_fields, ()) for row in rows]
        self.dao.raw_dc_member.bulk_upsert(normalized)
        written = self.dao.dc_member.bulk_upsert(normalized)
        return len(rows), written

    def _update_progress(self, *, execution_id: int | None, current: int, total: int, message: str) -> None:
        self._update_execution_progress(execution_id=execution_id, current=current, total=total, message=message)
