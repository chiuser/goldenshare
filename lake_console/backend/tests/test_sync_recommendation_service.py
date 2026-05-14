from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from lake_console.backend.app.api import sync_center
from lake_console.backend.app.main import create_app
from lake_console.backend.app.services.parquet_writer import write_rows_to_parquet
from lake_console.backend.app.services.sync_recommendation_service import SyncRecommendationService
from lake_console.backend.app.settings import LakeConsoleSettings


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def test_sync_recommendation_marks_lagging_daily_dataset(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    _write_calendar(
        lake_root,
        [
            ("2026-05-12", True),
            ("2026-05-13", True),
            ("2026-05-14", True),
        ],
    )
    _touch_partition(lake_root, "raw_tushare/daily/trade_date=2026-05-12")

    payload = SyncRecommendationService(
        lake_root=lake_root,
        now=datetime(2026, 5, 14, 21, 0, tzinfo=LOCAL_TZ),
    ).build(profile_key="prod_db_daily")

    daily = _item(payload, "daily")
    assert payload["expected_reference_date"] == "2026-05-14"
    assert daily["status"] == "lagging"
    assert daily["local_latest_trade_date"] == "2026-05-12"
    assert daily["expected_latest_trade_date"] == "2026-05-14"
    assert daily["suggested_start_date"] == "2026-05-13"
    assert daily["suggested_end_date"] == "2026-05-14"
    assert daily["lag_anchor_count"] == 2
    assert daily["lag_calendar_days"] == 2
    assert daily["plan_hint"] == {
        "profile_key": "prod_db_manual_backfill",
        "dataset_keys": ["daily"],
        "target_date": None,
        "start_date": "2026-05-13",
        "end_date": "2026-05-14",
    }


def test_sync_recommendation_cutoff_uses_previous_open_day_before_cutoff(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    _write_calendar(
        lake_root,
        [
            ("2026-05-12", True),
            ("2026-05-13", True),
            ("2026-05-14", True),
        ],
    )
    _touch_partition(lake_root, "raw_tushare/daily/trade_date=2026-05-13")

    payload = SyncRecommendationService(
        lake_root=lake_root,
        now=datetime(2026, 5, 14, 10, 0, tzinfo=LOCAL_TZ),
    ).build(profile_key="prod_db_daily")

    daily = _item(payload, "daily")
    assert payload["expected_reference_date"] == "2026-05-13"
    assert daily["status"] == "up_to_date"
    assert daily["expected_latest_trade_date"] == "2026-05-13"


def test_sync_recommendation_supports_week_and_month_anchors(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    _write_calendar(
        lake_root,
        [
            ("2026-04-30", True),
            ("2026-05-08", True),
            ("2026-05-11", True),
            ("2026-05-12", True),
            ("2026-05-15", True),
            ("2026-05-29", True),
        ],
    )
    _touch_partition(lake_root, "raw_tushare/index_weekly/trade_date=2026-05-08")
    _touch_partition(lake_root, "raw_tushare/index_monthly/trade_date=2026-04-30")

    payload = SyncRecommendationService(
        lake_root=lake_root,
        now=datetime(2026, 5, 29, 21, 0, tzinfo=LOCAL_TZ),
    ).build(profile_key="prod_db_daily")

    weekly = _item(payload, "index_weekly")
    monthly = _item(payload, "index_monthly")
    assert weekly["status"] == "lagging"
    assert weekly["expected_latest_trade_date"] == "2026-05-29"
    assert weekly["suggested_start_date"] == "2026-05-15"
    assert monthly["status"] == "lagging"
    assert monthly["expected_latest_trade_date"] == "2026-05-29"
    assert monthly["suggested_start_date"] == "2026-05-29"


def test_sync_recommendation_marks_empty_dataset(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    _write_calendar(lake_root, [("2026-05-14", True)])

    payload = SyncRecommendationService(
        lake_root=lake_root,
        now=datetime(2026, 5, 14, 21, 0, tzinfo=LOCAL_TZ),
    ).build(profile_key="prod_db_daily")

    daily = _item(payload, "daily")
    assert daily["status"] == "empty"
    assert daily["local_latest_trade_date"] is None
    assert daily["expected_latest_trade_date"] == "2026-05-14"
    assert daily["plan_hint"] is None


def test_sync_recommendation_blocks_when_calendar_missing(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    _touch_partition(lake_root, "raw_tushare/daily/trade_date=2026-05-12")

    payload = SyncRecommendationService(
        lake_root=lake_root,
        now=datetime(2026, 5, 14, 21, 0, tzinfo=LOCAL_TZ),
    ).build(profile_key="prod_db_daily")

    daily = _item(payload, "daily")
    assert payload["expected_reference_date"] is None
    assert daily["status"] == "blocked_missing_calendar"
    assert daily["local_latest_trade_date"] == "2026-05-12"
    assert "trade_cal" in daily["reason"]


def test_sync_recommendation_api_is_read_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    _write_calendar(lake_root, [("2026-05-14", True)])
    _patch_settings(monkeypatch, lake_root)

    response = TestClient(create_app()).get("/api/lake/sync/recommendations?profile_key=prod_db_daily")

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_key"] == "prod_db_daily"
    assert payload["items"]
    assert not (lake_root / "manifest" / "lake_jobs").exists()


def test_sync_recommendation_api_rejects_unsupported_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_settings(monkeypatch, tmp_path / "lake")

    response = TestClient(create_app()).get("/api/lake/sync/recommendations?profile_key=stk_mins_sync")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "UNSUPPORTED_RECOMMENDATION_PROFILE"


def _item(payload: dict, dataset_key: str) -> dict:
    return next(item for item in payload["items"] if item["dataset_key"] == dataset_key)


def _write_calendar(lake_root: Path, rows: list[tuple[str, bool]]) -> None:
    write_rows_to_parquet(
        [{"cal_date": cal_date, "is_open": is_open} for cal_date, is_open in rows],
        lake_root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet",
    )


def _touch_partition(lake_root: Path, relative_path: str) -> None:
    path = lake_root / relative_path
    path.mkdir(parents=True)
    (path / "part-000.parquet").write_text("placeholder", encoding="utf-8")


def _patch_settings(monkeypatch: pytest.MonkeyPatch, lake_root: Path) -> None:
    monkeypatch.setattr(
        sync_center,
        "load_settings",
        lambda: LakeConsoleSettings(
            lake_root=lake_root,
            tushare_token=None,
        ),
    )
