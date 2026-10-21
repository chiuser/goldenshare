"""Synchronous Tushare download tool. Importing performs no configuration or IO."""

from .download_api import TushareDownloader
from .download_errors import (
    DownloadCancelled,
    DownloadError,
    DownloadErrorCode,
    ErrorDetails,
)
from .download_models import (
    DownloadControl,
    DownloadMode,
    DownloadProgress,
    DownloadProgressEvent,
    DownloadScope,
    DownloadStage,
    DownloadStatus,
    DownloadSummary,
    DownloadTask,
    DownloadUnit,
    ObjectTimeRange,
    PagePosition,
    ProgressCallback,
    SourceRecord,
    TimeRange,
    UnitResult,
)

__all__ = [
    "DownloadCancelled",
    "DownloadControl",
    "DownloadError",
    "DownloadErrorCode",
    "DownloadMode",
    "DownloadProgress",
    "DownloadProgressEvent",
    "DownloadScope",
    "DownloadStage",
    "DownloadStatus",
    "DownloadSummary",
    "DownloadTask",
    "DownloadUnit",
    "ErrorDetails",
    "ObjectTimeRange",
    "PagePosition",
    "ProgressCallback",
    "SourceRecord",
    "TimeRange",
    "TushareDownloader",
    "UnitResult",
]
