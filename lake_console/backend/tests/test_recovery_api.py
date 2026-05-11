from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lake_console.backend.app.api import recovery
from lake_console.backend.app.services.kopia_recovery_service import KopiaCommandError, KopiaRecoveryService
from lake_console.backend.app.settings import LakeConsoleSettings


def test_kopia_recovery_service_summarizes_filters_and_builds_detail(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    service = KopiaRecoveryService(lake_root, runner=_fake_runner(lake_root))

    summary = service.get_repository_summary()
    assert summary["connected"] is True
    assert summary["repository_type"] == "filesystem"
    assert summary["snapshot_count"] == 2
    assert summary["pinned_snapshot_count"] == 1
    assert summary["latest_baseline_at"] is not None

    listing = service.list_snapshots(scope="whole_lake", pinned=True, baseline_only=True)
    assert listing["total"] == 1
    first = listing["items"][0]
    assert first["snapshot_id"] == "k9673865f7c8f70e07dffd7740e8c9e8b"
    assert first["is_baseline"] is True
    assert first["scope"] == "whole_lake"

    detail = service.get_snapshot("rawsnapshot123")
    assert detail is not None
    assert detail["dataset_key"] == "hk_basic"
    assert detail["scope"] == "raw"
    assert any(item["command_key"] == "restore_to_tmp" for item in detail["command_hints"])
    assert any(item["command_key"] == "pin_preview" for item in detail["command_hints"])


def test_kopia_recovery_api_reads_repository_summary_list_and_detail(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    runner = _fake_runner(lake_root)

    monkeypatch.setattr(
        recovery,
        "load_settings",
        lambda: LakeConsoleSettings(
            lake_root=lake_root,
            tushare_token=None,
        ),
    )
    monkeypatch.setattr(
        recovery,
        "KopiaRecoveryService",
        lambda root, **kwargs: KopiaRecoveryService(root, runner=runner, **kwargs),
    )

    summary_response = recovery.repository_summary()
    assert summary_response.connected is True
    assert summary_response.snapshot_count == 2

    list_response = recovery.list_recovery_snapshots(
        scope="raw",
        dataset_key="hk_basic",
        pinned=None,
        baseline_only=None,
        query=None,
        finished_from=None,
        finished_to=None,
        limit=100,
        offset=0,
    )
    assert list_response.total == 1
    assert list_response.items[0].dataset_key == "hk_basic"

    detail_response = recovery.get_recovery_snapshot("rawsnapshot123")
    payload = detail_response.model_dump()
    assert payload["snapshot_id"] == "rawsnapshot123"
    assert payload["repository_path"] == "/Volumes/datasource/goldenshare-kopia-repo"
    assert any(item["command_key"] == "restore_to_tmp" for item in payload["command_hints"])

    with pytest.raises(Exception) as exc_info:
        recovery.get_recovery_snapshot("missing")
    assert getattr(exc_info.value, "status_code", None) == 404


def test_kopia_recovery_summary_reports_disconnected_when_command_fails(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()

    def failing_runner(argv: list[str]):
        raise KopiaCommandError("open repository: get password: password prompt error")

    service = KopiaRecoveryService(lake_root, runner=failing_runner)
    summary = service.get_repository_summary()
    assert summary["connected"] is False
    assert summary["snapshot_count"] == 0
    assert "password prompt error" in (summary["repository_error"] or "")

    listing = service.list_snapshots()
    assert listing["total"] == 0
    assert listing["items"] == []


def test_kopia_recovery_service_uses_explicit_config_and_password(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    config_path = tmp_path / "repository.config"
    config_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr("lake_console.backend.app.services.kopia_recovery_service.shutil.which", lambda _: "/opt/homebrew/bin/kopia")

    def fake_run(argv, *, cwd, env, capture_output, text, check):  # type: ignore[no-untyped-def]
        captured["argv"] = argv
        captured["cwd"] = cwd
        captured["env"] = env

        class Result:
            returncode = 0
            stdout = '{"storage":"filesystem","storageConfig":{"path":"/Volumes/datasource/goldenshare-kopia-repo"}}'
            stderr = ""

        return Result()

    monkeypatch.setattr("lake_console.backend.app.services.kopia_recovery_service.subprocess.run", fake_run)

    service = KopiaRecoveryService(
        lake_root,
        kopia_config_path=config_path,
        kopia_password="secret-pass",
    )
    summary = service.get_repository_summary()
    assert summary["connected"] is True

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["KOPIA_CONFIG_PATH"] == str(config_path.resolve())
    assert env["KOPIA_PASSWORD"] == "secret-pass"


def _fake_runner(lake_root: Path):
    lake_root_str = str(lake_root.resolve())

    def run(argv: list[str]):
        if argv[1:3] == ["repository", "status"]:
            return {
                "storage": {
                    "type": "filesystem",
                    "config": {"path": "/Volumes/datasource/goldenshare-kopia-repo"},
                },
            }
        if argv[1:3] == ["snapshot", "list"]:
            return [
                {
                    "id": "dd69fa2d9d3868b85c2200ab4d4da108",
                    "description": "goldenshare lake full baseline 2026-05-11 before write-recovery rollout",
                    "source": {"host": "bogon", "userName": "congming", "path": lake_root_str},
                    "startTime": "2026-05-11T12:01:00.779025Z",
                    "endTime": "2026-05-11T12:03:09.563711Z",
                    "stats": {"totalSize": 240750886354, "fileCount": 244442, "dirCount": 145646},
                    "rootEntry": {"obj": "k9673865f7c8f70e07dffd7740e8c9e8b"},
                    "pins": ["goldenshare-lake-baseline-2026-05-11"],
                    "retentionReason": ["latest-1", "daily-1"],
                },
                {
                    "id": "raw-manifest-1",
                    "description": "hk_basic current snapshot",
                    "source": {"host": "bogon", "userName": "congming", "path": f"{lake_root_str}/raw_tushare/hk_basic"},
                    "startTime": "2026-05-11T13:20:00Z",
                    "endTime": "2026-05-11T13:21:00Z",
                    "stats": {"totalSize": 2048, "fileCount": 1, "dirCount": 1},
                    "rootEntry": {"obj": "rawsnapshot123"},
                    "pins": [],
                    "retentionReason": ["latest-1"],
                },
            ]
        raise AssertionError(f"unexpected argv: {argv}")

    return run
