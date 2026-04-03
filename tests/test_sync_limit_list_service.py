from __future__ import annotations

from datetime import date

from src.services.sync.sync_limit_list_service import build_limit_list_params


def test_build_limit_list_params_supports_incremental_filters() -> None:
    params = build_limit_list_params(
        "INCREMENTAL",
        trade_date=date(2026, 4, 3),
        limit_type=["U", "Z"],
        exchange=["SH", "SZ"],
    )

    assert params == {
        "trade_date": "20260403",
        "limit_type": "U,Z",
        "exchange": "SH,SZ",
    }


def test_build_limit_list_params_supports_full_range_filters() -> None:
    params = build_limit_list_params(
        "FULL",
        start_date="2026-03-01",
        end_date="2026-03-31",
        limit_type="D",
        exchange="BJ",
    )

    assert params == {
        "start_date": "20260301",
        "end_date": "20260331",
        "limit_type": "D",
        "exchange": "BJ",
    }
