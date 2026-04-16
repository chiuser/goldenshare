from __future__ import annotations

from datetime import date

from src.foundation.services.transform.suspend_hash import build_suspend_d_row_key_hash


def test_suspend_d_row_key_hash_changes_when_record_changes() -> None:
    base = {
        "ts_code": "000001.SZ",
        "trade_date": date(2026, 4, 16),
        "suspend_timing": "09:30-10:00",
        "suspend_type": "S",
    }
    revised = {**base, "suspend_timing": "14:00-15:00"}

    assert build_suspend_d_row_key_hash(base) != build_suspend_d_row_key_hash(revised)


def test_suspend_d_row_key_hash_is_stable_length() -> None:
    row = {
        "ts_code": "000001.SZ",
        "trade_date": date(2026, 4, 16),
        "suspend_timing": None,
        "suspend_type": "R",
    }

    assert len(build_suspend_d_row_key_hash(row)) == 64

