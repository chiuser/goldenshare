from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


JsonObject = dict[str, Any]
Runner = Callable[[list[str]], Any]


class KopiaCommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class KopiaSnapshotRecord:
    snapshot_id: str
    manifest_id: str | None
    description: str | None
    scope: str
    dataset_key: str | None
    source_path: str
    display_path: str
    is_baseline: bool
    pins: list[str]
    retention_reasons: list[str]
    total_size: int
    file_count: int
    dir_count: int
    host: str | None
    user_name: str | None
    started_at: datetime | None
    finished_at: datetime | None


class KopiaRecoveryService:
    def __init__(
        self,
        lake_root: Path,
        *,
        runner: Runner | None = None,
        kopia_bin: str = "kopia",
        kopia_config_path: Path | None = None,
        kopia_password: str | None = None,
    ) -> None:
        self.lake_root = lake_root.resolve()
        self.runner = runner or self._run_kopia_json
        self.kopia_bin = kopia_bin
        self.kopia_config_path = kopia_config_path.resolve() if kopia_config_path else None
        self.kopia_password = kopia_password

    def get_repository_summary(self) -> dict[str, Any]:
        inventory_error: str | None = None
        status_error: str | None = None
        snapshots: list[KopiaSnapshotRecord] = []
        status_payload: JsonObject | None = None

        try:
            snapshots = self._load_snapshots()
        except KopiaCommandError as exc:
            inventory_error = str(exc)

        try:
            status_payload = self.runner([self.kopia_bin, "repository", "status", "--json", "--disable-file-logging"])
        except KopiaCommandError as exc:
            status_error = str(exc)

        connected = inventory_error is None or status_error is None
        latest_snapshot_at = max((item.finished_at or item.started_at for item in snapshots if item.finished_at or item.started_at), default=None)
        latest_baseline_at = max(
            ((item.finished_at or item.started_at) for item in snapshots if item.is_baseline and (item.finished_at or item.started_at)),
            default=None,
        )
        return {
            "connected": connected,
            "repository_type": _repository_type(status_payload),
            "repository_path": _repository_path(status_payload),
            "lake_root": str(self.lake_root),
            "snapshot_count": len(snapshots),
            "pinned_snapshot_count": sum(1 for item in snapshots if item.pins),
            "latest_snapshot_at": latest_snapshot_at,
            "latest_baseline_at": latest_baseline_at,
            "repository_error": inventory_error or status_error,
        }

    def list_snapshots(
        self,
        *,
        scope: str | None = None,
        dataset_key: str | None = None,
        pinned: bool | None = None,
        baseline_only: bool | None = None,
        query: str | None = None,
        finished_from: str | None = None,
        finished_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        try:
            snapshots = self._load_snapshots()
        except KopiaCommandError:
            return {"items": [], "total": 0, "limit": min(max(limit, 1), 500), "offset": max(offset, 0)}

        filtered = [
            item
            for item in snapshots
            if self._matches_filters(
                item,
                scope=scope,
                dataset_key=dataset_key,
                pinned=pinned,
                baseline_only=baseline_only,
                query=query,
                finished_from=finished_from,
                finished_to=finished_to,
            )
        ]
        bounded_limit = min(max(limit, 1), 500)
        bounded_offset = max(offset, 0)
        page = filtered[bounded_offset : bounded_offset + bounded_limit]
        return {
            "items": [self._summary_payload(item) for item in page],
            "total": len(filtered),
            "limit": bounded_limit,
            "offset": bounded_offset,
        }

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        try:
            snapshots = self._load_snapshots()
        except KopiaCommandError:
            return None
        summary = next((item for item in snapshots if item.snapshot_id == snapshot_id), None)
        if summary is None:
            return None
        payload = self._summary_payload(summary)
        payload.update(
            {
                "repository_path": self.get_repository_summary().get("repository_path"),
                "host": summary.host,
                "user_name": summary.user_name,
                "manifest_id": summary.manifest_id,
                "command_hints": self._command_hints(summary),
            }
        )
        return payload

    def _load_snapshots(self) -> list[KopiaSnapshotRecord]:
        payload = self.runner([self.kopia_bin, "snapshot", "list", "--all", "--json", "--disable-file-logging"])
        if not isinstance(payload, list):
            raise KopiaCommandError("Kopia snapshot list 返回格式异常。")
        records: list[KopiaSnapshotRecord] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            source_path = _string_or_none(_nested_value(row, "source", "path"))
            if not source_path:
                continue
            normalized_path = Path(source_path).resolve()
            try:
                relative = normalized_path.relative_to(self.lake_root)
                relative_path = relative.as_posix()
                if relative_path == ".":
                    relative_path = ""
                inside_lake = True
            except ValueError:
                if normalized_path != self.lake_root:
                    continue
                relative_path = ""
                inside_lake = True
            if not inside_lake:
                continue
            snapshot_id = _string_or_none(_nested_value(row, "rootEntry", "obj")) or _string_or_none(row.get("id"))
            if not snapshot_id:
                continue
            scope, dataset = _classify_scope(relative_path)
            pins = _string_list(row.get("pins"))
            description = _string_or_none(row.get("description"))
            is_baseline = _is_baseline_snapshot(
                normalized_path=normalized_path,
                lake_root=self.lake_root,
                description=description,
                pins=pins,
            )
            stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
            records.append(
                KopiaSnapshotRecord(
                    snapshot_id=snapshot_id,
                    manifest_id=_string_or_none(row.get("id")),
                    description=description,
                    scope=scope,
                    dataset_key=dataset,
                    source_path=str(normalized_path),
                    display_path=_display_path(relative_path, scope=scope, dataset_key=dataset),
                    is_baseline=is_baseline,
                    pins=pins,
                    retention_reasons=_string_list(row.get("retentionReason")),
                    total_size=_int_or_zero(stats.get("totalSize")),
                    file_count=_int_or_zero(stats.get("fileCount")),
                    dir_count=_int_or_zero(stats.get("dirCount")),
                    host=_string_or_none(_nested_value(row, "source", "host")),
                    user_name=_string_or_none(_nested_value(row, "source", "userName")),
                    started_at=_parse_datetime(row.get("startTime")),
                    finished_at=_parse_datetime(row.get("endTime")),
                )
            )
        records.sort(key=lambda item: ((item.finished_at or item.started_at or datetime.min), item.snapshot_id), reverse=True)
        return records

    def _matches_filters(
        self,
        item: KopiaSnapshotRecord,
        *,
        scope: str | None,
        dataset_key: str | None,
        pinned: bool | None,
        baseline_only: bool | None,
        query: str | None,
        finished_from: str | None,
        finished_to: str | None,
    ) -> bool:
        if scope and item.scope != scope:
            return False
        if dataset_key and item.dataset_key != dataset_key:
            return False
        if pinned is not None and bool(item.pins) is not pinned:
            return False
        if baseline_only and not item.is_baseline:
            return False
        if query:
            haystack = " ".join(
                part
                for part in [
                    item.snapshot_id,
                    item.manifest_id or "",
                    item.description or "",
                    item.source_path,
                    item.display_path,
                    item.dataset_key or "",
                    ",".join(item.pins),
                ]
                if part
            ).lower()
            if query.lower() not in haystack:
                return False
        finished_from_dt = _parse_datetime(finished_from)
        finished_to_dt = _parse_datetime(finished_to)
        event_time = item.finished_at or item.started_at
        if finished_from_dt and (event_time is None or event_time < finished_from_dt):
            return False
        if finished_to_dt and (event_time is None or event_time > finished_to_dt):
            return False
        return True

    def _summary_payload(self, item: KopiaSnapshotRecord) -> dict[str, Any]:
        return {
            "snapshot_id": item.snapshot_id,
            "manifest_id": item.manifest_id,
            "description": item.description,
            "scope": item.scope,
            "dataset_key": item.dataset_key,
            "source_path": item.source_path,
            "display_path": item.display_path,
            "is_baseline": item.is_baseline,
            "pins": list(item.pins),
            "retention_reasons": list(item.retention_reasons),
            "total_size": item.total_size,
            "file_count": item.file_count,
            "dir_count": item.dir_count,
            "started_at": item.started_at,
            "finished_at": item.finished_at,
        }

    def _command_hints(self, item: KopiaSnapshotRecord) -> list[dict[str, str]]:
        restore_target = f"/tmp/goldenshare-lake-restore-{item.dataset_key or item.scope}-{item.snapshot_id[:8]}"
        hints = [
            {
                "command_key": "restore_to_tmp",
                "title": "恢复到临时目录",
                "command": f"kopia snapshot restore {item.snapshot_id} {restore_target} --write-files-atomically",
                "scenario": "先把这份快照恢复到临时目录进行核对。",
            }
        ]
        if item.pins:
            hints.append(
                {
                    "command_key": "unpin_preview",
                    "title": "取消 Pin 预览",
                    "command": f"kopia snapshot pin {item.snapshot_id} --remove={item.pins[0]}",
                    "scenario": "如果要取消当前 pin，可先预览这条命令。",
                }
            )
        else:
            hints.append(
                {
                    "command_key": "pin_preview",
                    "title": "添加 Pin 预览",
                    "command": f"kopia snapshot pin {item.snapshot_id} --add=manual-review",
                    "scenario": "如果要固定保留这份快照，可先预览 pin 命令。",
                }
            )
        return hints

    def _run_kopia_json(self, argv: list[str]) -> Any:
        if shutil.which(argv[0]) is None:
            raise KopiaCommandError("未找到 kopia 命令。请先安装并确认命令行可用。")
        env = self._build_kopia_env()
        completed = subprocess.run(
            argv,
            cwd=str(self.lake_root),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Kopia 命令执行失败。").strip()
            if "password prompt error" in message.lower() and "KOPIA_PASSWORD" not in env:
                message = (
                    f"{message}；当前 backend 无法交互输入 Kopia 密码。"
                    "请通过环境变量 KOPIA_PASSWORD 或 lake_console/config.local.toml 配置 kopia_password。"
                )
            raise KopiaCommandError(message)
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise KopiaCommandError("Kopia JSON 输出解析失败。") from exc

    def _build_kopia_env(self) -> dict[str, str]:
        env = dict(os.environ)
        resolved_config_path = self._resolve_kopia_config_path()
        if resolved_config_path and "KOPIA_CONFIG_PATH" not in env:
            env["KOPIA_CONFIG_PATH"] = str(resolved_config_path)
        if self.kopia_password and "KOPIA_PASSWORD" not in env:
            env["KOPIA_PASSWORD"] = self.kopia_password
        return env

    def _resolve_kopia_config_path(self) -> Path | None:
        if os.getenv("KOPIA_CONFIG_PATH"):
            return Path(os.environ["KOPIA_CONFIG_PATH"]).expanduser()
        if self.kopia_config_path is not None:
            return self.kopia_config_path
        for candidate in _default_kopia_config_candidates():
            if candidate.exists():
                return candidate
        return None


def _classify_scope(relative_path: str) -> tuple[str, str | None]:
    if not relative_path:
        return "whole_lake", None
    first, *rest = [part for part in relative_path.split("/") if part]
    if first == "manifest":
        return "manifest", None
    if first == "raw_tushare":
        return "raw", _normalize_dataset_key(rest[0] if rest else None)
    if first == "derived":
        return "derived", _normalize_dataset_key(rest[0] if rest else None)
    if first == "research":
        return "research", _normalize_dataset_key(rest[0] if rest else None)
    if first == "indicators":
        return "indicators", _normalize_dataset_key(rest[0] if rest else None)
    return "other", None


def _normalize_dataset_key(raw_value: str | None) -> str | None:
    value = _string_or_none(raw_value)
    if not value:
        return None
    for suffix in ("_by_date", "_by_symbol_month"):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _display_path(relative_path: str, *, scope: str, dataset_key: str | None) -> str:
    if scope == "whole_lake":
        return "whole_lake"
    if dataset_key:
        return dataset_key
    return relative_path or scope


def _is_baseline_snapshot(*, normalized_path: Path, lake_root: Path, description: str | None, pins: list[str]) -> bool:
    if normalized_path == lake_root and any("baseline" in pin.lower() for pin in pins):
        return True
    if normalized_path == lake_root and description and "baseline" in description.lower():
        return True
    return False


def _default_kopia_config_candidates() -> list[Path]:
    home = Path.home()
    return [
        home / "Library" / "Application Support" / "kopia" / "repository.config",
        home / ".config" / "kopia" / "repository.config",
    ]


def _repository_type(payload: JsonObject | None) -> str | None:
    if not payload:
        return None
    for candidate in (
        _nested_value(payload, "storage", "type"),
        payload.get("storage"),
        payload.get("storageType"),
        payload.get("storage_type"),
        _nested_value(payload, "storageConfig", "type"),
    ):
        value = _string_or_none(candidate)
        if value:
            return value
    return None


def _repository_path(payload: JsonObject | None) -> str | None:
    if not payload:
        return None
    for candidate in (
        payload.get("path"),
        payload.get("storagePath"),
        _nested_value(payload, "storage", "config", "path"),
        _nested_value(payload, "storageConfig", "path"),
        _nested_value(payload, "config", "path"),
    ):
        value = _string_or_none(candidate)
        if value:
            return value
    return None


def _nested_value(payload: Any, *keys: str) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_string_or_none(entry) for entry in value) if item]


def _parse_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _int_or_zero(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    text = value.strip()
    return text or None
