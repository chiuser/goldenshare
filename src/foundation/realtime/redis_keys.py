from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RealtimeRedisKeys:
    feed_key: str

    @property
    def prefix(self) -> str:
        return f"rt:feed:{self.feed_key}"

    def current_batch(self) -> str:
        return f"{self.prefix}:current_batch"

    def batch_snapshot(self, batch_id: str, ts_code: str) -> str:
        return f"{self.prefix}:batch:{batch_id}:snapshot:{ts_code}"

    def batch_index(self, batch_id: str) -> str:
        return f"{self.prefix}:batch:{batch_id}:index"

    def batch_meta(self, batch_id: str) -> str:
        return f"{self.prefix}:batch:{batch_id}:meta"

    def batches(self) -> str:
        return f"{self.prefix}:batches"

    def batch_stream(self) -> str:
        return f"{self.prefix}:stream:batch"

    def delta_stream(self) -> str:
        return f"{self.prefix}:stream:delta"

    def health(self) -> str:
        return f"{self.prefix}:health"

    def lease(self) -> str:
        return f"{self.prefix}:lease"
