from __future__ import annotations

import csv
from pathlib import Path


SEED_PATH = Path("reports/etf_series_active_seed_1395_20260617.csv")
ACCEPTED_GAPS_PATH = Path("reports/etf_series_active_fund_daily_accepted_gaps_31_20260617.csv")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_etf_active_pool_seed_report_shape() -> None:
    rows = _read_csv(SEED_PATH)
    codes = {row["ts_code"].strip().upper() for row in rows}

    assert len(rows) == 1395
    assert len(codes) == 1395
    assert not any(code.endswith(".OF") for code in codes)
    assert all(code.endswith(".SH") or code.endswith(".SZ") for code in codes)
    assert {row["selection_group"] for row in rows} == {"complete_1364", "accepted_low_gap_liquid_31"}
    assert all(row["latest_matched_trade_date"] for row in rows)


def test_etf_active_pool_accepted_gaps_report_shape() -> None:
    seed_codes = {row["ts_code"].strip().upper() for row in _read_csv(SEED_PATH)}
    gap_rows = _read_csv(ACCEPTED_GAPS_PATH)
    gap_codes = {row["ts_code"].strip().upper() for row in gap_rows}

    assert len(gap_rows) == 65
    assert len(gap_codes) == 31
    assert gap_codes <= seed_codes
    assert {row["resource"] for row in gap_rows} == {"fund_daily"}
    assert {row["gap_policy"] for row in gap_rows} == {"accepted_low_gap_liquid"}
