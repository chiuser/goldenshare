"""Injected transaction boundary; Biz never imports application DB settings."""
from typing import Callable, Protocol, TypeVar
from sqlalchemy.orm import Session
from .execution_policy import Deadline

T = TypeVar("T")


class CommitOutcomeUnknown(RuntimeError):
    """Commit was attempted; use the retained request receipt to resolve outcome."""


class TransactionRunner(Protocol):
    async def run(self, work: Callable[[Session], T], *, deadline: Deadline, write: bool) -> T: ...
