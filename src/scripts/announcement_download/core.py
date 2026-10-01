from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path


class DownloadError(Exception):
    """A safe reason code, never a raw network/DB exception containing credentials."""


class Blocked(DownloadError):
    pass


class FileFailed(DownloadError):
    pass


class Retryable(FileFailed):
    def __init__(self, reason: str, retry_after: float = 0):
        super().__init__(reason)
        self.retry_after = retry_after


class Cancelled(DownloadError):
    pass


@dataclass(frozen=True)
class DownloadPolicy:
    batch_size: int = 500
    db_timeout_ms: int = 15_000
    volume_timeout: float = 10
    chunk_size: int = 64 * 1024
    max_file_size: int = 512 * 1024 * 1024
    reserve_bytes: int = 1024 * 1024 * 1024
    connect_timeout: float = 10
    read_timeout: float = 15
    write_timeout: float = 15
    pool_timeout: float = 5
    transfer_deadline: float = 600
    attempts: int = 3
    redirects: int = 5
    backoff_seconds: float = 30
    filename_bytes: int = 200
    progress_seconds: float = 5
    wait_slice: float = 0.5


@dataclass(frozen=True)
class DownloadOptions:
    start_date: date
    end_date: date
    interval_seconds: float = 5
    output_root: Path = Path('/Volumes/datasource/announcements')

    def __post_init__(self):
        if self.end_date < self.start_date:
            raise ValueError('date_range_reversed')
        if not math.isfinite(self.interval_seconds) or self.interval_seconds < 0:
            raise ValueError('invalid_interval')


def iso_date(value: str) -> date:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('expected_YYYY-MM-DD')
    return date.fromisoformat(value)


def identity(parts: list[str]) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class Control:
    def __init__(self, policy: DownloadPolicy, emit=print):
        self.policy = policy
        self.emit = emit
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.view: dict = {'phase': 'startup', 'eta': '暂无法估算'}
        self.thread: threading.Thread | None = None

    def check(self):
        if self.stop.is_set():
            raise Cancelled('user_cancelled')

    def update(self, **values):
        with self.lock:
            self.view.update(values)
        self.report()

    def report(self):
        with self.lock:
            data = dict(self.view, updated_at=timestamp())
        self.emit(json.dumps(data, ensure_ascii=False))

    def start(self):
        def heartbeat():
            while not self.stop.wait(self.policy.progress_seconds):
                self.report()
        self.thread = threading.Thread(target=heartbeat, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)

    def wait(self, seconds: float):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check()
            self.stop.wait(min(self.policy.wait_slice, end - time.monotonic()))
        self.check()
