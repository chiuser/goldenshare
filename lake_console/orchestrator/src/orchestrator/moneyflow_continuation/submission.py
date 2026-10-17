"""Durable intent before one mutation; ambiguity is never retried."""

import fcntl
import os
import uuid
from contextlib import contextmanager

from orchestrator.moneyflow_continuation.contract import (
    CONTROL,
    POLICY,
    digest,
    encoded,
    file_hash,
    read_json,
    require,
    safe_path,
)
from orchestrator.moneyflow_continuation.plan import request_for
from orchestrator.moneyflow_continuation.recovery import (
    ACTION,
    RECOVERY_ACTIONS,
    action_layer,
    descriptor,
    recovery_actions,
    request,
)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path, value, *, immutable=False, limit=POLICY.action_bytes):
    path = safe_path(path)
    data = encoded(value)
    require(len(data) <= limit, "control_bytes")
    temporary = (
        path
        if immutable
        else path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    )
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    # Keep partial files on error: a crash must never manufacture "not sent".
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if not immutable:
        os.replace(temporary, path)
    sync_directory(path.parent)


def validate_new_output(path):
    from orchestrator.moneyflow_continuation.contract import REPO

    path = safe_path(path)
    require(
        any(
            root in path.parents
            for root in (safe_path("/private/tmp"), REPO / "lake_console/reports")
        ),
        "output_location",
        2,
    )
    require(
        path.parent.is_dir() and not path.exists(), "output_exists_or_parent_missing", 2
    )
    return path


def new_plan_output(path, value):
    write_json(validate_new_output(path), value, immutable=True, limit=POLICY.plan_bytes)


@contextmanager
def executor_lock(root=CONTROL):
    root = safe_path(root)
    root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        root / "executor.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            require(False, "another_executor")
        yield
    finally:
        os.close(descriptor)


class Journal:
    def __init__(self, plan, root=CONTROL):
        self.plan, self.root = plan, safe_path(root)
        self.directory = safe_path(root / plan["root_scope_digest"])

    def action_dir(self, unit, action):
        require(
            unit in self.plan["root_units"]
            and action in {"register", "raw", "silver", *RECOVERY_ACTIONS},
            "journal_scope",
        )
        if action in RECOVERY_ACTIONS:
            require(
                descriptor(self.plan, unit, action_layer(action)) is not None,
                "recovery_scope",
            )
        return safe_path(self.directory / unit["dataset"] / unit["trade_date"] / action)

    def read(self, unit, action):
        directory = self.action_dir(unit, action)
        files = {
            name: read_json(directory / (name + ".json"), POLICY.action_bytes)
            for name in ("request", "send_intent", "response", "observation")
            if (directory / (name + ".json")).exists()
        }
        require(not files or "request" in files, "journal_request_missing")
        if not files:
            return files
        request = files["request"]
        require(
            request.get("unit") == unit and request.get("action") == action,
            "journal_identity",
        )
        expected = self.body(
            unit, action, request.get("attempt_day"), request.get("raw_sha256")
        )
        require(
            request.get("body") == expected
            and request.get("scope") == self.plan["root_scope_digest"],
            "journal_request_changed",
        )
        for name in ("send_intent", "response", "observation"):
            if name in files:
                require(
                    files[name].get("request_sha256") == digest(request),
                    "journal_binding",
                )
        require(
            "response" not in files or "send_intent" in files, "journal_intent_missing"
        )
        return files

    def body(self, unit, action, at, raw_sha):
        if action in RECOVERY_ACTIONS:
            return request(
                descriptor(self.plan, unit, action_layer(action)), unit, raw_sha
            )
        return request_for(unit, action, at, raw_sha)

    def prepare(self, unit, action, at, raw_sha, facts):
        existing = self.read(unit, action)
        if existing:
            if action in {"silver", ACTION}:
                require(existing["request"]["raw_sha256"] == raw_sha, "raw_revision")
            return existing
        directory = self.action_dir(unit, action)
        directory.mkdir(parents=True, exist_ok=True)
        request = {
            "scope": self.plan["root_scope_digest"],
            "unit": unit,
            "action": action,
            "prepared_at": at.isoformat(),
            "attempt_day": at.date().isoformat(),
            "raw_sha256": raw_sha,
            "body": self.body(unit, action, at.date().isoformat(), raw_sha),
            "before": facts,
        }
        write_json(directory / "request.json", request, immutable=True)
        return self.read(unit, action)

    def observe(self, unit, action, fields):
        files = self.read(unit, action)
        require("request" in files, "journal_request_missing")
        value = {
            **files.get("observation", {}),
            **fields,
            "request_sha256": digest(files["request"]),
        }
        write_json(self.action_dir(unit, action) / "observation.json", value)

    def budget(self, key, maximum):
        path = safe_path(self.directory / "budgets.json")
        current = read_json(path, POLICY.action_bytes) if path.exists() else {}
        require(current.get(key, 0) < maximum, "read_budget", 4)
        current[key] = current.get(key, 0) + 1
        self.directory.mkdir(parents=True, exist_ok=True)
        write_json(path, current)

    def size(self):
        # Enumerate only the approved namespace; no recursive scan of historical staging.
        budget_file = safe_path(self.directory / "budgets.json")
        total = budget_file.stat().st_size if budget_file.exists() else 0
        require(total <= POLICY.action_bytes, "control_budget_size")
        for unit in self.plan["root_units"]:
            for action in (
                "register",
                "raw",
                "silver",
                *recovery_actions(self.plan, unit),
            ):
                directory = self.action_dir(unit, action)
                if directory.exists():
                    paths = list(directory.iterdir())
                    require(
                        len(paths) <= POLICY.control_entries_per_action,
                        "control_file_count",
                    )
                    for path in paths:
                        safe_path(path)
                        require(
                            path.is_file()
                            and path.stat().st_size <= POLICY.action_bytes,
                            "control_file_size",
                        )
                        total += path.stat().st_size
        require(total <= POLICY.control_bytes, "control_namespace_size")
        return total


def submit_once(backend, journal, unit, action, at, raw_sha=None):
    """Caller holds executor.lock. All mutation outcomes require native readback."""
    files = journal.read(unit, action)
    if files and action in {"silver", ACTION}:
        require(files["request"]["raw_sha256"] == raw_sha, "raw_revision")
    body = (
        files["request"]["body"]
        if files
        else journal.body(unit, action, at.date().isoformat(), raw_sha)
    )
    found = backend.reconcile(unit, action, body)
    if found:
        require(files and "send_intent" in files, "unrecorded_native_action")
        if "response" in files:
            backend.check_response(files["response"]["value"], action, found)
        return found
    require(not files or "send_intent" not in files, "uncertain_submission")
    backend.guard(journal.plan, at)
    require(not backend.stopping(), "operator_stopped", 130)
    files = journal.prepare(
        unit,
        action,
        at,
        raw_sha,
        {
            "native_absence_confirmed": True,
            "unrelated_source_changes": getattr(backend, "last_guard", {}).get(
                "unrelated_source_changes", []
            ),
            "read_policy": journal.plan["policy"],
        },
    )
    journal.size()
    request = files["request"]
    directory = journal.action_dir(unit, action)
    # Persist the observation budget before any HTTP request could reach the server.
    journal.observe(
        unit, action, {"started_at": at.isoformat(), "polls": 0, "native": None}
    )
    write_json(
        directory / "send_intent.json",
        {"request_sha256": digest(request), "at": at.isoformat()},
        immutable=True,
    )
    require(not backend.stopping(), "operator_stopped", 130)
    result = backend.mutate(request["body"])
    write_json(
        directory / "response.json",
        {"request_sha256": digest(request), "value": result},
        immutable=True,
    )
    found = backend.reconcile(unit, action, request["body"])
    require(found is not None, "mutation_not_visible")
    backend.check_response(result, action, found)
    return found


def verify_plan_file(path, expected):
    require(file_hash(path) == expected, "plan_sha256", 2)
    return read_json(path)
