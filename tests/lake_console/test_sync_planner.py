from __future__ import annotations

from datetime import date
from pathlib import Path

import lake_console.backend.app.sync.helpers.dates as date_helper
import lake_console.backend.app.sync.planners.stk_mins as stk_mins_planner
from lake_console.backend.app.sync.planner import LakeSyncPlanner


def test_daily_plan_uses_local_open_trade_calendar_for_range(tmp_path, monkeypatch):
    monkeypatch.setattr(
        date_helper,
        "read_parquet_rows",
        lambda path: [
            {"cal_date": "20260424", "is_open": True},
            {"cal_date": "20260425", "is_open": False},
            {"cal_date": "20260427", "is_open": True},
        ],
    )
    (tmp_path / "manifest" / "trading_calendar").mkdir(parents=True)
    (tmp_path / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet").write_text("fake", encoding="utf-8")

    plan = LakeSyncPlanner(lake_root=tmp_path).plan(
        dataset_key="daily",
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 27),
    )

    assert plan.request_count == 2
    assert plan.partition_count == 2
    assert plan.write_paths == (
        "raw_tushare/daily/trade_date=2026-04-24",
        "raw_tushare/daily/trade_date=2026-04-27",
    )
    assert "manifest/trading_calendar/tushare_trade_cal.parquet" in plan.required_manifests


def test_stk_mins_plan_sync_estimates_current_and_target_requests_for_full_year_all_market(tmp_path, monkeypatch):
    def fake_read(path: Path) -> list[dict[str, object]]:
        if "trading_calendar" in str(path):
            rows: list[dict[str, object]] = []
            month_open_days = [21, 20, 21, 21, 20, 20, 21, 21, 20, 20, 20, 20]
            for month, open_days in enumerate(month_open_days, start=1):
                for day in range(1, open_days + 1):
                    rows.append({"cal_date": f"2025{month:02d}{day:02d}", "is_open": True})
            return rows
        return [{"ts_code": f"{index:06d}.SZ", "list_status": "L"} for index in range(5511)]

    monkeypatch.setattr(date_helper, "read_parquet_rows", fake_read)
    monkeypatch.setattr(stk_mins_planner, "read_parquet_rows", fake_read)
    (tmp_path / "manifest" / "trading_calendar").mkdir(parents=True)
    (tmp_path / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet").write_text("fake", encoding="utf-8")
    (tmp_path / "manifest" / "security_universe").mkdir(parents=True)
    (tmp_path / "manifest" / "security_universe" / "tushare_stock_basic.parquet").write_text("fake", encoding="utf-8")

    plan = LakeSyncPlanner(lake_root=tmp_path, stk_mins_request_window_days=31).plan(
        dataset_key="stk_mins",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        all_market=True,
        freqs=[1, 5, 15, 30, 60],
        daily_quota_limit=250_000,
    )

    assert plan.request_count == 71_643
    assert plan.partition_count == 245 * 5
    assert plan.estimate is not None
    assert plan.estimate["implementation_status"] == "execution_aligned_target_windowing"
    assert plan.estimate["symbol_count"] == 5511
    assert plan.estimate["trade_date_count"] == 245
    assert plan.estimate["current_strategy"]["strategy_key"] == "historical_month_window_baseline"
    assert plan.estimate["current_strategy"]["window_count"] == 12
    assert plan.estimate["current_strategy"]["request_count"] == 330_660
    assert plan.estimate["target_strategy"]["request_count"] == 71_643
    assert plan.estimate["target_strategy"]["estimated_days_at_daily_quota"] == 1
    per_freq = {item["freq"]: item for item in plan.estimate["target_strategy"]["per_freq"]}
    assert per_freq[1]["trade_days_per_window"] == 33
    assert per_freq[1]["window_count"] == 8
    assert per_freq[5]["trade_days_per_window"] == 163
    assert per_freq[5]["window_count"] == 2
    assert per_freq[15]["window_count"] == 1
    assert per_freq[30]["rows_per_trade_day"] == 9
    assert per_freq[60]["rows_per_request_estimate"] == 1225


def test_stk_mins_plan_sync_single_symbol_range_does_not_require_local_stock_universe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        date_helper,
        "read_parquet_rows",
        lambda path: [
            {"cal_date": "20260401", "is_open": True},
            {"cal_date": "20260402", "is_open": False},
            {"cal_date": "20260403", "is_open": True},
        ],
    )
    (tmp_path / "manifest" / "trading_calendar").mkdir(parents=True)
    (tmp_path / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet").write_text("fake", encoding="utf-8")

    plan = LakeSyncPlanner(lake_root=tmp_path, stk_mins_request_window_days=31).plan(
        dataset_key="stk_mins",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 3),
        ts_code="600000.SH",
        freq=30,
        daily_quota_limit=250_000,
    )

    assert plan.request_count == 1
    assert plan.partition_count == 2
    assert plan.estimate is not None
    assert plan.estimate["symbol_scope"] == "single_symbol"
    assert plan.estimate["symbol_count"] == 1
    assert plan.estimate["trade_date_count"] == 2
    assert plan.estimate["current_strategy"]["request_count"] == 1
    assert plan.estimate["target_strategy"]["request_count"] == 1
