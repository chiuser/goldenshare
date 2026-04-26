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


class SyncExecutionResultStore(Protocol):
    """同步执行结果写入 contract。当前默认实现为无副作用 no-op。"""

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
        """一次性记录执行成功结果。"""
