from __future__ import annotations

from datetime import date
from typing import Protocol


class IngestionRunRecorder(Protocol):
    """数据维护运行过程记录 contract。"""

    def start_run(self, *, dataset_key: str, run_mode: str, run_id: int | None = None) -> object:
        """开始一次数据维护过程并返回句柄。"""

    def finish_run(
        self,
        *,
        handle: object,
        status: str,
        rows_fetched: int,
        rows_written: int,
        message: str | None = None,
    ) -> None:
        """结束一次数据维护过程。"""


class IngestionResultStore(Protocol):
    """数据维护结果写入 contract。当前默认实现为无副作用 no-op。"""

    def record_run_outcome(
        self,
        *,
        dataset_key: str,
        target_table: str,
        run_mode: str,
        run_profile: str | None = None,
        last_success_date: date | None = None,
        rows_committed: int | None = None,
    ) -> None:
        """一次性记录执行成功结果。"""
