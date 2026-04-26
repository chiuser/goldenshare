from __future__ import annotations

from datetime import date
from typing import Protocol


class SyncRunRecorder(Protocol):
    """同步运行过程记录 contract。"""

    def start_run(self, *, job_name: str, run_type: str, execution_id: int | None = None) -> object:
        """开始一次同步过程并返回句柄。"""

    def finish_run(
        self,
        *,
        handle: object,
        status: str,
        rows_fetched: int,
        rows_written: int,
        message: str | None = None,
    ) -> None:
        """结束一次同步过程。"""


class SyncJobStateStore(Protocol):
    """同步任务状态写入 contract。"""

    def get_last_success_date(self, *, job_name: str) -> date | None:
        """获取该任务最近成功业务日。"""

    def mark_success(
        self,
        *,
        job_name: str,
        target_table: str,
        last_success_date: date | None = None,
        last_cursor: str | None = None,
    ) -> None:
        """标记任务成功。"""

    def reconcile_success_date(
        self,
        *,
        job_name: str,
        target_table: str,
        last_success_date: date,
    ) -> None:
        """按观测值对齐最近成功业务日。"""

    def mark_full_sync_done(self, *, job_name: str, target_table: str) -> None:
        """标记全量同步完成。"""

    def record_execution_outcome(
        self,
        *,
        job_name: str,
        target_table: str,
        run_type: str,
        run_profile: str | None = None,
        last_success_date: date | None = None,
        last_cursor: str | None = None,
        rows_committed: int | None = None,
    ) -> None:
        """一次性记录执行成功结果，避免分裂状态写入同一资源行。"""
