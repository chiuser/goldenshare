from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ManifestService:
    def __init__(self, lake_root: Path) -> None:
        self.lake_root = lake_root

    def append_sync_run(self, payload: dict[str, Any]) -> None:
        manifest_dir = self.lake_root / "manifest"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        row = {
            **payload,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        with (manifest_dir / "sync_runs.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
