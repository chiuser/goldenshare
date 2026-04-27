from __future__ import annotations

from typing import Any, Protocol


class IngestionRunContext(Protocol):
    """数据维护运行上下文 contract。

    用于 foundation 在不依赖 ops ORM 模型的前提下，完成：
    1. 取消检查
    2. 进度写回
    """

    def is_cancel_requested(self, *, run_id: int) -> bool:
        """返回该任务是否已收到取消请求。"""

    def update_progress(
        self,
        *,
        run_id: int,
        current: int,
        total: int,
        message: str,
        rows_fetched: int | None = None,
        rows_saved: int | None = None,
        rows_rejected: int | None = None,
        current_object: dict[str, Any] | None = None,
    ) -> None:
        """持久化任务进度。"""
