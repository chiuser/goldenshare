from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lake_console.backend.app.services.tushare_client import TushareLakeClient


@dataclass(frozen=True)
class LakeSyncContext:
    lake_root: Path
    client: TushareLakeClient
