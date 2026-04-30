from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class TmpRunSummary:
    path: str
    modified_at: datetime
    age_hours: float
    total_bytes: int
    file_count: int
    empty: bool
    action: str


class TmpCleanupService:
    def __init__(self, lake_root: Path) -> None:
        self.lake_root = lake_root
        self.tmp_root = lake_root / "_tmp"

    def cleanup_run_if_empty(self, run_id: str) -> bool:
        run_dir = self.tmp_root / run_id
        if not run_dir.exists() or not run_dir.is_dir():
            return False
        self._remove_empty_directories(run_dir)
        if run_dir.exists() and not any(run_dir.iterdir()):
            run_dir.rmdir()
            return True
        return False

    def list_runs(self) -> list[TmpRunSummary]:
        if not self.tmp_root.exists():
            return []
        result = []
        for path in sorted(self.tmp_root.iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                continue
            result.append(self._summary(path=path, action="inspect"))
        return result

    def clean(self, *, older_than_hours: float | None, dry_run: bool) -> list[TmpRunSummary]:
        if older_than_hours is None and not dry_run:
            raise ValueError("真实清理必须显式传入 --older-than-hours，避免误删刚失败的任务现场。")
        summaries: list[TmpRunSummary] = []
        for summary in self.list_runs():
            if older_than_hours is not None and summary.age_hours < older_than_hours:
                summaries.append(_replace_action(summary, "skip_too_new"))
                continue
            if dry_run:
                summaries.append(_replace_action(summary, "would_delete"))
                continue
            shutil.rmtree(summary.path)
            summaries.append(_replace_action(summary, "deleted"))
        return summaries

    def _summary(self, *, path: Path, action: str) -> TmpRunSummary:
        files = [item for item in path.rglob("*") if item.is_file()]
        total_bytes = sum(item.stat().st_size for item in files)
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - modified_at).total_seconds() / 3600
        return TmpRunSummary(
            path=str(path),
            modified_at=modified_at,
            age_hours=round(age_hours, 3),
            total_bytes=total_bytes,
            file_count=len(files),
            empty=len(files) == 0,
            action=action,
        )

    def _remove_empty_directories(self, root: Path) -> None:
        if not root.exists():
            return
        for child in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if child.is_dir() and not any(child.iterdir()):
                child.rmdir()


def _replace_action(summary: TmpRunSummary, action: str) -> TmpRunSummary:
    return TmpRunSummary(
        path=summary.path,
        modified_at=summary.modified_at,
        age_hours=summary.age_hours,
        total_bytes=summary.total_bytes,
        file_count=summary.file_count,
        empty=summary.empty,
        action=action,
    )
