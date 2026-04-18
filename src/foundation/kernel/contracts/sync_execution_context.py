from __future__ import annotations

from typing import Protocol


class SyncExecutionContext(Protocol):
    """同步任务执行上下文 contract。

    用于 foundation 在不依赖 ops ORM 模型的前提下，完成：
    1. 取消检查
    2. 进度写回
    """

    def is_cancel_requested(self, *, execution_id: int) -> bool:
        """返回该 execution 是否已收到取消请求。"""

    def update_progress(
        self,
        *,
        execution_id: int,
        current: int,
        total: int,
        message: str,
    ) -> None:
        """持久化 execution 进度。"""

