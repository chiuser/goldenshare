"""Stable downloader errors; source exceptions and credentials are never retained."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .download_models import (
        CleanupIssue,
        DownloadScope,
        DownloadStage,
        PagePosition,
    )


class DownloadErrorCode(IntEnum):
    CONFIGURATION = 1001
    CONTRACT = 1101
    INPUT = 1102
    PERMISSION_OR_PARAMETER = 1201
    RATE_LIMIT = 1202
    TRANSIENT_SOURCE = 1203
    NO_VALID_RESPONSE = 1204
    SOURCE_PROTOCOL = 1205
    CAPACITY = 1302
    CLEANUP = 1304
    CANCELLED = 1401
    UNCLASSIFIED_SOURCE = 1501


@dataclass(frozen=True, slots=True)
class ErrorDetails:
    code: DownloadErrorCode | None = None
    stage: DownloadStage | None = None
    contract_name: str | None = None
    contract_version: str | None = None
    task_id: str | None = None
    unit_id: str | None = None
    current_scope: DownloadScope | None = None
    source_position: PagePosition | None = None
    attempt_number: int | None = None
    source_status: int | None = None
    source_code: int | None = None
    retry_exhausted: bool = False
    cleanup_errors: tuple[CleanupIssue, ...] = ()
    cause_type: str | None = None


class DownloadError(Exception):
    def __init__(self, code: DownloadErrorCode, *, details: ErrorDetails | None = None):
        if not isinstance(code, DownloadErrorCode):
            raise TypeError("DownloadErrorCode is required")
        self._details = replace(details or ErrorDetails(), code=code)
        super().__init__(f"tushare download: {code.name} ({int(code)})")

    @property
    def details(self) -> ErrorDetails:
        return self._details

    @property
    def code(self) -> DownloadErrorCode:
        return self._details.code

    def __getattr__(self, name):
        if name in ErrorDetails.__dataclass_fields__:
            return getattr(self._details, name)
        raise AttributeError(name)


class DownloadCancelled(DownloadError):
    def __init__(self, *, details: ErrorDetails | None = None):
        super().__init__(DownloadErrorCode.CANCELLED, details=details)


def capacity_error(*, estimated: bool) -> DownloadError:
    error = DownloadError(DownloadErrorCode.CAPACITY)
    reason = "预计工作空间不足" if estimated else "实际工作空间超限"
    error.args = (f"{error}: {reason}",)
    return error


def require(
    condition: bool, code: DownloadErrorCode = DownloadErrorCode.CONTRACT
) -> None:
    if not condition:
        raise DownloadError(code)
