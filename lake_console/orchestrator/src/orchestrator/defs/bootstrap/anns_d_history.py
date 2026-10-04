"""Month-scoped announcement capture and individually committed day candidates."""

import uuid
from datetime import timedelta
from pathlib import Path

from orchestrator.defs.anns_d_checkpoint import (
    announcement_atomic_json,
    announcement_file_fingerprint,
)
from orchestrator.defs.anns_d_contract import AnnouncementCancelled, AnnouncementError
from orchestrator.defs.prod_db.anns_d import announcement_month_bounds


def capture_announcement_month(month, source, upper_id, store, checkpoint, control):
    first, _end = announcement_month_bounds(month)
    document = checkpoint.document
    if document.get("capture_complete"):
        for page in document["pages"]:
            if announcement_file_fingerprint(Path(page["path"])) != page["fingerprint"]:
                raise AnnouncementError("announcement_capture_changed")
        return tuple(Path(page["path"]) for page in document["pages"])
    attempt = store.directory / f"month-{first.isoformat()}-{uuid.uuid4().hex}"
    attempt.mkdir(parents=True)
    checkpoint.save(phase="capturing", capture_complete=False, pages=[])
    evidence, expected, count = [], {}, 0

    def record_plan(summary):
        expected.update(summary)
        checkpoint.save(source_plan=summary)

    try:
        for rows in source.batches(month, upper_id, control, on_plan=record_plan):
            control.check()
            path = store.write_page(
                rows, attempt / f"page-{len(evidence):05d}.parquet", control
            )
            count += len(rows)
            evidence.append(
                {
                    "path": str(path),
                    "rows": len(rows),
                    "fingerprint": announcement_file_fingerprint(path),
                }
            )
            checkpoint.save(pages=evidence, source_rows=count)
        if count != expected.get("expected_rows"):
            raise AnnouncementError("announcement_history_row_count")
        checkpoint.save(
            phase="captured", capture_complete=True, pages=evidence, source_rows=count
        )
        return tuple(Path(page["path"]) for page in evidence)
    except (AnnouncementCancelled, KeyboardInterrupt):
        checkpoint.save(phase="cancelled", reason="announcement_cancelled")
        raise
    except AnnouncementError as error:
        if error.source_sample is not None:
            announcement_atomic_json(attempt / "rejected-row.json", error.source_sample)
        checkpoint.save(phase="failed", reason=str(error))
        raise
    except Exception:
        checkpoint.save(phase="failed", reason="announcement_history_failed")
        raise


def build_announcement_month(month, pages, store, checkpoint, control):
    first, end = announcement_month_bounds(month)
    if not checkpoint.document.get("capture_complete"):
        raise AnnouncementError("announcement_month_capture_incomplete")
    expected_pages = tuple(Path(page["path"]) for page in checkpoint.document["pages"])
    if tuple(pages) != expected_pages:
        raise AnnouncementError("announcement_capture_pages_changed")
    for page in checkpoint.document["pages"]:
        if announcement_file_fingerprint(page["path"]) != page["fingerprint"]:
            raise AnnouncementError("announcement_capture_changed")
    days = tuple(
        (first + timedelta(days=index)).isoformat()
        for index in range((end - first).days)
    )
    deliveries = {}
    with store.connection() as connection:
        store._relation(connection, "month_capture", pages)
        connection.execute(
            "CREATE TABLE announcement_month_rows AS SELECT * FROM month_capture"
        )
        for day in days:
            control.check()
            deliveries[day] = store.build_day(
                day, (), bootstrap=True, month_connection=connection
            )
            deliveries[day].update(
                source_pages=checkpoint.document["pages"],
                capture_complete=True,
                source_plan=checkpoint.document["source_plan"],
            )
            control.progress(
                phase="building",
                day=day,
                days_completed=len(deliveries),
                days_total=len(days),
            )
    if (
        sum(value["source_rows"] for value in deliveries.values())
        != checkpoint.document["source_rows"]
    ):
        raise AnnouncementError("announcement_history_partition_rows")
    checkpoint.save(phase="validated", deliveries=deliveries)
    return deliveries


def promote_announcement_month(deliveries, store, checkpoints, control):
    # Every child checkpoint survives cancellation; no group-level transaction.
    for day, delivery in sorted(deliveries.items()):
        control.check()
        store.promote_day(day, delivery, checkpoints(day))
        control.progress(phase="promoted", day=day)
