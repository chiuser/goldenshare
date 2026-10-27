"""Daily execution composition without Dagster registration or event side effects."""

from collections.abc import Mapping

from orchestrator.defs.anns_d_checkpoint import (
    ANNOUNCEMENT_CANCELLATION_ERRORS,
    AnnouncementCheckpoint,
    announcement_file_fingerprint,
    announcement_file_lock,
)
from orchestrator.defs.anns_d_contract import (
    AnnouncementError,
    announcement_date,
)
from orchestrator.defs.anns_d_source import capture_announcement_day


def _record_day_failure(checkpoint, error, *, cancelled):
    phase = "cancelled" if cancelled else "failed"
    reason = (
        str(error) if isinstance(error, AnnouncementError) else type(error).__name__
    )
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
            reason="announcement_cancelled"
            if cancelled
            else "announcement_execution_failed",
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
    except ANNOUNCEMENT_CANCELLATION_ERRORS as error:
        _record_day_failure(checkpoint, error, cancelled=True)
        raise
    except Exception as error:
        _record_day_failure(checkpoint, error, cancelled=False)
        raise


def _nonnegative_integer(value):
    return type(value) is int and value >= 0


def _fingerprint_metadata(value):
    return (
        isinstance(value, Mapping)
        and _nonnegative_integer(value.get("size"))
        and isinstance(value.get("sha256"), str)
        and len(value["sha256"]) == 64
        and all(character in "0123456789abcdefABCDEF" for character in value["sha256"])
    )


def announcement_capture_pages(checkpoint, *, page_size):
    """Validate actual daily/monthly producer metadata without reading files."""
    identity = checkpoint.identity
    if not isinstance(identity, Mapping) or not isinstance(
        identity.get("policy"), Mapping
    ):
        raise AnnouncementError("announcement_checkpoint_identity")
    try:
        announcement_date(identity.get("day"))
    except AnnouncementError:
        raise AnnouncementError("announcement_checkpoint_identity") from None
    daily = "window_id" in identity
    history = "plan_fingerprint" in identity
    if daily == history:
        raise AnnouncementError("announcement_checkpoint_identity")
    if daily:
        identifier = identity["window_id"]
        if (
            not isinstance(identifier, str)
            or not identifier
            or not identifier.replace("-", "").replace("_", "").isalnum()
        ):
            raise AnnouncementError("announcement_checkpoint_identity")
    else:
        identifier = identity["plan_fingerprint"]
        if (
            not isinstance(identifier, str)
            or len(identifier) != 64
            or any(character not in "0123456789abcdef" for character in identifier)
        ):
            raise AnnouncementError("announcement_checkpoint_identity")
    delivery = checkpoint.document.get("delivery")
    if (
        not isinstance(delivery, Mapping)
        or delivery.get("capture_complete") is not True
    ):
        raise AnnouncementError("announcement_delivery_incomplete")
    pages = delivery.get("source_pages")
    if not isinstance(pages, list) or not _fingerprint_metadata(
        delivery.get("fingerprint")
    ):
        raise AnnouncementError("announcement_delivery_incomplete")
    if not all(
        _nonnegative_integer(delivery.get(key))
        for key in ("source_rows", "readback_rows")
    ):
        raise AnnouncementError("announcement_delivery_incomplete")
    for page in pages:
        if (
            not isinstance(page, Mapping)
            or not isinstance(page.get("path"), str)
            or not page["path"]
            or not _nonnegative_integer(page.get("rows"))
            or not _fingerprint_metadata(page.get("fingerprint"))
        ):
            raise AnnouncementError("announcement_delivery_incomplete")
    if history:
        source_plan = delivery.get("source_plan")
        if not isinstance(source_plan, Mapping) or not _nonnegative_integer(
            source_plan.get("expected_rows")
        ):
            raise AnnouncementError("announcement_delivery_incomplete")
        expected = source_plan["expected_rows"]
        # History pages describe the whole month; source_rows describes this day.
        if (
            sum(page["rows"] for page in pages) != expected
            or delivery["source_rows"] > expected
        ):
            raise AnnouncementError("announcement_delivery_row_count")
        return tuple(pages)
    if (
        not pages
        or type(page_size) is not int
        or page_size != 2000
        or not all(
            _nonnegative_integer(delivery.get(key))
            for key in ("page_count", "last_offset", "last_page_rows")
        )
    ):
        raise AnnouncementError("announcement_delivery_incomplete")
    last_rows = delivery["last_page_rows"]
    if last_rows >= page_size:
        raise AnnouncementError("announcement_delivery_truncated")
    last_offset = (len(pages) - 1) * page_size
    if (
        delivery["page_count"] != len(pages)
        or delivery["last_offset"] != last_offset
        or delivery["source_rows"] != last_offset + last_rows
    ):
        raise AnnouncementError("announcement_delivery_row_count")
    for index, page in enumerate(pages):
        if (
            type(page.get("offset")) is not int
            or page["offset"] != index * page_size
            or page["rows"] != (last_rows if index == len(pages) - 1 else page_size)
        ):
            raise AnnouncementError("announcement_delivery_row_count")
    return tuple(pages)


def verify_announcement_delivery(store, day, checkpoint):
    """Pure file/evidence check; no source calls or permanent state projection."""
    document = checkpoint.document
    delivery = document.get("delivery")
    if not delivery or document.get("phase") != "promoted":
        raise AnnouncementError("announcement_delivery_missing")
    pages = announcement_capture_pages(checkpoint, page_size=store.policy.page_size)
    if announcement_file_fingerprint(store.target(day)) != delivery["fingerprint"]:
        raise AnnouncementError("announcement_delivery_file_changed")
    for page in pages:
        if announcement_file_fingerprint(page["path"]) != page["fingerprint"]:
            raise AnnouncementError("announcement_delivery_source_changed")
    counts = store.audit_file(store.target(day), day)
    if counts["written_rows"] != delivery["readback_rows"]:
        raise AnnouncementError("announcement_delivery_row_count")
    return delivery
