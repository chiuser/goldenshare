from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ops.models.ops.etf_series_active import EtfSeriesActive


ETF_SERIES_ACTIVE_RESOURCES: frozenset[str] = frozenset({"fund_daily", "etf_rt_daily"})
ETF_SERIES_ACTIVE_SEED_EXPECTED_ROWS = 1395
ETF_SERIES_ACTIVE_ALLOWED_SELECTION_GROUPS: frozenset[str] = frozenset(
    {"complete_1364", "accepted_low_gap_liquid_31"}
)


@dataclass(frozen=True, slots=True)
class EtfSeriesActiveSeedReport:
    dry_run: bool
    resource: str
    seed_csv_path: str
    candidate_count: int
    created_count: int
    skipped_count: int
    invalid_count: int


class EtfSeriesActiveSeedService:
    def run(
        self,
        session: Session,
        *,
        resource: str,
        seed_csv_path: Path,
        dry_run: bool = True,
    ) -> EtfSeriesActiveSeedReport:
        normalized_resource = _normalize_resource(resource)
        seed_rows = _load_seed_rows(seed_csv_path)
        existing_codes = set(
            session.scalars(
                select(EtfSeriesActive.ts_code).where(EtfSeriesActive.resource == normalized_resource)
            )
        )
        missing_rows = [row for row in seed_rows if row.ts_code not in existing_codes]
        checked_at = datetime.now(timezone.utc)

        if not dry_run:
            for row in missing_rows:
                session.add(
                    EtfSeriesActive(
                        resource=normalized_resource,
                        ts_code=row.ts_code,
                        first_seen_date=row.latest_matched_trade_date,
                        last_seen_date=row.latest_matched_trade_date,
                        last_checked_at=checked_at,
                    )
                )
            session.commit()

        return EtfSeriesActiveSeedReport(
            dry_run=dry_run,
            resource=normalized_resource,
            seed_csv_path=str(seed_csv_path),
            candidate_count=len(seed_rows),
            created_count=len(missing_rows),
            skipped_count=len(seed_rows) - len(missing_rows),
            invalid_count=0,
        )


@dataclass(frozen=True, slots=True)
class _SeedRow:
    ts_code: str
    latest_matched_trade_date: date


def _normalize_resource(resource: str) -> str:
    normalized = str(resource or "").strip()
    if normalized not in ETF_SERIES_ACTIVE_RESOURCES:
        allowed = ", ".join(sorted(ETF_SERIES_ACTIVE_RESOURCES))
        raise ValueError(f"unsupported ETF active resource: {resource!r}; allowed={allowed}")
    return normalized


def _load_seed_rows(seed_csv_path: Path) -> tuple[_SeedRow, ...]:
    if not seed_csv_path.exists():
        raise FileNotFoundError(f"ETF active seed csv not found: {seed_csv_path}")
    with seed_csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    fieldnames = set(reader.fieldnames or [])
    required_fields = {"ts_code", "latest_matched_trade_date"}
    missing_fields = sorted(required_fields - fieldnames)
    if missing_fields:
        raise ValueError(f"ETF active seed csv missing required fields: {', '.join(missing_fields)}")
    if len(rows) != ETF_SERIES_ACTIVE_SEED_EXPECTED_ROWS:
        raise ValueError(
            "ETF active seed csv row count mismatch: "
            f"expected={ETF_SERIES_ACTIVE_SEED_EXPECTED_ROWS}, actual={len(rows)}"
        )

    parsed_rows: list[_SeedRow] = []
    seen_codes: set[str] = set()
    for index, raw_row in enumerate(rows, start=2):
        ts_code = str(raw_row.get("ts_code") or "").strip().upper()
        if not ts_code:
            raise ValueError(f"ETF active seed csv row {index}: ts_code is required")
        if ts_code in seen_codes:
            raise ValueError(f"ETF active seed csv duplicated ts_code: {ts_code}")
        if ts_code.endswith(".OF"):
            raise ValueError(f"ETF active seed csv row {index}: .OF code is not allowed: {ts_code}")
        if not (ts_code.endswith(".SH") or ts_code.endswith(".SZ")):
            raise ValueError(f"ETF active seed csv row {index}: unsupported ts_code suffix: {ts_code}")

        selection_group = str(raw_row.get("selection_group") or "").strip()
        if selection_group and selection_group not in ETF_SERIES_ACTIVE_ALLOWED_SELECTION_GROUPS:
            raise ValueError(
                f"ETF active seed csv row {index}: unsupported selection_group={selection_group!r}"
            )

        latest_matched_trade_date_text = str(raw_row.get("latest_matched_trade_date") or "").strip()
        if not latest_matched_trade_date_text:
            raise ValueError(f"ETF active seed csv row {index}: latest_matched_trade_date is required")
        try:
            latest_matched_trade_date = date.fromisoformat(latest_matched_trade_date_text)
        except ValueError as exc:
            raise ValueError(
                f"ETF active seed csv row {index}: invalid latest_matched_trade_date={latest_matched_trade_date_text!r}"
            ) from exc

        seen_codes.add(ts_code)
        parsed_rows.append(
            _SeedRow(
                ts_code=ts_code,
                latest_matched_trade_date=latest_matched_trade_date,
            )
        )

    return tuple(parsed_rows)
