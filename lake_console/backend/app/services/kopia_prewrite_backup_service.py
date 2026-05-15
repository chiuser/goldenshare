from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class KopiaPrewriteBackupError(RuntimeError):
    pass


Runner = Callable[[list[str]], Any]


class KopiaPrewriteBackupService:
    def __init__(
        self,
        *,
        lake_root: Path,
        kopia_bin: str = "kopia",
        kopia_config_path: Path | None = None,
        kopia_password: str | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.lake_root = lake_root.resolve()
        self.kopia_bin = kopia_bin
        self.kopia_config_path = kopia_config_path.resolve() if kopia_config_path else None
        self.kopia_password = kopia_password
        self.runner = runner or self._run_kopia_json

    def create_prewrite_backup(self, *, run_id: str, profile_key: str, backup_plan: dict[str, Any]) -> dict[str, Any]:
        backup_paths = [str(item) for item in backup_plan.get("backup_paths") or []]
        snapshot_paths = [str(item) for item in backup_plan.get("snapshot_paths") or backup_paths]
        missing_paths = [str(item) for item in backup_plan.get("path_missing_before_write") or []]
        snapshot_ids: list[str] = []
        snapshot_records: list[dict[str, Any]] = []

        for relative_path in sorted(set(snapshot_paths)):
            absolute_path = (self.lake_root / relative_path).resolve()
            if not _is_relative_to(absolute_path, self.lake_root):
                raise KopiaPrewriteBackupError(f"Kopia 备份路径越界：{relative_path}")
            if not absolute_path.exists():
                missing_paths.append(relative_path)
                continue
            description = f"lake-sync prewrite run={run_id} profile={profile_key} snapshot_path={relative_path}"
            payload = self.runner(
                [
                    self.kopia_bin,
                    "snapshot",
                    "create",
                    str(absolute_path),
                    "--json",
                    "--description",
                    description,
                    "--disable-file-logging",
                ]
            )
            ids = _extract_snapshot_ids(payload)
            snapshot_ids.extend(ids)
            snapshot_records.append(
                {
                    "path": relative_path,
                    "absolute_path": str(absolute_path),
                    "snapshot_ids": ids,
                    "description": description,
                }
            )

        return {
            "run_id": run_id,
            "profile_key": profile_key,
            "provider": "kopia",
            "status": "success",
            "pin_policy": backup_plan.get("pin_policy") or "none",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_ids": snapshot_ids,
            "snapshots": snapshot_records,
            "snapshot_paths": sorted(set(snapshot_paths)),
            "backup_paths": backup_paths,
            "path_missing_before_write": sorted(set(missing_paths)),
        }

    def _run_kopia_json(self, argv: list[str]) -> Any:
        env = os.environ.copy()
        if self.kopia_config_path:
            env["KOPIA_CONFIG_PATH"] = str(self.kopia_config_path)
        if self.kopia_password:
            env["KOPIA_PASSWORD"] = self.kopia_password
        try:
            result = subprocess.run(
                argv,
                cwd=str(self.lake_root),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise KopiaPrewriteBackupError(f"找不到 Kopia 可执行文件：{argv[0]}") from exc
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or f"kopia exited with {result.returncode}"
            raise KopiaPrewriteBackupError(stderr)
        if not result.stdout.strip():
            return {}
        try:
            import json

            return json.loads(result.stdout)
        except Exception as exc:
            raise KopiaPrewriteBackupError(f"Kopia JSON 输出解析失败：{exc}") from exc


def _extract_snapshot_ids(payload: Any) -> list[str]:
    rows = payload if isinstance(payload, list) else [payload]
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        snapshot_id = _nested_string(row, "rootEntry", "obj") or _string_or_none(row.get("id")) or _string_or_none(row.get("snapshotID"))
        if snapshot_id:
            ids.append(snapshot_id)
    return ids


def _nested_string(payload: dict[str, Any], *keys: str) -> str | None:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _string_or_none(current)


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
