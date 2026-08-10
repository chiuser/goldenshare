#!/usr/bin/env python3
"""Fetch the 2025 public financial/shareholder snapshots for the power report.

Run with TUSHARE_TOKEN in the environment.  The input universe/valuation CSV is
generated from the bounded Prod read-only query documented in the report.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import tushare as ts


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "a_share_power_industry_20260803_prod.csv"
FINANCIAL_OUTPUT = ROOT / "a_share_power_industry_20260803_financials.csv"
HOLDERS_OUTPUT = ROOT / "a_share_power_industry_20260803_shareholders.csv"
META_OUTPUT = ROOT / "a_share_power_industry_20260803_public_extract_meta.json"
REPORT_PERIOD = "20251231"

FINANCIAL_FIELDS = (
    "ts_code,ann_date,end_date,netprofit_margin,grossprofit_margin,roe,"
    "netprofit_yoy,tr_yoy,debt_to_assets"
)
HOLDER_FIELDS = "ts_code,ann_date,end_date,holder_name,hold_ratio,holder_type"


def request_with_retry(call, *, label: str, attempts: int = 3):
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:  # Tushare error classes vary by client version.
            if attempt == attempts:
                raise RuntimeError(f"{label} failed after {attempts} attempts: {exc}") from exc
            time.sleep(1.5 * attempt)


def latest_disclosure(rows: pd.DataFrame) -> pd.DataFrame:
    """Keep only the latest disclosed annual row if a restatement creates duplicates."""
    if rows.empty:
        return rows
    return (
        rows.sort_values(["ts_code", "ann_date"], ascending=[True, False])
        .drop_duplicates(subset=["ts_code"], keep="first")
        .sort_values("ts_code")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sleep-seconds", type=float, default=0.18)
    parser.add_argument("--start", type=int, default=1, help="1-based inclusive universe position")
    parser.add_argument("--end", type=int, help="1-based inclusive universe position")
    args = parser.parse_args()

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise SystemExit("TUSHARE_TOKEN is required; it is not written to any output file.")
    if not INPUT.exists():
        raise SystemExit(f"Missing Prod universe file: {INPUT}")

    universe = pd.read_csv(INPUT, dtype={"ts_code": "string"})
    codes = universe["ts_code"].dropna().tolist()
    if args.start < 1 or args.start > len(codes):
        raise SystemExit(f"--start must be between 1 and {len(codes)}")
    end = args.end if args.end is not None else len(codes)
    if end < args.start or end > len(codes):
        raise SystemExit(f"--end must be between {args.start} and {len(codes)}")
    selected_codes = codes[args.start - 1 : end]
    pro = ts.pro_api(token)

    financial_frames: list[pd.DataFrame] = []
    shareholder_frames: list[pd.DataFrame] = []
    failures: list[dict[str, str]] = []

    for position, code in enumerate(selected_codes, start=args.start):
        try:
            financial = request_with_retry(
                lambda: pro.fina_indicator(
                    ts_code=code,
                    period=REPORT_PERIOD,
                    fields=FINANCIAL_FIELDS,
                ),
                label=f"fina_indicator {code}",
            )
            if not financial.empty:
                financial_frames.append(financial)
        except Exception as exc:
            failures.append({"ts_code": code, "dataset": "fina_indicator", "error": str(exc)})

        time.sleep(args.sleep_seconds)

        try:
            holders = request_with_retry(
                lambda: pro.top10_holders(
                    ts_code=code,
                    period=REPORT_PERIOD,
                    fields=HOLDER_FIELDS,
                ),
                label=f"top10_holders {code}",
            )
            if not holders.empty:
                shareholder_frames.append(holders)
        except Exception as exc:
            failures.append({"ts_code": code, "dataset": "top10_holders", "error": str(exc)})

        time.sleep(args.sleep_seconds)
        print(f"{position}/{len(codes)} {code}", flush=True)

    batch_financials = (
        latest_disclosure(pd.concat(financial_frames, ignore_index=True))
        if financial_frames
        else pd.DataFrame(columns=FINANCIAL_FIELDS.split(","))
    )
    batch_holders = (
        pd.concat(shareholder_frames, ignore_index=True)
        if shareholder_frames
        else pd.DataFrame(columns=HOLDER_FIELDS.split(","))
    )
    existing_financials = (
        pd.read_csv(FINANCIAL_OUTPUT, dtype={"ts_code": "string"})
        if FINANCIAL_OUTPUT.exists()
        else pd.DataFrame(columns=FINANCIAL_FIELDS.split(","))
    )
    existing_holders = (
        pd.read_csv(HOLDERS_OUTPUT, dtype={"ts_code": "string"})
        if HOLDERS_OUTPUT.exists()
        else pd.DataFrame(columns=HOLDER_FIELDS.split(","))
    )
    financials = latest_disclosure(pd.concat([existing_financials, batch_financials], ignore_index=True))
    holders = (
        pd.concat([existing_holders, batch_holders], ignore_index=True)
        .drop_duplicates()
        .sort_values(["ts_code", "holder_name"])
    )
    financials.to_csv(FINANCIAL_OUTPUT, index=False)
    holders.to_csv(HOLDERS_OUTPUT, index=False)
    previous_failures: list[dict[str, str]] = []
    if META_OUTPUT.exists():
        previous_failures = json.loads(META_OUTPUT.read_text(encoding="utf-8")).get("failures", [])
    META_OUTPUT.write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "report_period": REPORT_PERIOD,
                "source": "Tushare Pro public company disclosure aggregation",
                "financial_api": "fina_indicator",
                "shareholder_api": "top10_holders",
                "universe_rows": len(codes),
                "processed_positions": [args.start, end],
                "financial_rows": len(financials),
                "shareholder_rows": len(holders),
                "failures": previous_failures + failures,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
