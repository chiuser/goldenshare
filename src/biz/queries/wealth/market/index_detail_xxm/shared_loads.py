from concurrent.futures import Future
from threading import Lock


class SharedLoads:
    """Coalesce only overlapping work; never use a completed flight as a TTL cache."""

    def __init__(self, *, max_entries: int):
        self.max_entries = max_entries
        self._pending: dict[tuple, Future] = {}
        self._lock = Lock()

    def load(self, key, loader, remaining):
        with self._lock:
            future = self._pending.get(key)
            leader = future is None
            if leader:
                if len(self._pending) >= self.max_entries:
                    raise TimeoutError("共享加载等待数超过预算。")
                future = Future()
                self._pending[key] = future
        if not leader:
            value = future.result(timeout=remaining())
            remaining()
            return value
        try:
            value = loader()
            remaining()
            future.set_result(value)
            return value
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                del self._pending[key]
