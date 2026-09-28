from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import resource
import time
from typing import Callable


@dataclass(frozen=True, slots=True)
class ResourceSample:
    captured_at: str
    stage: str
    wall_seconds: float
    self_max_rss_kib: int
    child_max_rss_kib: int


class StageResourceMonitor:
    def __init__(self, sink: Callable[[ResourceSample], None]) -> None:
        self._sink = sink

    def measure(self, stage: str):
        return _Measurement(stage, self._sink)


class _Measurement:
    def __init__(self, stage: str, sink: Callable[[ResourceSample], None]) -> None:
        self._stage = stage
        self._sink = sink
        self._started = 0.0

    def __enter__(self) -> "_Measurement":
        self._started = time.monotonic()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self_usage = resource.getrusage(resource.RUSAGE_SELF)
        child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        self._sink(
            ResourceSample(
                captured_at=datetime.now(timezone.utc).isoformat(),
                stage=self._stage,
                wall_seconds=time.monotonic() - self._started,
                self_max_rss_kib=int(self_usage.ru_maxrss),
                child_max_rss_kib=int(child_usage.ru_maxrss),
            )
        )
        return False
