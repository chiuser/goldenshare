"""Read existing delivery evidence; temporary computation never writes Lake/staging."""

import json
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    announcement_file_fingerprint,
    assert_safe_announcement_path,
)
from orchestrator.defs.anns_d_contract import AnnouncementError, announcement_dates
from orchestrator.defs.anns_d_execution import verify_announcement_delivery
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.bootstrap.anns_d_history_audit import (
    audit_announcement_history_month,
)
from orchestrator.defs.bootstrap.anns_d_history_execution import (
    announcement_history_day_checkpoint,
    announcement_history_run_id,
    announcement_month_checkpoint,
)
from orchestrator.defs.bootstrap.anns_d_history_plan import (
    announcement_bootstrap_volume_gate,
    load_announcement_history_document,
    validate_announcement_history_plan,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy

EVENT_COMPUTE_MIN_FREE_BYTES = 25 * 1024**3


class AnnouncementEvidenceReader:
    """Only readonly Store methods; no Store constructor or promotion capability."""

    target = AnnouncementStore.target
    _relation = AnnouncementStore._relation
    _audit_relation = AnnouncementStore._audit_relation
    audit_file = AnnouncementStore.audit_file

    def __init__(
        self,
        directory,
        policy,
        control,
        *,
        root=DEFAULT_LAKE_ROOT,
        staging=DEFAULT_LAKE_STAGING_ROOT,
    ):
        self.root, self.staging = Path(root), Path(staging)
        announcement_bootstrap_volume_gate(self.root, self.staging)
        self.directory = assert_safe_announcement_path(directory)
        if (
            self.staging / "anns_d" not in self.directory.parents
            or not self.directory.is_dir()
        ):
            raise AnnouncementError("announcement_evidence_directory")
        self.policy, self.control = policy, control

    @contextmanager
    def connection(self):
        self.control.check()
        if shutil.disk_usage("/private/tmp").free < EVENT_COMPUTE_MIN_FREE_BYTES:
            raise AnnouncementError("announcement_event_compute_space")
        with TemporaryDirectory(
            prefix="anns-d-event-", dir="/private/tmp"
        ) as temporary:
            settings = DuckDBConnectionSettings(
                temp_directory=Path(temporary),
                memory_limit=self.policy.duckdb_memory,
                threads=self.policy.duckdb_threads,
                max_temp_directory_size=self.policy.spill_limit,
            )
            with connect_configured_duckdb(settings) as connection:
                connection.execute("SET autoinstall_known_extensions=false")
                connection.execute("SET autoload_known_extensions=false")
                stopped = threading.Event()

                def observe():
                    while not stopped.wait(0.1):
                        if self.control.cancelled():
                            connection.interrupt()
                            return
                        if time.monotonic() - self.control.last_report >= 5:
                            self.control.progress(phase="event_file_audit")

                monitor = threading.Thread(target=observe, daemon=True)
                monitor.start()
                try:
                    yield connection
                    self.control.check()
                except Exception:
                    self.control.check()
                    raise
                finally:
                    stopped.set()
                    monitor.join(timeout=1)


def _entry(store, day, cp, *, source_verified=False):
    delivery = cp.document.get("delivery", {})
    if cp.document.get("phase") != "promoted" or not delivery.get("capture_complete"):
        raise AnnouncementError("announcement_delivery_missing")
    announcement_dates(day, day)
    path = store.target(day)
    if announcement_file_fingerprint(path) != delivery.get("fingerprint"):
        raise AnnouncementError("announcement_delivery_file_changed")
    for page in [] if source_verified else delivery.get("source_pages", []):
        source = assert_safe_announcement_path(page["path"])
        if (
            store.staging / "anns_d" not in source.parents
            or announcement_file_fingerprint(source) != page["fingerprint"]
        ):
            raise AnnouncementError("announcement_delivery_source_changed")
    return {
        "day": day,
        "path": str(path),
        "file": delivery["fingerprint"],
        "rows": delivery["written_rows"],
        "source_rows": delivery["source_rows"],
        "checkpoint": str(cp.path),
        "checkpoint_file": announcement_file_fingerprint(cp.path),
        "identity": cp.identity,
    }


def read_announcement_event_files(spec, control, *, month=None):
    """Monthly history proof or at most seven completed daily deliveries."""
    entries = []
    if spec["mode"] == "history":
        plan = load_announcement_history_document(
            spec["history_plan"],
            kind="anns_d_history_plan",
            fingerprint=spec.get("history_fingerprint"),
        )
        validate_announcement_history_plan(plan)
        bundle = load_announcement_history_document(
            spec["history_audit"],
            kind="anns_d_history_audit_bundle",
            fingerprint=spec.get("audit_fingerprint"),
        )
        if bundle["plan_fingerprint"] != plan["fingerprint"]:
            raise AnnouncementError("announcement_event_history_identity")
        for group in plan["months"]:
            if month and group["month"] != month:
                continue
            control.check()
            directory = (
                Path(plan["staging_root"])
                / "anns_d"
                / f"run_id={announcement_history_run_id(plan, group)}"
            )
            store = AnnouncementEvidenceReader(
                directory,
                AnnouncementPolicy(**plan["policy"]),
                control,
                root=plan["lake_root"],
                staging=plan["staging_root"],
            )
            cp = announcement_month_checkpoint(plan, group, store)
            audit = audit_announcement_history_month(
                plan, group, store, cp, formal=True
            )
            expected = next(
                (a for a in bundle["months"] if a["month"] == group["month"]), None
            )
            if audit != expected:
                raise AnnouncementError("announcement_event_formal_audit_changed")
            for day in group["days"]:
                child = announcement_history_day_checkpoint(plan, day["day"], store)
                entry = _entry(store, day["day"], child, source_verified=True)
                original = cp.document["deliveries"][day["day"]]
                if (
                    entry["file"] != original["fingerprint"]
                    or entry["rows"] != original["written_rows"]
                    or entry["source_rows"] != day["source_rows"]
                ):
                    raise AnnouncementError("announcement_event_child_changed")
                # Child source evidence must be exactly the captured month pages.
                if (
                    child.document["delivery"].get("source_pages")
                    != cp.document["pages"]
                ):
                    raise AnnouncementError("announcement_event_child_source_changed")
                entry["capture_checkpoint"] = str(cp.path)
                entry["capture_checkpoint_file"] = announcement_file_fingerprint(
                    cp.path
                )
                entries.append(entry)
            control.progress(
                phase="event_file_audit",
                month=group["month"],
                audited_files=len(entries),
            )
    elif spec["mode"] == "daily":
        manifest = assert_safe_announcement_path(spec["delivery_manifest"])
        if not manifest.is_file() or manifest.stat().st_size > 65536:
            raise AnnouncementError("announcement_event_manifest_budget")
        paths = json.loads(manifest.read_text())
        if type(paths) is not list or not 1 <= len(paths) <= 7:
            raise AnnouncementError("announcement_event_daily_budget")
        if (
            spec.get("manifest_file")
            and announcement_file_fingerprint(manifest) != spec["manifest_file"]
        ):
            raise AnnouncementError("announcement_event_manifest_changed")
        for value in paths:
            path = assert_safe_announcement_path(value)
            if (
                Path(DEFAULT_LAKE_STAGING_ROOT) / "anns_d" not in path.parents
                or path.name != "delivery.json"
                or path.stat().st_size > 8 * 1024**2
            ):
                raise AnnouncementError("announcement_event_checkpoint_path")
            doc = json.loads(path.read_text())
            identity = doc["identity"]
            day = identity["day"]
            expected_policy = AnnouncementPolicy(
                interval_seconds=identity["policy"]["interval_seconds"]
            )

            if identity["policy"] != asdict(expected_policy):
                raise AnnouncementError("announcement_event_daily_policy")
            if month and day[:7] + "-01" != month:
                continue
            cp = AnnouncementCheckpoint(path, identity)
            store = AnnouncementEvidenceReader(
                path.parent, AnnouncementPolicy(**identity["policy"]), control
            )
            verify_announcement_delivery(store, day, cp)
            entries.append(_entry(store, day, cp))
    else:
        raise AnnouncementError("announcement_event_source_mode")
    if (
        not entries
        or len(entries) > 2465
        or len({e["day"] for e in entries}) != len(entries)
    ):
        raise AnnouncementError("announcement_event_file_budget")
    return sorted(entries, key=lambda e: e["day"])


def verify_announcement_event_evidence(entries):
    """Hash every evidence file once per month, including source pages, at readback."""
    pages = {}
    for entry in entries:
        path = assert_safe_announcement_path(entry["checkpoint"])
        if announcement_file_fingerprint(path) != entry["checkpoint_file"]:
            raise AnnouncementError("announcement_event_checkpoint_changed")
        doc = json.loads(path.read_text())
        if doc["identity"] != entry["identity"]:
            raise AnnouncementError("announcement_event_identity_changed")
        for page in doc["delivery"].get("source_pages", []):
            pages[page["path"]] = page["fingerprint"]
        if "capture_checkpoint_file" in entry and (
            announcement_file_fingerprint(entry["capture_checkpoint"])
            != entry["capture_checkpoint_file"]
        ):
            raise AnnouncementError("announcement_event_capture_changed")
    for path, expected in pages.items():
        if (
            announcement_file_fingerprint(assert_safe_announcement_path(path))
            != expected
        ):
            raise AnnouncementError("announcement_event_source_changed")
