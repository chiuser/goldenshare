from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select

from src.db import SessionLocal
from src.foundation.models.core.equity_top_list import EquityTopList
from src.foundation.services.transform.top_list_reason import hash_top_list_reason


@dataclass
class TopListReasonHashRepairSummary:
    scanned: int
    updated: int
    skipped_missing_reason: int
    conflicts: int


def find_top_list_reason_hash_conflicts(session) -> list[tuple[str, object, str, int]]:
    stmt = select(EquityTopList.ts_code, EquityTopList.trade_date, EquityTopList.reason)
    grouped: dict[tuple[str, object, str], int] = defaultdict(int)
    for ts_code, trade_date, reason in session.execute(stmt):
        reason_hash = hash_top_list_reason(reason)
        if reason_hash is None:
            continue
        grouped[(ts_code, trade_date, reason_hash)] += 1
    return [
        (ts_code, trade_date, reason_hash, count)
        for (ts_code, trade_date, reason_hash), count in grouped.items()
        if count > 1
    ]


def repair_top_list_reason_hash(session) -> TopListReasonHashRepairSummary:
    conflicts = find_top_list_reason_hash_conflicts(session)
    if conflicts:
        raise ValueError(f"Found {len(conflicts)} top_list reason_hash conflicts before repair")

    stmt = select(EquityTopList.ts_code, EquityTopList.trade_date, EquityTopList.reason).where(EquityTopList.reason_hash.is_(None))
    mappings: list[dict[str, object]] = []
    scanned = 0
    skipped_missing_reason = 0
    for ts_code, trade_date, reason in session.execute(stmt):
        scanned += 1
        reason_hash = hash_top_list_reason(reason)
        if reason_hash is None:
            skipped_missing_reason += 1
            continue
        mappings.append(
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "reason": reason,
                "reason_hash": reason_hash,
            }
        )
    if mappings:
        session.bulk_update_mappings(EquityTopList, mappings)
    return TopListReasonHashRepairSummary(
        scanned=scanned,
        updated=len(mappings),
        skipped_missing_reason=skipped_missing_reason,
        conflicts=len(conflicts),
    )


def main() -> None:
    with SessionLocal() as session:
        summary = repair_top_list_reason_hash(session)
        session.commit()
        print(
            "equity_top_list reason_hash repair "
            f"scanned={summary.scanned} updated={summary.updated} "
            f"skipped_missing_reason={summary.skipped_missing_reason} conflicts={summary.conflicts}"
        )


if __name__ == "__main__":
    main()
