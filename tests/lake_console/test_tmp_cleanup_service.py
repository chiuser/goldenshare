from __future__ import annotations

import os
import time

import pytest

from lake_console.backend.app.services.tmp_cleanup_service import TmpCleanupService


def test_cleanup_run_if_empty_removes_empty_run_tree(tmp_path):
    run_dir = tmp_path / "_tmp" / "run-1" / "nested"
    run_dir.mkdir(parents=True)

    removed = TmpCleanupService(tmp_path).cleanup_run_if_empty("run-1")

    assert removed is True
    assert not (tmp_path / "_tmp" / "run-1").exists()


def test_cleanup_run_if_empty_keeps_non_empty_run_tree(tmp_path):
    run_dir = tmp_path / "_tmp" / "run-1" / "nested"
    run_dir.mkdir(parents=True)
    (run_dir / "part.parquet").write_text("data", encoding="utf-8")

    removed = TmpCleanupService(tmp_path).cleanup_run_if_empty("run-1")

    assert removed is False
    assert (run_dir / "part.parquet").exists()


def test_clean_tmp_requires_age_for_real_delete(tmp_path):
    service = TmpCleanupService(tmp_path)

    with pytest.raises(ValueError):
        service.clean(older_than_hours=None, dry_run=False)


def test_clean_tmp_dry_run_and_age_delete(tmp_path):
    run_dir = tmp_path / "_tmp" / "old-run"
    run_dir.mkdir(parents=True)
    (run_dir / "part.parquet").write_text("data", encoding="utf-8")
    old_timestamp = time.time() - 48 * 3600
    os.utime(run_dir, (old_timestamp, old_timestamp))

    dry_run = TmpCleanupService(tmp_path).clean(older_than_hours=24, dry_run=True)
    deleted = TmpCleanupService(tmp_path).clean(older_than_hours=24, dry_run=False)

    assert dry_run[0].action == "would_delete"
    assert deleted[0].action == "deleted"
    assert not run_dir.exists()
