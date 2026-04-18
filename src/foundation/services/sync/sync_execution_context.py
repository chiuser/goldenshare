from __future__ import annotations

from src.foundation.kernel.contracts.sync_execution_context import SyncExecutionContext


class NullSyncExecutionContext(SyncExecutionContext):
    """foundation 默认实现：不感知上层执行表语义。"""

    def is_cancel_requested(self, *, execution_id: int) -> bool:
        return False

    def update_progress(
        self,
        *,
        execution_id: int,
        current: int,
        total: int,
        message: str,
    ) -> None:
        return None
