"""Independent history stages; physical commit never depends on Dagster events."""

import hashlib
import time
from pathlib import Path

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    AnnouncementControl,
    announcement_file_fingerprint,
    announcement_file_lock,
)
from orchestrator.defs.anns_d_contract import AnnouncementCancelled, AnnouncementError
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.bootstrap.anns_d_history import (
    build_announcement_month,
    capture_announcement_month,
)
from orchestrator.defs.bootstrap.anns_d_history_audit import (
    audit_announcement_history_month,
)
from orchestrator.defs.bootstrap.anns_d_history_plan import (
    announcement_bootstrap_volume_gate,
    history_document_fingerprint,
)
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy


class AnnouncementHistoryControl(AnnouncementControl):
    def __init__(self, parent, seconds):
        self.parent = parent
        self.deadline = time.monotonic() + seconds
        super().__init__(
            cancelled=lambda: parent.cancelled() or time.monotonic() >= self.deadline,
            emit=lambda event: parent.progress(**event),
        )

    def check(self):
        self.parent.check()
        if time.monotonic() >= self.deadline:
            raise AnnouncementError("announcement_month_timeout")


class FrozenAnnouncementHistorySource:
    def __init__(self, source, month):
        self.source, self.month = source, month

    def batches(self, month, upper_id, control, on_plan):
        def inspect(summary):
            if summary["expected_rows"] != self.month["source_rows"]:
                raise AnnouncementError("announcement_history_plan_source_changed")
            on_plan(summary)

        yield from self.source.batches(month, upper_id, control, on_plan=inspect)


def announcement_history_run_id(plan, month):
    return hashlib.sha256(
        f"{plan['run_id']}:{plan['fingerprint']}:{month['month']}".encode()
    ).hexdigest()[:32]


def announcement_history_store(plan, month, control):
    root, staging = Path(plan["lake_root"]), Path(plan["staging_root"])
    announcement_bootstrap_volume_gate(root, staging)
    run_id = announcement_history_run_id(plan, month)
    return AnnouncementStore(
        root, staging, run_id, AnnouncementPolicy(**plan["policy"]), control
    )


def announcement_month_checkpoint(plan, month, store):
    return AnnouncementCheckpoint(
        store.directory / "capture.json",
        {"plan_fingerprint": plan["fingerprint"], "month": month["month"]},
    )


def announcement_history_day_checkpoint(plan, day, store):
    run_id = hashlib.sha256(
        f"{plan['fingerprint']}:delivery:{day}".encode()
    ).hexdigest()[:32]
    return AnnouncementCheckpoint(
        store.staging / "anns_d" / f"run_id={run_id}" / "delivery.json",
        {"plan_fingerprint": plan["fingerprint"], "day": day, "policy": plan["policy"]},
    )


def verify_announcement_history_targets(month, store, checkpoint):
    for day in month["days"]:
        current = announcement_file_fingerprint(store.target(day["day"]))
        delivery = checkpoint.document.get("deliveries", {}).get(day["day"])
        # A file can only move from the frozen baseline to this plan's proven output.
        if current != day["baseline"] and (
            not delivery or current != delivery["fingerprint"]
        ):
            raise AnnouncementError("announcement_history_target_conflict")


def run_announcement_history_stage(
    stage, plan, month, control, *, source=None, audit=None, formal=False
):
    started_at = time.monotonic()
    control = AnnouncementHistoryControl(control, plan["policy"]["month_deadline"])
    store = announcement_history_store(plan, month, control)
    with announcement_file_lock(
        store.staging / "anns_d" / "locks" / "history-execution.lock"
    ):
        checkpoint = announcement_month_checkpoint(plan, month, store)
        verify_announcement_history_targets(month, store, checkpoint)
        control.progress(
            phase=stage, month=month["month"], source_rows=month["source_rows"]
        )
        try:
            if stage == "capture":
                capture_announcement_month(
                    month["month"],
                    FrozenAnnouncementHistorySource(source, month),
                    month["upper_id"],
                    store,
                    checkpoint,
                    control,
                )
            elif stage == "build":
                pages = tuple(
                    Path(page["path"]) for page in checkpoint.document.get("pages", [])
                )
                deliveries = build_announcement_month(
                    month["month"], pages, store, checkpoint, control
                )
                if any(
                    deliveries[d["day"]]["source_rows"] != d["source_rows"]
                    for d in month["days"]
                ):
                    raise AnnouncementError("announcement_history_day_source_count")
            elif stage == "audit":
                result = audit_announcement_history_month(
                    plan, month, store, checkpoint, formal=formal
                )
                checkpoint.save(
                    last_stage=stage, elapsed_seconds=time.monotonic() - started_at
                )
                return result
            elif stage == "promote":
                if (
                    not audit
                    or audit.get("fingerprint") != history_document_fingerprint(audit)
                    or audit.get("kind") != "anns_d_history_audit"
                    or not audit.get("passed")
                    or audit.get("plan_fingerprint") != plan["fingerprint"]
                    or audit.get("month") != month["month"]
                ):
                    raise AnnouncementError("announcement_history_green_audit_required")
                current_audit = audit_announcement_history_month(
                    plan, month, store, checkpoint
                )
                for key in (
                    "source_rows",
                    "written_rows",
                    "days",
                    "set_difference_rows",
                ):
                    if current_audit[key] != audit.get(key):
                        raise AnnouncementError("announcement_history_audit_changed")
                # The audited source and output hashes are also frozen across stages.
                for index, day in enumerate(month["days"], start=1):
                    delivery = checkpoint.document["deliveries"][day["day"]]
                    candidate, target = (
                        str(delivery["candidate"]),
                        str(store.target(day["day"])),
                    )
                    if (
                        audit.get("files", {}).get(
                            candidate, audit.get("files", {}).get(target)
                        )
                        != delivery["fingerprint"]
                    ):
                        raise AnnouncementError("announcement_history_audit_changed")
                    control.check()
                    child = announcement_history_day_checkpoint(plan, day["day"], store)
                    store.promote_day(day["day"], delivery, child)
                    control.progress(
                        phase="promoted",
                        month=month["month"],
                        day=day["day"],
                        days_completed=index,
                        total_days=len(month["days"]),
                    )
                checkpoint.save(phase="promoted")
            else:
                raise AnnouncementError("announcement_history_stage")
        except (AnnouncementCancelled, KeyboardInterrupt):
            checkpoint.save(phase="cancelled", reason="announcement_cancelled")
            raise
        except Exception as error:
            checkpoint.save(
                phase="failed",
                reason=str(error)
                if isinstance(error, AnnouncementError)
                else "announcement_history_stage_failed",
            )
            raise
        elapsed = time.monotonic() - started_at
        checkpoint.save(last_stage=stage, elapsed_seconds=elapsed)
        return {
            "month": month["month"],
            "phase": checkpoint.document["phase"],
            "checkpoint": str(checkpoint.path),
            "source_rows": month["source_rows"],
            "elapsed_seconds": elapsed,
        }
