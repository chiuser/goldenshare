from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lake_console.backend.app.services.prod_core_db import PROD_CORE_DB_SOURCE
from lake_console.backend.app.services.prod_raw_db import PROD_RAW_DB_SOURCE
from lake_console.backend.app.sync.planners.event_date import PROD_DB_EVENT_DATE_PROFILE_KEY
from lake_console.backend.app.services.sync_profile_runner import SyncProfileRunner, SyncProfileRunnerError
from lake_console.backend.app.settings import LakeConsoleSettings


def test_sync_profile_runner_executes_prod_db_snapshot(monkeypatch, tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    captured: dict[str, Any] = {}

    class FakeProdRawCurrentExportService:
        def __init__(self, *, lake_root: Path, database_url: str | None, progress):  # type: ignore[no-untyped-def]
            captured["lake_root"] = lake_root
            captured["database_url"] = database_url
            self.progress = progress

        def export(self, *, dataset_key: str) -> dict[str, Any]:
            assert dataset_key == "bse_mapping"
            self.progress("[bse_mapping:prod-raw-db] fetched=2")
            return {
                "dataset_key": "bse_mapping",
                "source": "prod-raw-db",
                "run_id": "run-bse",
                "fetched_rows": 2,
                "written_rows": 2,
                "manifest_written_rows": 2,
                "raw_output": "/lake/raw_tushare/bse_mapping/current/part-000.parquet",
                "manifest_output": "/lake/manifest/security_reference/tushare_bse_mapping.parquet",
                "elapsed_seconds": 0.1,
            }

    monkeypatch.setattr(
        "lake_console.backend.app.services.sync_profile_runner.ProdRawCurrentExportService",
        FakeProdRawCurrentExportService,
    )

    result = SyncProfileRunner(
        settings=LakeConsoleSettings(
            lake_root=tmp_path,
            tushare_token=None,
            prod_raw_db_url="postgresql://readonly@example/db",
        ),
        progress=events.append,
    ).run(
        plan={
            "profile_key": "prod_db_snapshot_refresh",
            "dataset_plans": [{"dataset_key": "bse_mapping", "source": PROD_RAW_DB_SOURCE, "mode": "snapshot_refresh"}],
        }
    )

    assert captured["database_url"] == "postgresql://readonly@example/db"
    assert result["status"] == "success"
    assert result["dataset_results"][0]["dataset_key"] == "bse_mapping"
    assert result["dataset_results"][0]["written_rows"] == 2
    assert [event["event_type"] for event in events] == ["dataset_started", "dataset_progress", "dataset_completed"]


def test_sync_profile_runner_executes_prod_db_daily_from_raw(monkeypatch, tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    captured: dict[str, Any] = {}

    class FakeDbTradeDateExportService:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.progress = kwargs["progress"]

        def export(self, *, trade_date, start_date, end_date, ts_code):  # type: ignore[no-untyped-def]
            assert trade_date.isoformat() == "2026-05-14"
            assert start_date is None
            assert end_date is None
            assert ts_code is None
            self.progress("[daily:prod-raw-db] fetched=10")
            return {
                "dataset_key": "daily",
                "source": PROD_RAW_DB_SOURCE,
                "mode": "point_incremental",
                "run_id": "run-daily",
                "fetched_rows": 10,
                "written_rows": 10,
                "elapsed_seconds": 0.1,
            }

    monkeypatch.setattr(
        "lake_console.backend.app.services.sync_profile_runner.DbTradeDateExportService",
        FakeDbTradeDateExportService,
    )

    result = SyncProfileRunner(
        settings=LakeConsoleSettings(
            lake_root=tmp_path,
            tushare_token=None,
            prod_raw_db_url="postgresql://readonly@example/raw",
        ),
        progress=events.append,
    ).run(
        plan={
            "profile_key": "prod_db_daily",
            "dataset_plans": [
                {
                    "dataset_key": "daily",
                    "source": PROD_RAW_DB_SOURCE,
                    "mode": "point_incremental",
                    "parameters": {"trade_date": "2026-05-14"},
                }
            ],
        }
    )

    assert captured["source"] == PROD_RAW_DB_SOURCE
    assert captured["database_url"] == "postgresql://readonly@example/raw"
    assert result["dataset_results"][0]["dataset_key"] == "daily"
    assert result["dataset_results"][0]["written_rows"] == 10
    assert [event["event_type"] for event in events] == ["dataset_started", "dataset_progress", "dataset_completed"]


def test_sync_profile_runner_executes_prod_db_daily_from_core(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    class FakeDbTradeDateExportService:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def export(self, *, trade_date, start_date, end_date, ts_code):  # type: ignore[no-untyped-def]
            assert trade_date is None
            assert start_date.isoformat() == "2026-05-01"
            assert end_date.isoformat() == "2026-05-14"
            assert ts_code is None
            return {
                "dataset_key": "index_daily",
                "source": PROD_CORE_DB_SOURCE,
                "mode": "range_rebuild",
                "run_id": "run-index-daily",
                "fetched_rows": 20,
                "written_rows": 20,
                "trade_date_count": 2,
                "elapsed_seconds": 0.2,
            }

    monkeypatch.setattr(
        "lake_console.backend.app.services.sync_profile_runner.DbTradeDateExportService",
        FakeDbTradeDateExportService,
    )

    result = SyncProfileRunner(
        settings=LakeConsoleSettings(
            lake_root=tmp_path,
            tushare_token=None,
            prod_core_db_url="postgresql://readonly@example/core",
        )
    ).run(
        plan={
            "profile_key": "prod_db_manual_backfill",
            "dataset_plans": [
                {
                    "dataset_key": "index_daily",
                    "source": PROD_CORE_DB_SOURCE,
                    "mode": "range_rebuild",
                    "parameters": {"start_date": "2026-05-01", "end_date": "2026-05-14"},
                }
            ],
        }
    )

    assert captured["source"] == PROD_CORE_DB_SOURCE
    assert captured["database_url"] == "postgresql://readonly@example/core"
    assert result["dataset_results"][0]["source"] == PROD_CORE_DB_SOURCE
    assert result["dataset_results"][0]["trade_date_count"] == 2


def test_sync_profile_runner_executes_lake_reference_stock_basic(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    class FakeTushareLakeClient:
        def __init__(self, token: str | None, *, request_limit_per_minute: int) -> None:
            captured["token"] = token
            captured["request_limit_per_minute"] = request_limit_per_minute

    class FakeTushareStockBasicSyncService:
        def __init__(self, *, lake_root: Path, client, progress):  # type: ignore[no-untyped-def]
            captured["lake_root"] = lake_root
            captured["client"] = client
            self.progress = progress

        def sync(self) -> dict[str, Any]:
            self.progress("[stock_basic] fetched=2")
            return {
                "dataset_key": "stock_basic",
                "run_id": "run-stock-basic",
                "fetched_rows": 2,
                "written_rows": 2,
                "universe_written_rows": 2,
                "raw_output": "/lake/raw_tushare/stock_basic/current/part-000.parquet",
                "universe_output": "/lake/manifest/security_universe/tushare_stock_basic.parquet",
                "elapsed_seconds": 0.1,
            }

    monkeypatch.setattr(
        "lake_console.backend.app.services.sync_profile_runner.TushareLakeClient",
        FakeTushareLakeClient,
    )
    monkeypatch.setattr(
        "lake_console.backend.app.services.sync_profile_runner.TushareStockBasicSyncService",
        FakeTushareStockBasicSyncService,
    )

    result = SyncProfileRunner(
        settings=LakeConsoleSettings(
            lake_root=tmp_path,
            tushare_token="token-001",
            tushare_request_limit_per_minute=321,
        )
    ).run(
        plan={
            "profile_key": "lake_reference_refresh",
            "dataset_plans": [
                {
                    "dataset_key": "stock_basic",
                    "source": "tushare",
                    "mode": "snapshot_refresh",
                    "parameters": {},
                }
            ],
        }
    )

    assert captured["token"] == "token-001"
    assert captured["request_limit_per_minute"] == 321
    assert result["dataset_results"][0]["dataset_key"] == "stock_basic"
    assert result["dataset_results"][0]["universe_written_rows"] == 2


def test_sync_profile_runner_executes_prod_db_event_date(monkeypatch, tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    captured: dict[str, Any] = {}

    class FakeDbEventDateExportService:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.progress = kwargs["progress"]

        def export(self, *, event_dates):  # type: ignore[no-untyped-def]
            assert [item.isoformat() for item in event_dates] == ["2026-05-15"]
            self.progress("[anns_d:prod-raw-db] event_date=2026-05-15 written=2")
            return {
                "dataset_key": "anns_d",
                "source": PROD_RAW_DB_SOURCE,
                "mode": "event_date_point",
                "date_axis": "event_date",
                "partition_field": "event_date",
                "source_date_field": "ann_date",
                "run_id": "run-anns-event",
                "event_dates": ["2026-05-15"],
                "event_date_count": 1,
                "fetched_rows": 2,
                "written_rows": 2,
                "elapsed_seconds": 0.1,
            }

    monkeypatch.setattr(
        "lake_console.backend.app.services.sync_profile_runner.DbEventDateExportService",
        FakeDbEventDateExportService,
    )

    result = SyncProfileRunner(
        settings=LakeConsoleSettings(
            lake_root=tmp_path,
            tushare_token=None,
            prod_raw_db_url="postgresql://readonly@example/raw",
        ),
        progress=events.append,
    ).run(
        plan={
            "profile_key": PROD_DB_EVENT_DATE_PROFILE_KEY,
            "dataset_plans": [
                {
                    "dataset_key": "anns_d",
                    "source": PROD_RAW_DB_SOURCE,
                    "mode": "event_date_point",
                    "date_axis": "event_date",
                    "parameters": {"event_dates": ["2026-05-15"]},
                }
            ],
        }
    )

    assert captured["database_url"] == "postgresql://readonly@example/raw"
    assert result["dataset_results"][0]["dataset_key"] == "anns_d"
    assert result["dataset_results"][0]["date_axis"] == "event_date"
    assert result["dataset_results"][0]["event_date_count"] == 1
    assert result["dataset_results"][0]["written_rows"] == 2
    assert [event["event_type"] for event in events] == ["dataset_started", "dataset_progress", "dataset_completed"]


def test_sync_profile_runner_rejects_stk_mins_special_pipeline(tmp_path: Path) -> None:
    runner = SyncProfileRunner(
        settings=LakeConsoleSettings(lake_root=tmp_path, tushare_token=None, prod_raw_db_url="postgresql://readonly@example/db")
    )

    with pytest.raises(SyncProfileRunnerError, match="不在 M6 可执行 profile"):
        runner.run(
            plan={
                "profile_key": "stk_mins_sync",
                "dataset_plans": [{"dataset_key": "stk_mins", "source": "tushare", "mode": "snapshot_refresh"}],
            }
        )


def test_sync_profile_runner_requires_prod_raw_database_url(tmp_path: Path) -> None:
    runner = SyncProfileRunner(
        settings=LakeConsoleSettings(lake_root=tmp_path, tushare_token=None, prod_raw_db_url=None)
    )

    with pytest.raises(SyncProfileRunnerError, match="GOLDENSHARE_PROD_RAW_DB_URL"):
        runner.run(
            plan={
                "profile_key": "prod_db_snapshot_refresh",
                "dataset_plans": [{"dataset_key": "bse_mapping", "source": PROD_RAW_DB_SOURCE, "mode": "snapshot_refresh"}],
            }
        )
