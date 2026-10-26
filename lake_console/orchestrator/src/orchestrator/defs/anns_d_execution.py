"""Daily execution composition without Dagster registration or event side effects."""

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    announcement_file_fingerprint,
    announcement_file_lock,
)
from orchestrator.defs.anns_d_contract import AnnouncementCancelled, AnnouncementError
from orchestrator.defs.anns_d_source import capture_announcement_day


def _record_day_failure(checkpoint, error, *, cancelled):
    phase = "cancelled" if cancelled else "failed"
    reason = str(error) if isinstance(error, AnnouncementError) else type(error).__name__
    # save() updates memory before writing: only persisted proof establishes promotion.
    persisted = (
        AnnouncementCheckpoint(checkpoint.path, checkpoint.identity).document
        if checkpoint.path.exists()
        else None
    )
    if persisted and persisted.get("phase") == "promoted" and persisted.get("delivery"):
        checkpoint.document = persisted
        checkpoint.save(failure_phase=phase, reason=reason)
    else:
        checkpoint.save(
            phase=phase,
            reason="announcement_cancelled" if cancelled else "announcement_execution_failed",
        )


def _clear_day_failure(checkpoint):
    if "failure_phase" in checkpoint.document or "reason" in checkpoint.document:
        checkpoint.document.pop("failure_phase", None)
        checkpoint.document.pop("reason", None)
        checkpoint.save()


def update_announcement_day(
    day, call, store, checkpoint, control, budget, policy, *, window_dates=None
):
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
                _clear_day_failure(checkpoint)
                return delivery
            captured = capture_announcement_day(
                day,
                call,
                store,
                checkpoint,
                control,
                budget,
                policy,
                window_dates=window_dates,
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
        _clear_day_failure(checkpoint)
        return delivery
    except (AnnouncementCancelled, KeyboardInterrupt) as error:
        _record_day_failure(checkpoint, error, cancelled=True)
        raise
    except Exception as error:
        _record_day_failure(checkpoint, error, cancelled=False)
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
