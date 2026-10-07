"""A request's shared read deadline; background preparation retains per-unit budgets."""
from contextlib import contextmanager
from contextvars import ContextVar
import time
from .core import Blocked

_deadline=ContextVar('announcement_read_deadline',default=None)


def remaining(seconds):
    deadline=_deadline.get()
    if deadline is not None:
        seconds=min(seconds,deadline-time.monotonic())
    if seconds<=0:
        raise Blocked('query_sql_timeout')
    return seconds


@contextmanager
def read_budget(seconds):
    token=_deadline.set(time.monotonic()+seconds)
    try:
        yield
        remaining(seconds)
    finally:
        _deadline.reset(token)
