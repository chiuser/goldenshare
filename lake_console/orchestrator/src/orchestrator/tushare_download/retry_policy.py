"""Finite same-page retries with business-owned cancellation and no rate coordinator."""

from __future__ import annotations

import math
from dataclasses import replace
from email.utils import parsedate_to_datetime

from .download_errors import DownloadError
from .download_errors import DownloadErrorCode as Code


def retry_after_at(value, clock):
    if value is None:
        return None
    try:
        seconds = float(value)
        if not math.isfinite(seconds) or seconds < 0:
            return None
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                return None
            seconds = max(0.0, (target - clock.utc_now()).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    return clock.monotonic() + seconds


class RetryPolicy:
    def __init__(self, config, clock, sleep_fn):
        self.config, self.clock, self.sleep_fn = config, clock, sleep_fn

    def can_retry(self, failure, attempt_number):
        return (
            not failure.cleanup_errors
            and failure.code
            in (Code.RATE_LIMIT, Code.TRANSIENT_SOURCE, Code.NO_VALID_RESPONSE)
            and attempt_number <= self.config.max_retries
        )

    def retry_at(self, failure, attempt_number, now):
        return max(
            now + self.config.retry_backoff_seconds[attempt_number - 1],
            failure.retry_after_at or now,
        )

    def wait_until(self, retry_at, control):
        start = self.clock.monotonic()
        while True:
            control.raise_if_cancelled()
            remaining = retry_at - self.clock.monotonic()
            if remaining <= 0:
                return self.clock.monotonic() - start
            self.sleep_fn(min(remaining, self.config.poll_interval_seconds))

    def to_download_error(self, failure, attempt_number, *, location):
        exhausted = (
            not failure.cleanup_errors
            and failure.code
            in (Code.RATE_LIMIT, Code.TRANSIENT_SOURCE, Code.NO_VALID_RESPONSE)
            and attempt_number > self.config.max_retries
        )
        details = replace(
            location,
            code=failure.code,
            attempt_number=attempt_number,
            source_status=failure.source_status,
            source_code=failure.source_code,
            cause_type=failure.cause_type,
            cleanup_errors=failure.cleanup_errors,
            retry_exhausted=exhausted,
        )
        return DownloadError(failure.code, details=details)
