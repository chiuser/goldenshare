from __future__ import annotations

from pathlib import Path

import pytest

from lake_console.backend.app.services.parquet_writer import replace_directory_atomically, replace_file_atomically


def test_replace_file_atomically_rolls_back_existing_file_when_tmp_publish_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_file = tmp_path / "_tmp" / "part-000.parquet"
    final_file = tmp_path / "final" / "part-000.parquet"
    backup_root = tmp_path / "_backup"

    tmp_file.parent.mkdir(parents=True)
    final_file.parent.mkdir(parents=True)
    tmp_file.write_text("new", encoding="utf-8")
    final_file.write_text("old", encoding="utf-8")

    original_replace = Path.replace

    def fail_tmp_publish(self: Path, target: Path) -> Path:
        if self == tmp_file:
            raise RuntimeError("publish failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_tmp_publish)

    with pytest.raises(RuntimeError, match="publish failed"):
        replace_file_atomically(tmp_file=tmp_file, final_file=final_file, backup_root=backup_root)

    assert final_file.read_text(encoding="utf-8") == "old"
    assert tmp_file.read_text(encoding="utf-8") == "new"
    assert not (backup_root / final_file.name).exists()


def test_replace_file_atomically_replaces_existing_file_and_removes_backup(tmp_path: Path) -> None:
    tmp_file = tmp_path / "_tmp" / "part-000.parquet"
    final_file = tmp_path / "final" / "part-000.parquet"
    backup_root = tmp_path / "_backup"

    tmp_file.parent.mkdir(parents=True)
    final_file.parent.mkdir(parents=True)
    tmp_file.write_text("new", encoding="utf-8")
    final_file.write_text("old", encoding="utf-8")

    replace_file_atomically(tmp_file=tmp_file, final_file=final_file, backup_root=backup_root)

    assert final_file.read_text(encoding="utf-8") == "new"
    assert not tmp_file.exists()
    assert not (backup_root / final_file.name).exists()


def test_replace_directory_atomically_rolls_back_existing_directory_when_tmp_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_dir = tmp_path / "_tmp" / "trade_date=2026-05-08"
    final_dir = tmp_path / "raw" / "trade_date=2026-05-08"
    backup_root = tmp_path / "_backup"

    tmp_dir.mkdir(parents=True)
    final_dir.mkdir(parents=True)
    (tmp_dir / "part-000.parquet").write_text("new", encoding="utf-8")
    (final_dir / "part-000.parquet").write_text("old", encoding="utf-8")

    original_replace = Path.replace

    def fail_tmp_publish(self: Path, target: Path) -> Path:
        if self == tmp_dir:
            raise RuntimeError("publish failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_tmp_publish)

    with pytest.raises(RuntimeError, match="publish failed"):
        replace_directory_atomically(tmp_dir=tmp_dir, final_dir=final_dir, backup_root=backup_root)

    assert (final_dir / "part-000.parquet").read_text(encoding="utf-8") == "old"
    assert (tmp_dir / "part-000.parquet").read_text(encoding="utf-8") == "new"
    assert not (backup_root / final_dir.name).exists()


def test_replace_directory_atomically_replaces_existing_directory_and_removes_backup(tmp_path: Path) -> None:
    tmp_dir = tmp_path / "_tmp" / "trade_date=2026-05-08"
    final_dir = tmp_path / "raw" / "trade_date=2026-05-08"
    backup_root = tmp_path / "_backup"

    tmp_dir.mkdir(parents=True)
    final_dir.mkdir(parents=True)
    (tmp_dir / "part-000.parquet").write_text("new", encoding="utf-8")
    (final_dir / "part-000.parquet").write_text("old", encoding="utf-8")

    replace_directory_atomically(tmp_dir=tmp_dir, final_dir=final_dir, backup_root=backup_root)

    assert (final_dir / "part-000.parquet").read_text(encoding="utf-8") == "new"
    assert not tmp_dir.exists()
    assert not (backup_root / final_dir.name).exists()
