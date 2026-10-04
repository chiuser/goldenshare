"""Daily execution composition without Dagster registration or event side effects."""

from orchestrator.defs.anns_d_checkpoint import (
    announcement_file_fingerprint,
    announcement_file_lock,
)
from orchestrator.defs.anns_d_contract import AnnouncementCancelled, AnnouncementError
from orchestrator.defs.anns_d_source import capture_announcement_day


def update_announcement_day(day, call, store, checkpoint, control, budget, policy):
    """Return verified delivery; the future asset separately records its event."""
    try:
        with announcement_file_lock(
            store.staging / "anns_d" / "locks" / "source-execution.lock"
        ):
            # Exclusive source execution makes recovery of a dead parent's claim safe.
            budget.recover_interrupted()
            delivery = checkpoint.document.get("delivery")
            if delivery:
                store.promote_day(day, delivery, checkpoint)
                control.progress(
                    phase="promoted",
                    day=day,
                    **{
                        key: delivery[key]
                        for key in ("source_rows", "written_rows", "new_unique_rows")
                    },
                )
                return delivery
            captured = capture_announcement_day(
                day, call, store, checkpoint, control, budget, policy
            )
        control.check()
        delivery = store.build_day(day, captured.pages)
        if delivery["source_rows"] != captured.rows:
            raise AnnouncementError("announcement_capture_row_count")
        delivery.update(
            source_pages=checkpoint.document["pages"],
            capture_complete=True,
            page_count=len(captured.pages),
            last_offset=captured.last_offset,
            last_page_rows=captured.last_page_rows,
            requests=captured.requests,
        )
        checkpoint.save(phase="validated", delivery=delivery)
        store.promote_day(day, delivery, checkpoint)
        control.progress(
            phase="promoted",
            day=day,
            source_rows=captured.rows,
            written_rows=delivery["written_rows"],
            new_unique_rows=delivery["new_unique_rows"],
        )
        return delivery
    except (AnnouncementCancelled, KeyboardInterrupt):
        checkpoint.save(phase="cancelled", reason="announcement_cancelled")
        raise
    except Exception:
        checkpoint.save(phase="failed", reason="announcement_execution_failed")
        raise


def verify_announcement_delivery(store, day, checkpoint):
    """Pure file/evidence check; no source calls or permanent state projection."""
    document = checkpoint.document
    delivery = document.get("delivery")
    if not delivery or document.get("phase") != "promoted":
        raise AnnouncementError("announcement_delivery_missing")
    if announcement_file_fingerprint(store.target(day)) != delivery["fingerprint"]:
        raise AnnouncementError("announcement_delivery_file_changed")
    if not delivery.get("capture_complete"):
        raise AnnouncementError("announcement_delivery_incomplete")
    for page in delivery.get("source_pages", []):
        if announcement_file_fingerprint(page["path"]) != page["fingerprint"]:
            raise AnnouncementError("announcement_delivery_source_changed")
    counts = store.audit_file(store.target(day), day)
    if counts["written_rows"] != delivery["readback_rows"]:
        raise AnnouncementError("announcement_delivery_row_count")
    if (
        "last_page_rows" in delivery
        and delivery["last_page_rows"] >= store.policy.page_size
    ):
        raise AnnouncementError("announcement_delivery_truncated")
    return delivery
