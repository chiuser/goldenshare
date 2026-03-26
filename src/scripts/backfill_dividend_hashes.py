from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import text

from src.db import SessionLocal
from src.services.transform.dividend_hash import build_dividend_event_key_hash, build_dividend_row_key_hash


@dataclass
class DividendHashBackfillSummary:
    raw_scanned: int
    raw_updated: int
    raw_deleted: int
    core_scanned: int
    core_updated: int
    core_deleted: int


def _dedupe_by_key(
    mappings: list[dict[str, object]], key_field: str
) -> tuple[list[dict[str, object]], list[int]]:
    winners: dict[object, dict[str, object]] = {}
    duplicate_ids: list[int] = []
    for mapping in mappings:
        key = mapping[key_field]
        existing = winners.get(key)
        if existing is None:
            winners[key] = mapping
            continue
        existing_id = int(existing["id"])
        current_id = int(mapping["id"])
        if current_id > existing_id:
            duplicate_ids.append(existing_id)
            winners[key] = mapping
        else:
            duplicate_ids.append(current_id)
    deduped = sorted(winners.values(), key=lambda item: int(item["id"]))
    return deduped, duplicate_ids


def _assert_no_conflicts(kind: str, mappings: list[dict[str, object]], key_field: str) -> None:
    counts = Counter(mapping[key_field] for mapping in mappings)
    conflicts = [key for key, count in counts.items() if count > 1]
    if conflicts:
        raise ValueError(f"{kind} backfill found {len(conflicts)} duplicate {key_field} values after dedupe")


def backfill_dividend_hashes_with_connection(connection) -> DividendHashBackfillSummary:
    raw_rows = connection.execute(
        text(
            """
            select id, ts_code, end_date, ann_date, div_proc, stk_div, stk_bo_rate, stk_co_rate,
                   cash_div, cash_div_tax, record_date, ex_date, pay_date, div_listdate,
                   imp_ann_date, base_date, base_share
            from raw.dividend
            order by id
            """
        )
    ).mappings().all()
    raw_mappings = [
        {"id": row["id"], "row_key_hash": build_dividend_row_key_hash(row)}
        for row in raw_rows
    ]
    raw_mappings, raw_duplicate_ids = _dedupe_by_key(raw_mappings, "row_key_hash")
    _assert_no_conflicts("raw.dividend", raw_mappings, "row_key_hash")
    if raw_duplicate_ids:
        connection.execute(text("delete from raw.dividend where id = any(:ids)"), {"ids": raw_duplicate_ids})
    if raw_mappings:
        connection.execute(
            text("update raw.dividend set row_key_hash = :row_key_hash where id = :id"),
            raw_mappings,
        )

    core_rows = connection.execute(
        text(
            """
            select id, ts_code, end_date, ann_date, div_proc, stk_div, stk_bo_rate, stk_co_rate,
                   cash_div, cash_div_tax, record_date, ex_date, pay_date, div_listdate,
                   imp_ann_date, base_date, base_share
            from core.equity_dividend
            order by id
            """
        )
    ).mappings().all()
    core_mappings = [
        {
            "id": row["id"],
            "row_key_hash": build_dividend_row_key_hash(row),
            "event_key_hash": build_dividend_event_key_hash(row),
        }
        for row in core_rows
    ]
    core_mappings, core_duplicate_ids = _dedupe_by_key(core_mappings, "row_key_hash")
    _assert_no_conflicts("core.equity_dividend", core_mappings, "row_key_hash")
    if core_duplicate_ids:
        connection.execute(text("delete from core.equity_dividend where id = any(:ids)"), {"ids": core_duplicate_ids})
    if core_mappings:
        connection.execute(
            text(
                """
                update core.equity_dividend
                set row_key_hash = :row_key_hash,
                    event_key_hash = :event_key_hash
                where id = :id
                """
            ),
            core_mappings,
        )

    return DividendHashBackfillSummary(
        raw_scanned=len(raw_rows),
        raw_updated=len(raw_mappings),
        raw_deleted=len(raw_duplicate_ids),
        core_scanned=len(core_rows),
        core_updated=len(core_mappings),
        core_deleted=len(core_duplicate_ids),
    )


def main() -> None:
    with SessionLocal() as session:
        summary = backfill_dividend_hashes_with_connection(session.connection())
        session.commit()
        print(
            "dividend hash backfill "
            f"raw_scanned={summary.raw_scanned} raw_updated={summary.raw_updated} raw_deleted={summary.raw_deleted} "
            f"core_scanned={summary.core_scanned} core_updated={summary.core_updated} core_deleted={summary.core_deleted}"
        )


if __name__ == "__main__":
    main()
