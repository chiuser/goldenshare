"""Monthly bootstrap file durability and permitted-path checks, without data SQL."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT


def check_monthly_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("monthly_path_invalid")
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise ValueError("monthly_symlink_forbidden")


def check_monthly_root(root: Path, *, staging: bool) -> None:
    check_monthly_path(root)
    canonical = Path(DEFAULT_LAKE_STAGING_ROOT if staging else DEFAULT_LAKE_ROOT)
    temporary = (Path("/private/tmp"), Path(tempfile.gettempdir()).resolve())
    if root != canonical and not any(root.is_relative_to(p) for p in temporary):
        raise ValueError("monthly_root_forbidden")
    if not root.is_dir():
        raise ValueError("monthly_root_must_exist")
    if root == canonical and not root.parent.is_mount():
        raise ValueError("monthly_volume_not_mounted")
    if not os.access(root, os.W_OK):
        raise ValueError("monthly_root_not_writable")


def check_monthly_free_space(root: Path, required_bytes: int) -> None:
    check_monthly_path(root)
    if shutil.disk_usage(root).free < required_bytes:
        raise ValueError("monthly_disk_budget_exceeded")


def monthly_file_hash(path: Path, *, max_bytes: int | None = None) -> str:
    check_monthly_path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        total = 0
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise ValueError("monthly_file_budget_exceeded")
            digest.update(chunk)
    return digest.hexdigest()


def sync_monthly_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sync_monthly_file(path: Path) -> None:
    check_monthly_path(path)
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def write_monthly_json(path: Path, payload: dict, max_bytes: int) -> None:
    check_monthly_path(path)
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    if len(encoded) > max_bytes:
        raise ValueError("monthly_control_budget_exceeded")
    pending = path.with_name("." + path.name + "." + uuid4().hex + ".pending")
    with pending.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)
    sync_monthly_directory(path.parent)


def read_monthly_json(path: Path, max_bytes: int) -> dict:
    check_monthly_path(path)
    with path.open("rb") as stream:
        encoded = stream.read(max_bytes + 1)
    if len(encoded) > max_bytes:
        raise ValueError("monthly_control_budget_exceeded")
    payload = json.loads(encoded)
    if not isinstance(payload, dict):
        raise ValueError("monthly_control_invalid")  # noqa: TRY004 - stable receipt reason code
    return payload


def check_monthly_cancel(cancel) -> None:
    if cancel():
        raise ValueError("monthly_cancelled")


@contextmanager
def monthly_file_lock(path: Path):
    check_monthly_path(path)
    with path.open("ab") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("monthly_writer_busy") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
