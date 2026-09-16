"""Suppress third-party HTTP diagnostics only within a credential-bearing call.

httpcore DEBUG can log remote headers and exception bytes, not only the URL.
Do not globally silence other modules' HTTP logs or try to redact known secrets
after formatting them. ContextVars preserve concurrent unrelated diagnostics.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import logging

_private_call = ContextVar("ta_private_notification_io", default=False)


class _PrivateCallFilter(logging.Filter):
    def filter(self, record):
        return not _private_call.get()


def install_notification_log_guard():
    # This adapter only enables direct HTTP/1.1; no proxy or HTTP/2 is enabled.
    for name in ("httpx", "httpcore.connection", "httpcore.http11"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, _PrivateCallFilter) for f in logger.filters):
            logger.addFilter(_PrivateCallFilter())


@contextmanager
def private_notification_io():
    token = _private_call.set(True)
    try:
        yield
    finally:
        _private_call.reset(token)
