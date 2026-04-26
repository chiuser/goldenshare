from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from src.db import SessionLocal
from src.foundation.services.transform.holdernumber_hash import build_holdernumber_event_key_hash, build_holdernumber_row_key_hash


@dataclass
class HolderNumberHashRepairSummary:
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


def repair_holdernumber_hashes_with_connection(connection) -> HolderNumberHashRepairSummary:
    raw_rows = connection.execute(
        text(
            """
            select id, ts_code, ann_date, end_date, holder_num
            from raw.holdernumber
            order by id
            """
        )
    ).mappings().all()
    raw_mappings = [{"id": row["id"], "row_key_hash": build_holdernumber_row_key_hash(row)} for row in raw_rows]
    raw_mappings, raw_duplicate_ids = _dedupe_by_key(raw_mappings, "row_key_hash")
    if raw_duplicate_ids:
        connection.execute(text("delete from raw.holdernumber where id = any(:ids)"), {"ids": raw_duplicate_ids})
    if raw_mappings:
        connection.execute(
            text("update raw.holdernumber set row_key_hash = :row_key_hash where id = :id"),
            raw_mappings,
        )

    core_rows = connection.execute(
        text(
            """
            select id, ts_code, ann_date, end_date, holder_num
            from core.equity_holder_number
            order by id
            """
        )
    ).mappings().all()
    core_mappings = [
        {
            "id": row["id"],
            "row_key_hash": build_holdernumber_row_key_hash(row),
            "event_key_hash": build_holdernumber_event_key_hash(row),
        }
        for row in core_rows
    ]
    core_mappings, core_duplicate_ids = _dedupe_by_key(core_mappings, "row_key_hash")
    if core_duplicate_ids:
        connection.execute(
            text("delete from core.equity_holder_number where id = any(:ids)"), {"ids": core_duplicate_ids}
        )
    if core_mappings:
        connection.execute(
            text(
                """
                update core.equity_holder_number
                set row_key_hash = :row_key_hash,
                    event_key_hash = :event_key_hash
                where id = :id
                """
            ),
            core_mappings,
        )

    return HolderNumberHashRepairSummary(
        raw_scanned=len(raw_rows),
        raw_updated=len(raw_mappings),
        raw_deleted=len(raw_duplicate_ids),
        core_scanned=len(core_rows),
        core_updated=len(core_mappings),
        core_deleted=len(core_duplicate_ids),
    )


def main() -> None:
    with SessionLocal() as session:
        summary = repair_holdernumber_hashes_with_connection(session.connection())
        session.commit()
        print(
            "holdernumber hash repair "
            f"raw_scanned={summary.raw_scanned} raw_updated={summary.raw_updated} raw_deleted={summary.raw_deleted} "
            f"core_scanned={summary.core_scanned} core_updated={summary.core_updated} core_deleted={summary.core_deleted}"
        )


if __name__ == "__main__":
    main()
