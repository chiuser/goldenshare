from __future__ import annotations

from datetime import date

import pytest

from src.biz.services.wealth.market.nine_turn.nine_turn_response_policy import (
    build_nine_turn_response,
)


def test_nine_turn_response_rejects_payload_above_five_megabytes() -> None:
    with pytest.raises(ValueError, match="5MB"):
        build_nine_turn_response(
            subject_type="stock",
            ts_code="000001.SZ",
            period="day",
            rows=[{
                "trade_date": date(2026, 8, 13),
                "trade_time": None,
                "up_count": 1,
                "down_count": 0,
                "nine_turn_matched": True,
            }],
            source_row_count=1,
            matched_row_count=1,
            missing_row_count=0,
            has_more=False,
            next_cursor=None,
            start_date=None,
            end_date=date(2026, 8, 13),
            expected_end_date=date(2026, 8, 13),
            observed_start_date=date(2026, 8, 13),
            observed_end_date=date(2026, 8, 13),
            limit=1,
            debug_info={"oversized": "x" * 5_000_000},
        )
