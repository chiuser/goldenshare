from __future__ import annotations

from datetime import date
from typing import Protocol


class SyncRunLogStore(Protocol):
    """同步运行日志写入 contract。"""

    def start_log(self, *, job_name: str, run_type: str, execution_id: int | None = None) -> object:
        """开始一条运行日志并返回句柄。"""

    def finish_log(
        self,
        *,
        log: object,
        status: str,
        rows_fetched: int,
        rows_written: int,
        message: str | None = None,
    ) -> None:
        """结束运行日志并写回结果。"""


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

