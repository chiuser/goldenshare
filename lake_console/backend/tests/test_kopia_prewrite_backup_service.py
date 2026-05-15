from __future__ import annotations

from pathlib import Path

import pytest

from lake_console.backend.app.services.kopia_prewrite_backup_service import KopiaPrewriteBackupError, KopiaPrewriteBackupService


def test_kopia_prewrite_backup_creates_snapshots_for_aggregated_snapshot_paths(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    (lake_root / "raw_tushare" / "daily" / "trade_date=2026-05-13").mkdir(parents=True)
    (lake_root / "raw_tushare" / "daily" / "trade_date=2026-05-14").mkdir(parents=True)
    captured: list[list[str]] = []

    def fake_runner(argv: list[str]):
        captured.append(argv)
        return [{"rootEntry": {"obj": "snapshot-001"}}]

    backup = KopiaPrewriteBackupService(lake_root=lake_root, runner=fake_runner).create_prewrite_backup(
        run_id="run_1",
        profile_key="prod_db_daily",
        backup_plan={
            "backup_paths": [
                "raw_tushare/daily/trade_date=2026-05-13",
                "raw_tushare/daily/trade_date=2026-05-14",
            ],
            "snapshot_paths": ["raw_tushare/daily"],
            "path_missing_before_write": ["raw_tushare/moneyflow/trade_date=2026-05-14"],
            "pin_policy": "none",
        },
    )

    assert backup["status"] == "success"
    assert backup["snapshot_ids"] == ["snapshot-001"]
    assert backup["snapshot_paths"] == ["raw_tushare/daily"]
    assert backup["backup_paths"] == [
        "raw_tushare/daily/trade_date=2026-05-13",
        "raw_tushare/daily/trade_date=2026-05-14",
    ]
    assert len(captured) == 1
    assert captured[0][0:3] == ["kopia", "snapshot", "create"]
    assert captured[0][3] == str(lake_root / "raw_tushare" / "daily")
    assert any("snapshot_path=raw_tushare/daily" in item for item in captured[0])
    assert "raw_tushare/moneyflow/trade_date=2026-05-14" in backup["path_missing_before_write"]


def test_kopia_prewrite_backup_rejects_path_escape(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()

    with pytest.raises(KopiaPrewriteBackupError, match="路径越界"):
        KopiaPrewriteBackupService(lake_root=lake_root, runner=lambda _: {}).create_prewrite_backup(
            run_id="run_1",
            profile_key="prod_db_daily",
            backup_plan={"backup_paths": ["../outside"], "path_missing_before_write": []},
        )


def test_kopia_prewrite_backup_reports_missing_binary(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    existing = lake_root / "raw_tushare" / "daily" / "trade_date=2026-05-14"
    existing.mkdir(parents=True)

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("kopia")

    monkeypatch.setattr("lake_console.backend.app.services.kopia_prewrite_backup_service.subprocess.run", fake_run)

    with pytest.raises(KopiaPrewriteBackupError, match="找不到 Kopia"):
        KopiaPrewriteBackupService(lake_root=lake_root).create_prewrite_backup(
            run_id="run_1",
            profile_key="prod_db_daily",
            backup_plan={"backup_paths": ["raw_tushare/daily/trade_date=2026-05-14"], "path_missing_before_write": []},
        )
