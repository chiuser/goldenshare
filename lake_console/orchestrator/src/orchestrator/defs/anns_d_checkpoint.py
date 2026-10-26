"""Run-scoped durable execution evidence and process-safe file coordination."""

import fcntl
import hashlib
import json
import math
import os
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_VERSION,
    AnnouncementCancelled,
    AnnouncementError,
)


def assert_safe_announcement_path(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise AnnouncementError("announcement_unsafe_path")
    for node in reversed((path, *path.parents)):
        if (node.exists() or node.is_symlink()) and stat.S_ISLNK(node.lstat().st_mode):
            raise AnnouncementError("announcement_symlink")
    return path


def announcement_fsync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def announcement_atomic_json(path, document):
    path = assert_safe_announcement_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".partial")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    announcement_fsync_directory(path.parent)


def announcement_file_fingerprint(path):
    path = assert_safe_announcement_path(path)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_nlink != 1:
        raise AnnouncementError("announcement_not_regular_file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"size": path.stat().st_size, "sha256": digest.hexdigest()}


@contextmanager
def announcement_file_lock(path):
    path = assert_safe_announcement_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AnnouncementError("announcement_writer_busy") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class AnnouncementControl:
    def __init__(self, cancelled=lambda: False, emit=lambda event: None):
        self.cancelled, self.emit = cancelled, emit
        self.view = {}
        self.last_report = 0.0

    def check(self):
        if self.cancelled():
            raise AnnouncementCancelled("announcement_cancelled")

    def progress(self, **values):
        if any(
            self.view.get(key) != value
            for key, value in values.items()
            if key != "waiting"
        ):
            self.view["last_business_progress_at"] = time.time()
        self.view.update(values)
        self.last_report = time.monotonic()
        self.emit({**self.view, "updated_at": time.time(), "eta": "暂无法估算"})

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.check()
            if time.monotonic() - self.last_report >= 5:
                self.progress(waiting=True)
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        self.check()


class AnnouncementCheckpoint:
    def __init__(self, path, identity):
        self.path = assert_safe_announcement_path(path)
        self.identity = identity
        self.document = {
            "identity": identity,
            "phase": "planned",
            "contract_version": ANNOUNCEMENT_VERSION,
        }
        if self.path.exists():
            self.document = json.loads(self.path.read_text())
            if (
                self.document.get("contract_version") != ANNOUNCEMENT_VERSION
                or self.document["identity"] != identity
            ):
                raise AnnouncementError("announcement_checkpoint_identity")

    def save(self, **values):
        self.document.update(values)
        announcement_atomic_json(self.path, self.document)


class AnnouncementWindowBudget:
    """Persistent request counts; an executing window requires preinitialized evidence."""

    def __init__(
        self, path, window_id, policy, *, identity=None, require_existing=False
    ):
        self.path = assert_safe_announcement_path(path)
        self.window_id, self.policy = window_id, policy
        self.identity = identity
        self.require_existing = require_existing

    def initial_document(self):
        document = {
            "window_id": self.window_id,
            "requests": 0,
            "next_request": 0,
            "in_flight": False,
            "day_requests": {},
        }
        if self.identity is not None:
            document["identity"] = self.identity
        return document

    def _read(self):
        if not self.path.exists():
            if self.require_existing:
                raise AnnouncementError("announcement_window_budget_missing")
            return self.initial_document()
        try:
            document = json.loads(self.path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AnnouncementError("announcement_window_budget_invalid") from None
        if not isinstance(document, dict) or document.get("window_id") != self.window_id:
            raise AnnouncementError("announcement_window_identity")
        if self.identity is not None and document.get("identity") != self.identity:
            raise AnnouncementError("announcement_window_contract_changed")
        requests = document.get("requests")
        day_requests = document.get("day_requests")
        next_request = document.get("next_request")
        if (
            isinstance(requests, bool)
            or not isinstance(requests, int)
            or not 0 <= requests <= self.policy.max_window_requests
            or not isinstance(day_requests, dict)
            or not isinstance(document.get("in_flight"), bool)
            or isinstance(next_request, bool)
            or not isinstance(next_request, (int, float))
            or not math.isfinite(next_request)
            or next_request < 0
        ):
            raise AnnouncementError("announcement_window_budget_invalid")
        for day, count in day_requests.items():
            if (
                not isinstance(day, str)
                or isinstance(count, bool)
                or not isinstance(count, int)
                or not 0 <= count <= self.policy.max_day_requests
                or (
                    self.identity is not None
                    and day not in self.identity["days"]
                )
            ):
                raise AnnouncementError("announcement_window_budget_invalid")
        if sum(day_requests.values()) != requests:
            raise AnnouncementError("announcement_window_budget_invalid")
        if self.identity is not None and set(document) != set(self.initial_document()):
            raise AnnouncementError("announcement_window_budget_invalid")
        return document

    def claim(self, control, day):
        with announcement_file_lock(self.path.with_suffix(".lock")):
            document = self._read()
            if document["in_flight"]:
                raise AnnouncementError("announcement_request_in_flight")
            if document["requests"] >= self.policy.max_window_requests:
                raise AnnouncementError("announcement_window_budget")
            if document["day_requests"].get(day, 0) >= self.policy.max_day_requests:
                raise AnnouncementError("announcement_day_budget")
            if self.identity is not None and day not in self.identity["days"]:
                raise AnnouncementError("announcement_day_outside_window")
            control.wait(max(0, document["next_request"] - time.time()))
            control.check()
            document["requests"] += 1
            document["day_requests"][day] = document["day_requests"].get(day, 0) + 1
            document["in_flight"] = True
            announcement_atomic_json(self.path, document)
            return document["day_requests"][day]

    def finish(self):
        with announcement_file_lock(self.path.with_suffix(".lock")):
            document = self._read()
            document.update(
                in_flight=False, next_request=time.time() + self.policy.interval_seconds
            )
            announcement_atomic_json(self.path, document)

    def recover_interrupted(self):
        # Caller owns the exclusive source-execution lock; consumed claims are retained.
        with announcement_file_lock(self.path.with_suffix(".lock")):
            document = self._read()
            document.update(
                in_flight=False,
                next_request=max(
                    document["next_request"], time.time() + self.policy.interval_seconds
                ),
            )
            announcement_atomic_json(self.path, document)
